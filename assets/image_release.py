#!/usr/bin/env python3
"""Jenkins image releases: build remotely, sign offline, verify, then publish."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ARCHITECTURES = ("amd64", "arm64v8")
BUILDERS = {
    "amd64": ("tcp://172.27.0.101:2376",),
    "arm64v8": (
        "tcp://172.27.0.126:2376",
        "tcp://172.27.0.43:2376",
        "tcp://172.27.0.250:2376",
    ),
}
COMPONENTS = {
    "engine": {
        "repository": "dt-duckiematrix",
        "manifest": "duckiematrix-engine.release.json",
        "catalog": "engines.json",
        "guard": "duckietown_engine_guard",
        "release_key": "DTM_ENGINE_RELEASE_PUBLIC_KEY",
        "issuer_keys": "DTM_ENGINE_PUBLIC_KEYS",
        "description": "The Duckiematrix Engine",
    },
    "viewer": {
        "repository": "dt-duckietown-viewer",
        "manifest": "duckietown-viewer.release.json",
        "catalog": "backends.json",
        "guard": "duckietown_viewer_guard",
        "release_key": "DTV_RELEASE_PUBLIC_KEY",
        "issuer_keys": "DTV_AUTH_PUBLIC_KEYS",
        "description": "The Duckietown Viewer",
    },
}
TRUST_VARIABLES = (
    "DTS_RELEASE_PUBLIC_KEY", "DTS_COMMANDS_PUBLIC_KEY", "DTS_DEVELOPER_PUBLIC_KEYS",
    "DTM_RELEASE_PUBLIC_KEY", "DTM_RENDERER_PUBLIC_KEYS",
    "DTV_RELEASE_PUBLIC_KEY", "DTV_AUTH_PUBLIC_KEYS",
    "DTM_ENGINE_RELEASE_PUBLIC_KEY", "DTM_ENGINE_PUBLIC_KEYS",
)
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
SOURCE_SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def run(command: list[str], *, capture=False, combined=False, env=None, input=None, cwd=None, timeout=3600) -> str:
    result = subprocess.run(
        command, check=True, text=True, stdout=subprocess.PIPE if capture else None,
        stderr=(subprocess.STDOUT if combined else subprocess.PIPE) if capture else None,
        env=env, input=input, cwd=cwd, timeout=timeout,
    )
    return result.stdout if capture else ""


def docker(builder: str, *arguments: str, **kwargs) -> str:
    return run(["docker", "--host", builder, *arguments], **kwargs)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def coordinates(component: str, source_sha: str, version: str) -> dict:
    if component not in COMPONENTS or not SOURCE_SHA.fullmatch(source_sha) or not VERSION.fullmatch(version):
        raise ValueError("A known component, full lowercase source SHA and x.y.z version are required.")
    return COMPONENTS[component]


def trust_environment(path: Path) -> dict[str, str]:
    trust = read_json(path)
    if set(trust) != set(TRUST_VARIABLES) or any(
        not isinstance(value, str) or not value for value in trust.values()
    ):
        raise ValueError("The public trust file must contain all nine DTS public environment values as strings.")
    return {**os.environ, **trust}


def check_tools(root: Path, expected: str) -> None:
    if not SOURCE_SHA.fullmatch(expected):
        raise ValueError("Release tools must be pinned to an approved full Shell commit.")
    if run(["git", "-C", str(root), "rev-parse", "HEAD"], capture=True).strip() != expected:
        raise ValueError("The release tools checkout does not match the approved commit.")
    if run(["git", "-C", str(root), "status", "--porcelain"], capture=True).strip():
        raise ValueError("The release tools checkout must be clean.")


def select_builder(architecture: str) -> str:
    expected = {"amd64": {"x86_64", "amd64"}, "arm64v8": {"aarch64", "arm64"}}[architecture]
    for builder in BUILDERS[architecture]:
        try:
            value = docker(builder, "info", "--format", "{{.OSType}}/{{.Architecture}}", capture=True, timeout=15).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = (error.stderr or str(error)) if isinstance(error, subprocess.CalledProcessError) else str(error)
            print(f"Builder {builder} is unavailable: {detail}", file=sys.stderr)
            continue
        if value not in {f"linux/{arch}" for arch in expected}:
            raise ValueError(f"Builder {builder} reports {value!r}, not native Linux {architecture}.")
        return builder
    raise RuntimeError(f"No native {architecture} Jenkins builder is available.")


def inspect_image(builder: str, reference: str) -> dict:
    image, = json.loads(docker(builder, "image", "inspect", reference, capture=True, timeout=30))
    if not SHA256.fullmatch(image["Id"]):
        raise ValueError("Docker did not return an immutable image configuration ID.")
    return image


def check_image_platform(image: dict, architecture: str) -> None:
    expected = "amd64" if architecture == "amd64" else "arm64"
    if image.get("Os") != "linux" or image.get("Architecture") != expected:
        raise ValueError(f"The image is not a native Linux {architecture} build.")


def load_metadata(root: Path, component: str, source_sha: str, version: str) -> dict[str, dict]:
    config = coordinates(component, source_sha, version)
    result = {}
    for arch in ARCHITECTURES:
        metadata = read_json(root / arch / "metadata.json")
        if set(metadata) != {
            "component", "source_sha", "version", "architecture", "builder", "image", "project", "tag",
        } or any(metadata[key] != value for key, value in {
            "component": component, "source_sha": source_sha, "version": version, "architecture": arch,
        }.items()):
            raise ValueError(f"The {arch} image metadata does not match this approved release.")
        project = metadata["project"]
        if (
            metadata["builder"] not in BUILDERS[arch]
            or not isinstance(metadata["image"], str) or not SHA256.fullmatch(metadata["image"])
            or not isinstance(project, str)
            or not re.fullmatch(r"/[a-zA-Z0-9/_-]+/" + config["repository"], project)
            or ".." in project.split("/")
            or not isinstance(metadata["tag"], str)
            or not re.fullmatch(
                "duckietown/" + config["repository"] + r":ci-release-[0-9]+-" + source_sha + "-" + arch,
                metadata["tag"],
            )
        ):
            raise ValueError(f"The {arch} image metadata has an invalid builder, path or identity.")
        result[arch] = metadata
    return result


def build(args) -> None:
    config = coordinates(args.component, args.source_sha, args.version)
    if args.build_number <= 0:
        raise ValueError("A positive Jenkins build number is required.")
    actual = run(["git", "-C", str(args.source), "rev-parse", "HEAD"], capture=True).strip()
    if actual != args.source_sha:
        raise ValueError("The source checkout does not match the approved commit.")
    if run(["git", "-C", str(args.source), "status", "--porcelain"], capture=True).strip():
        raise ValueError("The source checkout must be clean before building.")
    builder = select_builder(args.arch)
    tag = f"duckietown/{config['repository']}:ci-release-{args.build_number}-{args.source_sha}-{args.arch}"
    args.output.mkdir(parents=True, exist_ok=False)
    docker(
        builder, "build", "--pull", "--no-cache", "--tag", tag,
        "--build-arg", f"ARCH={args.arch}", "--build-arg", "DISTRO=ente",
        "--build-arg", "DOCKER_REGISTRY=docker.io", "--build-arg", "BASE_REPOSITORY=dt-commons",
        "--build-arg", f"PROJECT_NAME={config['repository']}",
        "--build-arg", f"PROJECT_DESCRIPTION={config['description']}",
        "--build-arg", "PROJECT_MAINTAINER=Duckietown", "--build-arg", "PROJECT_FORMAT_VERSION=4",
        str(args.source.resolve()), env={**os.environ, "DOCKER_BUILDKIT": "1"},
    )
    image = inspect_image(builder, tag)
    check_image_platform(image, args.arch)
    project = image["Config"]["Labels"]["org.duckietown.label.project.path"]
    if not isinstance(project, str) or not re.fullmatch(r"/[a-zA-Z0-9/_-]+/" + config["repository"], project):
        raise ValueError("The image project path is not the expected absolute repository path.")
    container = docker(builder, "create", "--entrypoint", "/bin/true", image["Id"], capture=True).strip()
    try:
        payload = args.output / "payload"
        payload.mkdir()
        docker(builder, "cp", f"{container}:{project}/.", str(payload.resolve()))
    finally:
        docker(builder, "rm", container)
    write_json(args.output / "metadata.json", {
        "component": args.component, "source_sha": args.source_sha, "version": args.version,
        "architecture": args.arch, "builder": builder, "image": image["Id"], "project": project, "tag": tag,
    })


def seal(args) -> None:
    config = coordinates(args.component, args.source_sha, args.version)
    metadata = load_metadata(args.unsigned, args.component, args.source_sha, args.version)
    check_tools(args.tools, args.tools_ref)
    environment = trust_environment(args.trust)
    args.output.mkdir(parents=True, exist_ok=False)
    for arch in metadata:
        payload = args.unsigned / arch / "payload"
        manifest = payload / config["manifest"]
        if manifest.exists() or manifest.is_symlink():
            raise ValueError("An unsigned image must not already contain a release manifest or manifest symlink.")
        command = [
            sys.executable, str(args.tools / "tools" / f"{args.component}_release.py"), "seal", str(payload),
            "--version", args.version, "--platform", "linux" if arch == "amd64" else "linux-arm64",
            "--key", str(args.key),
        ]
        if args.component == "viewer":
            command += ["--kind", "backend", "--entrypoint", "packages/duckietown_viewer"]
        run(command, env=environment)
        destination = args.output / arch
        destination.mkdir()
        shutil.copyfile(manifest, destination / config["manifest"])


VERIFY_ENGINE = """
guard.verify_release(root, release_key=trust[0], issuer_keys=trust[1])
"""
VERIFY_VIEWER = """
guard.verify_release(root, release_key=trust[0], issuer_keys=trust[1], kind="backend")
"""
DENY_ENGINE = """
from duckiematrix_engine.main import main
main()
"""
DENY_VIEWER = """
from duckietown_viewer.main import main
main()
"""
DENY_CORE = """
import argparse
from packages.duckiematrix_engine.engine import MatrixEngine
from duckietown_engine_guard import EngineAuthorizationError
try:
    MatrixEngine(argparse.Namespace())
