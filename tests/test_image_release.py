import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jenkins_image_release", ROOT / "assets/image_release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SOURCE = "a" * 40
TOOLS = "b" * 40
IMAGE = "sha256:" + "c" * 64
FINAL = "sha256:" + "d" * 64
DIGEST = "sha256:" + "e" * 64


class ImageReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jenkins-image-release-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = SimpleNamespace(
            component="engine", source_sha=SOURCE, version="1.0.0", build_number=7,
            arch="amd64", source=self.root / "source", unsigned=self.root / "unsigned",
            sealed=self.root / "sealed", final=self.root / "final", records=self.root / "records",
            tools=self.root / "tools", tools_ref=TOOLS, key=self.root / "private.pem",
            output=self.root / "output", trust=self.root / "trust.json",
        )
        self.args.trust.write_text(json.dumps({name: "public fixture" for name in release.TRUST_VARIABLES}))
        self.metadata()

    def metadata(self):
        config = release.COMPONENTS[self.args.component]
        for arch in release.ARCHITECTURES:
            directory = self.args.unsigned / arch
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "payload").mkdir(exist_ok=True)
            release.write_json(directory / "metadata.json", {
                "component": self.args.component, "source_sha": SOURCE, "version": "1.0.0",
                "architecture": arch, "builder": release.BUILDERS[arch][0],
                "image": IMAGE, "project": f"/code/{config['repository']}",
                "tag": f"duckietown/{config['repository']}:ci-release-7-{SOURCE}-{arch}",
            })
            sealed = self.args.sealed / arch
            sealed.mkdir(parents=True, exist_ok=True)
            (sealed / config["manifest"]).write_bytes(b"signed inventory fixture")
            final = self.args.final / arch
            final.mkdir(parents=True, exist_ok=True)
            release.write_json(final / "image.json", {
                "image": FINAL, "runtime_sha256": hashlib.sha256(b"signed inventory fixture").hexdigest(),
            })

    def test_coordinates_reject_moving_refs_and_shell_injection(self):
        for source, version in (("ente", "1.0.0"), (SOURCE, "1.0.0; command"), ("A" * 40, "1.0.0")):
            with self.subTest(source=source, version=version), self.assertRaises(ValueError):
                release.coordinates("engine", source, version)

    def test_public_trust_requires_exactly_nine_nonempty_values(self):
        for value in ({}, {name: "" for name in release.TRUST_VARIABLES}, {"PRIVATE_KEY": "not allowed"}):
            self.args.trust.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "nine DTS public"):
                release.trust_environment(self.args.trust)

    def test_tools_require_matching_clean_checkout(self):
        with patch.object(release, "run", side_effect=[TOOLS, ""]):
            release.check_tools(self.args.tools, TOOLS)
        for output in ([SOURCE], [TOOLS, " M tools/engine_release.py"]):
            with patch.object(release, "run", side_effect=output), self.assertRaises(ValueError):
                release.check_tools(self.args.tools, TOOLS)

    def test_native_builder_failover_checks_architecture(self):
        for failed in (
            subprocess.CalledProcessError(1, ["docker"], stderr="unreachable"),
            subprocess.TimeoutExpired(["docker", "info"], 15),
        ):
            with self.subTest(failure=type(failed).__name__), patch.object(
                release, "docker", side_effect=[failed, "linux/aarch64\n"],
            ):
                self.assertEqual(release.BUILDERS["arm64v8"][1], release.select_builder("arm64v8"))
        with patch.object(release, "docker", return_value="linux/x86_64"), self.assertRaisesRegex(ValueError, "native Linux"):
            release.select_builder("arm64v8")

    def test_image_platform_must_match_the_native_builder_architecture(self):
        release.check_image_platform({"Os": "linux", "Architecture": "arm64"}, "arm64v8")
        for image in ({"Os": "linux", "Architecture": "amd64"}, {"Os": "windows", "Architecture": "arm64"}):
            with self.subTest(image=image), self.assertRaisesRegex(ValueError, "native Linux"):
                release.check_image_platform(image, "arm64v8")

    def test_metadata_requires_both_architectures_and_original_coordinates(self):
        self.assertEqual(set(release.ARCHITECTURES), set(release.load_metadata(self.args.unsigned, "engine", SOURCE, "1.0.0")))
        path = self.args.unsigned / "amd64/metadata.json"
        original = release.read_json(path)
        for change in (
            {"builder": "tcp://unapproved:2376"}, {"image": "mutable:tag"},
            {"project": "/code/../dt-duckiematrix"}, {"source_sha": TOOLS},
            {"component": "viewer"}, {"tag": "duckietown/dt-duckiematrix:ente-amd64"},
        ):
            with self.subTest(change=change):
                release.write_json(path, {**original, **change})
                with self.assertRaises(ValueError):
                    release.load_metadata(self.args.unsigned, "engine", SOURCE, "1.0.0")
        release.write_json(path, original)
        (self.args.unsigned / "arm64v8/metadata.json").unlink()
        with self.assertRaises(FileNotFoundError):
            release.load_metadata(self.args.unsigned, "engine", SOURCE, "1.0.0")

    def test_build_extracts_stopped_image_without_running_code_or_publishing(self):
        calls = []

        def docker(builder, *command, **kwargs):
            calls.append(command)
            if command[0] == "create":
                return "container-fixture\n"
            return ""

        image = {
            "Id": IMAGE, "Os": "linux", "Architecture": "amd64",
            "Config": {"Labels": {"org.duckietown.label.project.path": "/code/dt-duckiematrix"}},
        }
        with patch.object(release, "run", side_effect=[SOURCE, ""]), patch.object(
            release, "select_builder", return_value=release.BUILDERS["amd64"][0],
        ), patch.object(release, "inspect_image", return_value=image), patch.object(release, "docker", side_effect=docker):
            release.build(self.args)
        self.assertEqual(IMAGE, release.read_json(self.args.output / "metadata.json")["image"])
        self.assertEqual(["build", "create", "cp", "rm"], [call[0] for call in calls])
        self.assertNotIn("--push", calls[0])
        self.assertFalse(any("SIGNING" in argument for argument in calls[0]))

    def test_failed_image_extraction_removes_the_stopped_container(self):
        def docker(builder, *command, **kwargs):
            if command[0] == "create":
                return "container-fixture"
            if command[0] == "cp":
                raise subprocess.CalledProcessError(1, ["docker", "cp"])
            return ""

        image = {
            "Id": IMAGE, "Os": "linux", "Architecture": "amd64",
            "Config": {"Labels": {"org.duckietown.label.project.path": "/code/dt-duckiematrix"}},
        }
        with patch.object(release, "run", side_effect=[SOURCE, ""]), patch.object(
            release, "select_builder", return_value=release.BUILDERS["amd64"][0],
        ), patch.object(release, "inspect_image", return_value=image), patch.object(
            release, "docker", side_effect=docker,
        ) as command:
            with self.assertRaises(subprocess.CalledProcessError):
                release.build(self.args)
        self.assertEqual(("rm", "container-fixture"), command.call_args.args[1:])

    def test_sealing_rejects_existing_manifests_and_dangling_symlinks(self):
        manifest = self.args.unsigned / "amd64/payload/duckiematrix-engine.release.json"
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    manifest.symlink_to(self.root / "missing")
                else:
                    manifest.write_bytes(b"old manifest")
                self.args.output = self.root / f"seal-rejected-{symlink}"
                with patch.object(release, "check_tools"), patch.object(
                    release, "run",
                ) as command, self.assertRaisesRegex(ValueError, "manifest or manifest symlink"):
                    release.seal(self.args)
                command.assert_not_called()
                manifest.unlink()

    def finalize_check(self, builder, image, script, **kwargs):
        if script == release.PYTHON_PATH + release.DENY_ENGINE or script == release.PYTHON_PATH + release.DENY_VIEWER:
            raise subprocess.CalledProcessError(1, ["docker", "run"], stderr="requires a live authorized DTS session")

    def test_finalization_checks_native_trust_direct_denial_and_engine_core(self):
        with patch.object(release, "inspect_image", side_effect=lambda builder, tag: {
            "Id": IMAGE if ":ci-release-" in tag else FINAL,
            "Os": "linux", "Architecture": "amd64" if tag.endswith("amd64") else "arm64",
        }), patch.object(release, "docker") as docker, patch.object(
            release, "image_check", side_effect=self.finalize_check,
        ) as check:
            release.finalize(self.args)
        self.assertEqual(6, check.call_count)
        self.assertTrue(any(release.DENY_CORE in call.args[2] for call in check.call_args_list))
        self.assertTrue(any("EXTENSION_SUFFIXES" in call.args[2] for call in check.call_args_list))
        self.assertFalse(any(call.args[1] in ("login", "push") for call in docker.call_args_list))
        self.assertEqual(FINAL, release.read_json(self.args.output / "amd64/image.json")["image"])

    def test_viewer_finalization_checks_backend_inventory_and_startup_denial(self):
        self.args.component = "viewer"
        self.metadata()
        with patch.object(release, "inspect_image", side_effect=lambda builder, tag: {
            "Id": IMAGE if ":ci-release-" in tag else FINAL,
            "Os": "linux", "Architecture": "amd64" if tag.endswith("amd64") else "arm64",
        }), patch.object(release, "docker"), patch.object(
            release, "image_check", side_effect=self.finalize_check,
        ) as check:
            release.finalize(self.args)
        self.assertEqual(4, check.call_count)
        self.assertTrue(any('kind="backend"' in call.args[2] for call in check.call_args_list))
        self.assertFalse(any(release.DENY_CORE in call.args[2] for call in check.call_args_list))

    def test_finalization_does_not_accept_unrelated_startup_errors(self):
        def check(builder, image, script, **kwargs):
            if script == release.PYTHON_PATH + release.DENY_ENGINE:
                raise subprocess.CalledProcessError(1, ["docker"], stderr="ModuleNotFoundError")

        with patch.object(release, "inspect_image", return_value={"Id": IMAGE}), patch.object(
            release, "docker",
        ), patch.object(
            release, "image_check", side_effect=check,
        ), self.assertRaisesRegex(RuntimeError, "other than missing DTS"):
            release.finalize(self.args)

    def test_container_checks_preserve_stderr_denial_and_remove_owned_container(self):
        with patch.object(
            release, "docker", side_effect=["fixture-container", "", "1", "requires a live authorized DTS session", ""],
        ) as docker, self.assertRaises(subprocess.CalledProcessError) as failure:
            release.image_check(release.BUILDERS["amd64"][0], "image", "script")
        self.assertIn("requires a live", failure.exception.stdout)
        self.assertTrue(docker.call_args_list[3].kwargs["combined"])
        self.assertEqual(("rm", "--force", "fixture-container"), docker.call_args.args[1:])

    def test_stalled_container_checks_force_remove_their_own_container(self):
        with patch.object(release, "docker", side_effect=[
            "fixture-container", "", subprocess.TimeoutExpired(["docker", "wait"], 120), "",
        ]) as docker, self.assertRaises(subprocess.TimeoutExpired):
            release.image_check(release.BUILDERS["amd64"][0], "image", "script")
        self.assertEqual(("rm", "--force", "fixture-container"), docker.call_args.args[1:])

    def test_unsigned_image_substitution_fails_before_execution(self):
        with patch.object(release, "inspect_image", return_value={"Id": FINAL}), patch.object(
            release, "docker",
        ) as docker, self.assertRaisesRegex(ValueError, "changed"):
            release.finalize(self.args)
        docker.assert_not_called()

    def test_existing_or_unavailable_registry_tag_cannot_be_overwritten(self):
        with patch.object(release, "docker", return_value="{}"), self.assertRaisesRegex(ValueError, "already exists"):
            release.require_new_tag(release.BUILDERS["amd64"][0], "release:1.0.0", {})
        for message in ("unauthorized", "network is unreachable", "TLS verification failed"):
            failed = subprocess.CalledProcessError(1, ["docker"], stderr=message)
            with self.subTest(message=message), patch.object(
                release, "docker", side_effect=failed,
            ), self.assertRaisesRegex(RuntimeError, "publication refused"):
                release.require_new_tag(release.BUILDERS["amd64"][0], "release:1.0.0", {})

    def publish_docker(self, builder, *command, **kwargs):
        if command[0] == "manifest":
            raise subprocess.CalledProcessError(1, ["docker"], stderr="no such manifest")
        if command[0] == "push":
            return f"pushed: digest: {DIGEST} size: 1234\n"
        return ""

    def test_publish_records_registry_manifest_digest_and_config_separately(self):
        with patch.dict(os.environ, {"DOCKER_USERNAME": "fixture", "DOCKER_PASSWORD": "test-only"}), patch.object(
            release, "run", return_value="",
        ) as login, patch.object(release, "inspect_image", return_value={"Id": FINAL}), patch.object(
            release, "docker", side_effect=self.publish_docker,
        ) as docker:
            release.publish(self.args)
        images = release.read_json(self.args.output / "images.json")
        self.assertEqual(set(release.ARCHITECTURES), set(images))
        self.assertEqual("duckietown/dt-duckiematrix@" + DIGEST, images["amd64"]["reference"])
        self.assertEqual(FINAL.removeprefix("sha256:"), images["amd64"]["config_sha256"])
        self.assertNotIn("test-only", json.dumps(images))
        self.assertFalse(Path(login.call_args.kwargs["env"]["DOCKER_CONFIG"]).exists())
        self.assertFalse(any(call.args[1] == "run" for call in docker.call_args_list))

    def test_publishing_checks_both_images_before_any_push(self):
        path = self.args.final / "arm64v8/image.json"
        release.write_json(path, {"image": "not immutable", "runtime_sha256": "f" * 64})
        with patch.dict(os.environ, {"DOCKER_USERNAME": "fixture", "DOCKER_PASSWORD": "test-only"}), patch.object(
            release, "run", return_value="",
        ), patch.object(release, "inspect_image", return_value={"Id": FINAL}), patch.object(
            release, "docker", side_effect=self.publish_docker,
        ) as docker, self.assertRaisesRegex(ValueError, "identity is invalid"):
            release.publish(self.args)
        self.assertFalse(any(call.args[1] == "push" for call in docker.call_args_list))

    def test_catalog_refuses_missing_architecture_and_changed_inventory(self):
        self.args.records.mkdir()
        release.write_json(self.args.records / "images.json", {"amd64": {}})
        with patch.object(release, "check_tools"), self.assertRaisesRegex(ValueError, "Both amd64"):
            release.catalog(self.args)
        release.write_json(self.args.records / "images.json", {arch: {} for arch in release.ARCHITECTURES})
        with patch.object(release, "check_tools"), self.assertRaisesRegex(ValueError, "sealed manifest"):
            release.catalog(self.args)

    def test_cli_preserves_the_original_container_error_output(self):
        arguments = [
            "dt-ci-image-release", "build", "--component", "engine", "--source-sha", SOURCE,
            "--version", "1.0.0", "--source", str(self.args.source), "--arch", "amd64",
            "--build-number", "7", "--output", str(self.args.output),
        ]
        output = io.StringIO()
        with patch.object(sys, "argv", arguments), patch.object(
            release, "build", side_effect=subprocess.CalledProcessError(
                1, ["docker", "start", "owned-container"], output="Original native guard validation error",
            ),
        ), patch.object(sys, "stderr", output):
            self.assertEqual(1, release.main())
        self.assertIn("Original native guard validation error", output.getvalue())

    def test_offline_sealing_and_catalog_with_actual_shell_tools_for_both_components(self):
        tools = os.environ.get("DTS_RELEASE_TOOLS_CHECKOUT")
        if not tools:
            self.skipTest("Set DTS_RELEASE_TOOLS_CHECKOUT to exercise actual reviewed Shell signing tools.")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        def public(key):
            return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

        environment = {}
        private = {}
        for variable in release.TRUST_VARIABLES:
            if variable.endswith("_KEYS"):
                environment[variable] = json.dumps({
                    issuer: public(Ed25519PrivateKey.generate()) for issuer in (
                        "https://hub.duckietown.com", "https://staging-hub.duckietown.com",
                    )
                })
            else:
                private[variable] = Ed25519PrivateKey.generate()
                environment[variable] = public(private[variable])
        self.args.trust.write_text(json.dumps(environment))
        self.args.tools = Path(tools)
        for component in release.COMPONENTS:
            with self.subTest(component=component):
                self.args.component = component
                config = release.COMPONENTS[component]
                self.metadata()
                self.args.key.write_bytes(private[config["release_key"]].private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
                ))
                for arch in release.ARCHITECTURES:
                    payload = self.args.unsigned / arch / "payload"
                    protected = payload / "packages" / ("duckiematrix_engine" if component == "engine" else "duckietown_viewer")
                    protected.mkdir(parents=True, exist_ok=True)
                    modules = ("bootstrap", "engine") if component == "engine" else ("main", "app", "authorization")
                    for name in modules:
                        (protected / f"{name}.fixture.so").write_bytes(b"native fixture, not executable")
                self.args.output = self.root / f"sealed-{component}"
                with patch.object(release, "check_tools"), patch.object(release, "docker") as docker:
                    release.seal(self.args)
                docker.assert_not_called()
                self.args.sealed = self.args.output
                records = self.root / f"records-{component}"
                records.mkdir()
                release.write_json(records / "images.json", {
                    arch: {
                        "reference": f"duckietown/{config['repository']}@{DIGEST}",
                        "config_sha256": FINAL.removeprefix("sha256:"),
                        "runtime_sha256": hashlib.sha256((self.args.sealed / arch / config["manifest"]).read_bytes()).hexdigest(),
                    } for arch in release.ARCHITECTURES
                })
                self.args.records = records
                self.args.output = self.root / f"catalog-{component}"
                with patch.object(release, "check_tools"), patch.object(release, "docker") as docker:
                    release.catalog(self.args)
                docker.assert_not_called()
                envelope = release.read_json(self.args.output / config["catalog"])
                payload = base64.b64decode(envelope["payload"], validate=True)
                private[config["release_key"]].public_key().verify(
                    base64.b64decode(envelope["signature"], validate=True), payload,
                )
                claims = json.loads(payload)
                self.assertEqual("duckiematrix-engine-images" if component == "engine" else "duckietown-viewer-backends", claims["audience"])
                self.assertEqual("ente", claims["distribution"])
                self.assertEqual(set(release.ARCHITECTURES), set(claims["images"]))
                self.assertEqual("1.0.0", claims["version"])
                self.assertEqual(SOURCE, release.read_json(self.args.output / "release.json")["source_sha"])


if __name__ == "__main__":
    unittest.main()
