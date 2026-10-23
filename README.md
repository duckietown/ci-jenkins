# CI Jenkins

Jenkins application image for the Duckietown CI Infrastructure.

## Updating Duckietown Shell

The image-level `dts` installation is controlled by the
`duckietown-shell` requirement in `dependencies-py3.dt.txt`. Pin a specific
release when upgrading Jenkins:

```text
duckietown-shell==<target-version>
```

The existing version range permits compatible releases, but rebuilding without
changing the requirement can reuse Docker's dependency-install layer. Use a
no-cache rebuild when intentionally taking the newest version permitted by the
range.

Build and publish the production image from this directory:

```sh
dts devel build \
  --arch amd64 \
  --tag production \
  --push
```

`--arch amd64` produces the architecture-specific image, `--tag production`
selects the production tag, and `--push` publishes
`docker.io/duckietown/ci-jenkins:production-amd64`. Add `--no-cache` when
keeping the version range and deliberately taking its newest compatible
release. After the image is published, deploy it on the CI host:

```sh
cd /home/shared/dt-davinci-deployment/ci.duckietown.com
make update
make production-up-d
```

Verify the installed package in the running Jenkins container:

```sh
. ./deployment.sh
docker compose -p production-ci exec jenkins bash -lc \
  'python3 -c "from importlib.metadata import version; print(version(\"duckietown-shell\"))"'
```

The mounted `user-shell` volume provides the `ente` and `daffy` command
profiles. It is separate from the image-level `duckietown-shell` package
version.

## Protected Ente image releases

Docker images are built by Jenkins, not GitHub Actions. The existing generated
`Docker Autobuild - ente - ... - ARCH` jobs still build/push ordinary CI tags.
Those unsigned tags are not approved Ente Engine/Viewer releases.

The jobs repository adds two **manually triggered** Pipeline jobs:

- `Protected Image Release - ente - dt-duckiematrix`
- `Protected Image Release - ente - dt-duckietown-viewer`

Both require a reviewed full application `SOURCE_SHA`, an unused `VERSION`
(`x.y.z`), and maintainer approval before signing. The approved full Shell tools
SHA is part of the generated job configuration, **not** a build parameter.
The [release helper](assets/image_release.py) builds both native architectures,
extracts the stopped image without running its code, seals the project
inventories offline, verifies the final native trust/inventory and
missing-handoff rejection, and publishes immutable Docker Hub image identities.
The Engine additionally checks that constructing its compiled core cannot skip
the authorized bootstrap.

Only after both images pass and publish does the job sign and archive
`release/engines.json` or `release/backends.json`, plus `release/release.json`
with source/tools provenance. The catalog remains compatible with the existing
DTS publishers; these jobs do **not** change DCSS latest pointers.
An existing versioned registry tag is never overwritten. If a release partially
publishes before failing, investigate it and choose a fresh version for retry.

### Provisioning

Before enabling these jobs:

1. Install Jenkins Pipeline (including Input Step), Git/Git LFS and Credentials
   Binding versions compatible with the deployed Jenkins. These are required
   in addition to this image's bundled Slack plugin.
2. Disable controller executors. Ordinary repository jobs must run on isolated
   CI agents without the controller's Jenkins home, signing credentials or
   access to the signing agent. Adding credentials to a controller that also
   executes arbitrary repository shell commands does not isolate those secrets.
3. Provision dedicated **exclusive-mode**, single-executor agents labelled
   `docker-release` and `artifact-signing`. Do not let unlabelled ordinary jobs
   run there. Install the reviewed helper at
   `/usr/local/bin/dt-ci-image-release` and this image's Python dependencies on
   both agents; rebuilding only the controller does not update external agents.
   The signing agent must have **no Docker socket/daemon access**, no application
   execution, and no untrusted jobs. It needs Git access to the approved Shell
   tools, not the application checkout.
4. The Docker agent uses the existing native CI endpoints: amd64
   `172.27.0.101:2376`; ARM64 candidates `172.27.0.126:2376`,
   `172.27.0.43:2376`, `172.27.0.250:2376`. Use trusted release daemons and prevent
   concurrent untrusted workloads from mutating their images. The helper
   checks the daemon's native architecture and never uses emulation. Changes
   to those endpoints require a reviewed helper update.