except EngineAuthorizationError:
    pass
else:
    raise AssertionError("The compiled Engine core must require its authorized bootstrap.")
"""
PYTHON_PATH = """
import os, sys
from pathlib import Path
root = Path(os.environ["DT_PROJECT_PATH"])
sys.path[:0] = [str(root), str(root / "packages")]
"""


def image_check(builder: str, image: str, script: str, *, environment=None, variables=()) -> None:
    arguments = ["create", "--network", "none", "--entrypoint", "python3"]
    for variable in variables:
        arguments += ["-e", variable]
    container = docker(builder, *arguments, image, "-c", script, capture=True, env=environment).strip()
    try:
        docker(builder, "start", container, env=environment)
        status = docker(builder, "wait", container, capture=True, timeout=120).strip()
        output = docker(builder, "logs", container, capture=True, combined=True)
        if not re.fullmatch(r"[0-9]+", status):
            raise ValueError("Docker did not return a container exit status.")
        if int(status) != 0:
            raise subprocess.CalledProcessError(int(status), ["docker", "start", container], output=output)
    finally:
        docker(builder, "rm", "--force", container)


def finalize(args) -> None:
    config = coordinates(args.component, args.source_sha, args.version)
    metadata = load_metadata(args.unsigned, args.component, args.source_sha, args.version)
    environment = trust_environment(args.trust)
    args.output.mkdir(parents=True, exist_ok=False)
    for arch, original in metadata.items():
        builder = original["builder"]
        if inspect_image(builder, original["tag"])["Id"] != original["image"]:
            raise ValueError("The unsigned image tag changed after its runtime was extracted.")
        manifest = args.sealed / arch / config["manifest"]
        destination = args.output / arch
        destination.mkdir()
        tag = f"duckietown/{config['repository']}:{args.component}-{args.version}-{arch}"
        with tempfile.TemporaryDirectory(prefix="sealed-image-") as temporary:
            context = Path(temporary)
            shutil.copyfile(manifest, context / config["manifest"])
            (context / "Dockerfile").write_text(
                f"FROM {original['tag']}\nCOPY {config['manifest']} "
                f"{original['project']}/{config['manifest']}\n", encoding="ascii",
            )
            docker(builder, "build", "--tag", tag, str(context))
        verification = PYTHON_PATH + (
            f"\nimport json, {config['guard']} as guard\n"
            "from importlib.machinery import EXTENSION_SUFFIXES\n"
            "assert guard.__file__.endswith(tuple(EXTENSION_SUFFIXES)), 'The guard must be a native extension.'\n"
            f'trust = (os.environ["{config["release_key"]}"], json.loads(os.environ["{config["issuer_keys"]}"]))\n'
            "assert guard.native_trust() == trust, 'The native guard has unexpected public trust.'\n"
        ) + (VERIFY_ENGINE if args.component == "engine" else VERIFY_VIEWER)
        image_check(
            builder, tag, verification, environment=environment,
            variables=(config["release_key"], config["issuer_keys"]),
        )
        try:
            image_check(
                builder, tag,
                PYTHON_PATH + (DENY_ENGINE if args.component == "engine" else DENY_VIEWER),
            )
        except subprocess.CalledProcessError as error:
            output = (error.stdout or "") + (error.stderr or "")
            if "requires a live authorized DTS session" not in output:
                raise RuntimeError(
                    f"Direct startup failed for a reason other than missing DTS authorization:\n{output}"
                ) from error
        else:
            raise RuntimeError("An application without a live DTS handoff must not start.")
        if args.component == "engine":
            image_check(builder, tag, PYTHON_PATH + DENY_CORE)
        final = inspect_image(builder, tag)
        check_image_platform(final, arch)
        write_json(destination / "image.json", {
            "image": final["Id"], "runtime_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        })


def require_new_tag(builder: str, tag: str, environment: dict) -> None:
    try:
        docker(builder, "manifest", "inspect", tag, capture=True, env=environment, timeout=60)
    except subprocess.CalledProcessError as error:
        message = ((error.stdout or "") + (error.stderr or "")).lower()
        if "no such manifest" in message or "manifest unknown" in message:
            return
        raise RuntimeError(
            f"Cannot determine whether the release tag already exists; publication refused:\n{message}"
        ) from error
    raise ValueError(f"Release tag {tag} already exists. Choose a new version.")


def publish(args) -> None:
    config = coordinates(args.component, args.source_sha, args.version)
    metadata = load_metadata(args.unsigned, args.component, args.source_sha, args.version)
    username = os.environ.get("DOCKER_USERNAME", "")
    password = os.environ.get("DOCKER_PASSWORD", "")
    if not username or not password:
        raise ValueError("Jenkins Docker publishing credentials are required.")
    images = {}
    with tempfile.TemporaryDirectory(prefix="release-docker-login-") as temporary:
        environment = {**os.environ, "DOCKER_CONFIG": temporary}
        run(["docker", "login", "docker.io", "--username", username, "--password-stdin"], input=password, env=environment)
        for arch, original in metadata.items():
            builder = original["builder"]
            tag = f"duckietown/{config['repository']}:{args.component}-{args.version}-{arch}"
            final = read_json(args.final / arch / "image.json")
            if set(final) != {"image", "runtime_sha256"} or not isinstance(final["image"], str) or not SHA256.fullmatch(final["image"]):
                raise ValueError("The verified final image identity is invalid.")
            if inspect_image(builder, tag)["Id"] != final["image"]:
                raise ValueError("The final image tag changed after verification.")
            manifest = args.sealed / arch / config["manifest"]
            if hashlib.sha256(manifest.read_bytes()).hexdigest() != final["runtime_sha256"]:
                raise ValueError("The sealed runtime changed after image verification.")
            require_new_tag(builder, tag, environment)
        for arch, original in metadata.items():
            builder = original["builder"]
            tag = f"duckietown/{config['repository']}:{args.component}-{args.version}-{arch}"
            final = read_json(args.final / arch / "image.json")
            output = docker(builder, "push", tag, capture=True, env=environment)
            print(output, end="")
            digests = re.findall(r"digest: (sha256:[0-9a-f]{64})", output)
            if len(digests) != 1:
                raise ValueError("Docker push did not return exactly one immutable manifest digest.")
            reference = f"duckietown/{config['repository']}@{digests[0]}"
            docker(builder, "pull", reference, env=environment)
            if inspect_image(builder, reference)["Id"] != final["image"]:
                raise ValueError("The published manifest does not resolve to the verified image.")
            images[arch] = {
                "reference": reference, "config_sha256": final["image"].removeprefix("sha256:"),
                "runtime_sha256": final["runtime_sha256"],
            }
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "images.json", images)


def catalog(args) -> None:
    config = coordinates(args.component, args.source_sha, args.version)
    check_tools(args.tools, args.tools_ref)
    images = read_json(args.records / "images.json")
    if set(images) != set(ARCHITECTURES):
        raise ValueError("Both amd64 and arm64v8 records are required before signing a catalog.")
    for arch, record in images.items():
        manifest = args.sealed / arch / config["manifest"]
        if not isinstance(record, dict) or record.get("runtime_sha256") != hashlib.sha256(manifest.read_bytes()).hexdigest():
            raise ValueError("The published runtime does not match its sealed manifest.")
    args.output.mkdir(parents=True, exist_ok=False)
    run([
        sys.executable, str(args.tools / "tools" / f"{args.component}_release.py"), "catalog",
        str(args.records / "images.json"), "--version", args.version, "--key", str(args.key),
        "--output", str(args.output / config["catalog"]),
    ], env=trust_environment(args.trust))
    write_json(args.output / "release.json", {
        "component": args.component, "source_sha": args.source_sha, "tools_sha": args.tools_ref,
        "version": args.version, "images": images,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, function in (
        ("build", build), ("seal", seal), ("finalize", finalize), ("publish", publish), ("catalog", catalog),
    ):
        command = commands.add_parser(name)
        command.set_defaults(function=function)
        command.add_argument("--component", required=True, choices=COMPONENTS)
        command.add_argument("--source-sha", required=True)
        command.add_argument("--version", required=True)
        command.add_argument("--output", required=True, type=Path)
        if name == "build":
            command.add_argument("--arch", required=True, choices=ARCHITECTURES)
            command.add_argument("--source", required=True, type=Path)
            command.add_argument("--build-number", required=True, type=int)
        if name in ("seal", "finalize", "publish"):
            command.add_argument("--unsigned", required=True, type=Path)
        if name in ("finalize", "publish", "catalog"):
            command.add_argument("--sealed", required=True, type=Path)
        if name == "publish":
            command.add_argument("--final", required=True, type=Path)
        if name == "catalog":
            command.add_argument("--records", required=True, type=Path)
        if name in ("seal", "catalog"):
            command.add_argument("--tools", required=True, type=Path)
            command.add_argument("--tools-ref", required=True)
            command.add_argument("--key", required=True, type=Path)
        if name in ("seal", "finalize", "catalog"):
            command.add_argument("--trust", type=Path, default=Path("/etc/duckietown/image-release-trust.json"))
    args = parser.parse_args()
    try:
        args.function(args)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Image release failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            if error.stdout:
                print(error.stdout, file=sys.stderr)
            if error.stderr:
                print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
