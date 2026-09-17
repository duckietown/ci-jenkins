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