5. Create the Jenkins credentials below. Private artifact keys are **Secret
   file** credentials containing an unencrypted Ed25519 PEM, not environment
   text injected into every build:

   | Credential ID | Type | Scope of use |
   | --- | --- | --- |
   | `GITHUB_SSH_KEY` | SSH private key | Approved application/tools checkout |
   | `DTM_ENGINE_RELEASE_SIGNING_KEY` | Secret file | Engine inventory/catalog signing on `artifact-signing` only |
   | `DTV_RELEASE_SIGNING_KEY` | Secret file | Viewer inventory/catalog signing on `artifact-signing` only |
   | `PRODUCTION_DOCKER_PASSWORD` | Secret text | Publishing verified images; existing production Docker username `afdaniele` |

   Never provision a Hub permission private key here. Keep keys out of ordinary
   autobuild bindings, Docker arguments, contexts, images, logs and archives.
   File credentials are bound only around the two offline signing commands;
   no application image is built or executed in those scopes.
6. Mount a read-only public JSON file at
   `/etc/duckietown/image-release-trust.json` on both release agent types.
   Its keys are exactly the nine public variables below; values are strings,
   including the JSON-encoded two-issuer maps. Use the same distinct public
   trust as native DTS and the published guards:

   ```sh
   python3 - <<'PY'
   import json, os
   from pathlib import Path
   names = (
       "DTS_RELEASE_PUBLIC_KEY", "DTS_COMMANDS_PUBLIC_KEY", "DTS_DEVELOPER_PUBLIC_KEYS",
       "DTM_RELEASE_PUBLIC_KEY", "DTM_RENDERER_PUBLIC_KEYS",
       "DTV_RELEASE_PUBLIC_KEY", "DTV_AUTH_PUBLIC_KEYS",
       "DTM_ENGINE_RELEASE_PUBLIC_KEY", "DTM_ENGINE_PUBLIC_KEYS",
   )
   Path("image-release-trust.json").write_text(
       json.dumps({name: os.environ[name] for name in names}, indent=2) + "\n"
   )
   PY
   ```

   Generate this file outside source repositories. Mount only this public
   file, not the operator's private-key directory.
7. Restrict job Build/Configure, Pipeline Replay, credential administration and
   trusted infrastructure/tool changes to release maintainers. Configure the
   `duckietown-release-managers` submitter group in the Jenkins security realm.
   Build permission alone must not allow an unapproved user to reach signing;
   changing the pipeline or replaying it can bypass its approval step.
8. Publish the native DTS and guard versions first, then follow
   [the job generation instructions](https://github.com/duckietown/.jenkins-jobs#protected-ente-image-releases)
   with the reviewed full Shell tools SHA. Review/push the generated changes
   and reload Jenkins jobs from disk.

These are infrastructure prerequisites, not protection supplied merely by a
Jenkins label. Native daemons, agents, the controller and approved tool commits
remain trusted release infrastructure.

### Running a release

1. Open the relevant protected job's **Build with Parameters** page and supply
   the exact reviewed `SOURCE_SHA` and unused `VERSION`.
2. Record its numeric build number. At **Maintainer approval**, verify the
   application SHA, version and pinned Shell SHA, then approve as a release
   maintainer.
3. Require **SUCCESS** through the final catalog stage for both native
   architectures. Download that exact build's `release/backends.json` or
   `release/engines.json` and its provenance file; do not select a mutable
   `lastSuccessfulBuild` from a concurrent/different release.
4. Publish with the existing authorized DTS command:
   `dts desktop viewer devel release` for the assembled Viewer desktop/backend
   artifacts, or `dts matrix engine devel release --file /path/to/engines.json`.
   See the [coordinated release runbook](https://github.com/duckietown/duckietown-shell/blob/main/devel.md)
   for the shared trust and publisher requirements.

These catalogs use the **production Ente** artifact namespace, including when
testing with `ente-staging`; staging is not an isolated artifact channel.
Ordinary Daffy jobs and artifacts remain unchanged.

### Local checks

From this repository, with the existing development Python environment:

```sh
DTS_RELEASE_TOOLS_CHECKOUT=../duckietown-shell \
    python3 -m unittest discover -s tests -p test_image_release.py
```

This tests orchestration, denial/error paths, owned-container timeout cleanup
and real offline Engine/Viewer inventory/catalog signatures with ephemeral
keys. Docker calls use fixtures; this is not a live Jenkins/native Docker
release test. Full builds and agent/credential isolation remain deployment
gates.
