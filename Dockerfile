# parameters
ARG PROJECT_NAME
ARG PROJECT_DESCRIPTION
ARG PROJECT_MAINTAINER
# pick an icon from: https://fontawesome.com/v4.7.0/icons/
ARG PROJECT_ICON="cube"
ARG PROJECT_FORMAT_VERSION

ARG HTTP_PORT=8080
ARG AGENT_PORT=50000

# Jenkins version (and jenkins.war SHA-256 checksum, download will be validated using it)
ARG JENKINS_VERSION=2.440.2
ARG JENKINS_SHA=8126628e9e2f8ee2f807d489ec0a6e37fc9f5d6ba84fa8f3718e7f3e2a27312e

# Can be used to customize where jenkins.war gets downloaded from
ARG JENKINS_URL=https://repo.jenkins-ci.org/public/org/jenkins-ci/main/jenkins-war/${JENKINS_VERSION}/jenkins-war-${JENKINS_VERSION}.war

# ==================================================>
# ==> Do not change the code below this line
ARG ARCH
ARG DISTRO
ARG DOCKER_REGISTRY
ARG BASE_REPOSITORY
ARG BASE_ORGANIZATION=duckietown
ARG BASE_TAG=${DISTRO}-${ARCH}
ARG LAUNCHER=default

# define base image
FROM ${DOCKER_REGISTRY}/${BASE_ORGANIZATION}/${BASE_REPOSITORY}:${BASE_TAG} as base

# recall all arguments
ARG ARCH
ARG DISTRO
ARG DOCKER_REGISTRY
ARG PROJECT_NAME
ARG PROJECT_DESCRIPTION
ARG PROJECT_MAINTAINER
ARG PROJECT_ICON
ARG PROJECT_FORMAT_VERSION
ARG BASE_TAG
ARG BASE_REPOSITORY
ARG BASE_ORGANIZATION
ARG LAUNCHER
# - buildkit
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT

# check build arguments
RUN dt-args-check \
    "PROJECT_NAME" "${PROJECT_NAME}" \
    "PROJECT_DESCRIPTION" "${PROJECT_DESCRIPTION}" \
    "PROJECT_MAINTAINER" "${PROJECT_MAINTAINER}" \
    "PROJECT_ICON" "${PROJECT_ICON}" \
    "PROJECT_FORMAT_VERSION" "${PROJECT_FORMAT_VERSION}" \
    "ARCH" "${ARCH}" \
    "DISTRO" "${DISTRO}" \
    "DOCKER_REGISTRY" "${DOCKER_REGISTRY}" \
    "BASE_REPOSITORY" "${BASE_REPOSITORY}" \
    && dt-check-project-format "${PROJECT_FORMAT_VERSION}"

# define/create repository path
ARG PROJECT_PATH="${SOURCE_DIR}/${PROJECT_NAME}"
ARG PROJECT_LAUNCHERS_PATH="${LAUNCHERS_DIR}/${PROJECT_NAME}"
RUN mkdir -p "${PROJECT_PATH}" "${PROJECT_LAUNCHERS_PATH}"
WORKDIR "${PROJECT_PATH}"

# keep some arguments as environment variables
ENV DT_PROJECT_NAME="${PROJECT_NAME}" \
    DT_PROJECT_DESCRIPTION="${PROJECT_DESCRIPTION}" \
    DT_PROJECT_MAINTAINER="${PROJECT_MAINTAINER}" \
    DT_PROJECT_ICON="${PROJECT_ICON}" \
    DT_PROJECT_PATH="${PROJECT_PATH}" \
    DT_PROJECT_LAUNCHERS_PATH="${PROJECT_LAUNCHERS_PATH}" \
    DT_LAUNCHER="${LAUNCHER}"

# install apt dependencies
COPY ./dependencies-apt.txt "${PROJECT_PATH}/"
RUN dt-apt-install ${PROJECT_PATH}/dependencies-apt.txt

# install python3 dependencies
ARG PIP_INDEX_URL="https://pypi.org/simple"
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
COPY ./dependencies-py3.* "${PROJECT_PATH}/"
RUN dt-pip3-install "${PROJECT_PATH}/dependencies-py3.*"

# copy the source code
COPY ./packages "${PROJECT_PATH}/packages"

# install launcher scripts
COPY ./launchers/. "${PROJECT_LAUNCHERS_PATH}/"
RUN dt-install-launchers "${PROJECT_LAUNCHERS_PATH}"

# install scripts
COPY ./assets/entrypoint.d "${PROJECT_PATH}/assets/entrypoint.d"
COPY ./assets/environment.d "${PROJECT_PATH}/assets/environment.d"

# define default command
CMD ["bash", "-c", "dt-launcher-${DT_LAUNCHER}"]

# store module metadata
LABEL \
    # module info
    org.duckietown.label.project.name="${PROJECT_NAME}" \
    org.duckietown.label.project.description="${PROJECT_DESCRIPTION}" \
    org.duckietown.label.project.maintainer="${PROJECT_MAINTAINER}" \
    org.duckietown.label.project.icon="${PROJECT_ICON}" \
    org.duckietown.label.project.path="${PROJECT_PATH}" \
    org.duckietown.label.project.launchers.path="${PROJECT_LAUNCHERS_PATH}" \
    # format
    org.duckietown.label.format.version="${PROJECT_FORMAT_VERSION}" \
    # platform info
    org.duckietown.label.platform.os="${TARGETOS}" \
    org.duckietown.label.platform.architecture="${TARGETARCH}" \
    org.duckietown.label.platform.variant="${TARGETVARIANT}" \
    # code info
    org.duckietown.label.code.distro="${DISTRO}" \
    org.duckietown.label.code.launcher="${LAUNCHER}" \
    org.duckietown.label.code.python.registry="${PIP_INDEX_URL}" \
    # base info
    org.duckietown.label.base.organization="${BASE_ORGANIZATION}" \
    org.duckietown.label.base.repository="${BASE_REPOSITORY}" \
    org.duckietown.label.base.tag="${BASE_TAG}"
# <== Do not change the code above this line
# <==================================================

ARG HTTP_PORT
ARG AGENT_PORT
ARG JENKINS_VERSION
ARG JENKINS_SHA
ARG JENKINS_URL
ARG ARCH

ARG DOCKER_DOWNLOAD_URL="https://download.docker.com/linux/static/stable"
ARG DOCKER_VERSION="20.10.7"

ARG DOCKER_BUILDX_VERSION="0.9.1"
ARG DOCKER_BUILDX_DOWNLOAD_URL="https://github.com/docker/buildx/releases/download/v${DOCKER_BUILDX_VERSION}/buildx-v${DOCKER_BUILDX_VERSION}.linux"

# configure environment
ENV JENKINS_HOME=${DT_USER_HOME}/user-data
ENV JENKINS_SLAVE_AGENT_PORT=${AGENT_PORT} \
    JENKINS_VERSION=${JENKINS_VERSION} \
    REF=/usr/share/jenkins/ref \
    JENKINS_UC=https://updates.jenkins.io \
    JENKINS_UC_EXPERIMENTAL=https://updates.jenkins.io/experimental \
    JENKINS_INCREMENTALS_REPO_MIRROR=https://repo.jenkins-ci.org/incrementals \
    COPY_REFERENCE_FILE_LOG=${JENKINS_HOME}/copy_reference_file.log \
    JENKINS_ENABLE_FUTURE_JAVA=true \
    PATH=${JENKINS_HOME}/.local/bin/:${PATH}

# Give Jenkins user superpowers
RUN echo "${DT_USER_NAME} ALL = (ALL) NOPASSWD: ALL" > /etc/sudoers.d/${DT_USER_NAME}

# $REF (defaults to `/usr/share/jenkins/ref/`) contains all reference configuration we want
# to set on a fresh new installation. Use it to bundle additional plugins
# or config file with your custom jenkins Docker image.
RUN mkdir -p ${REF}/init.groovy.d

# install docker binaries
RUN /bin/bash -c '\
  # install docker CLI
  set -ex; \
  # - pick correct architecture
  declare -A _arch; \
  _arch=(["arm32v7"]="armhf" ["arm64v8"]="aarch64" ["amd64"]="x86_64") \
  && docker_arch="${_arch[$ARCH]}" \
  && cd /tmp \
  # - download binaries
  && wget -nv \
    "${DOCKER_DOWNLOAD_URL}/${docker_arch}/docker-${DOCKER_VERSION}.tgz" \
    -O ./docker-bin.tgz \
  # - extract binaries
  && tar -zxvf ./docker-bin.tgz \
  # - copy binaries to system dir
  && cp ./docker/* /usr/local/bin \
  # - clean up temp files
  && rm -rf \
    docker \
    docker-bin.tgz'

# install docker buildx
RUN /bin/bash -c '\
  # install docker buildx
  set -ex; \
  # - prepare destination directory
  mkdir -p /usr/lib/docker/cli-plugins; \
  # - pick correct architecture
  declare -A _arch; \
  _arch=(["arm32v7"]="arm-v7" ["arm64v8"]="arm64" ["amd64"]="amd64") \
  && docker_build_arch="${_arch[$ARCH]}" \
  && cd /tmp \
  # - download docker-buildx
  && wget -nv \
    "${DOCKER_BUILDX_DOWNLOAD_URL}-${docker_build_arch}" \
    -O /usr/lib/docker/cli-plugins/docker-buildx \
  # - make docker-buildx executable
  && chmod +x /usr/lib/docker/cli-plugins/docker-buildx'

# could use ADD but this one does not check Last-Modified header neither does it allow to control checksum
# see https://github.com/docker/docker/issues/8331
RUN echo "Downloading Jenkins from '${JENKINS_URL}'..." \
    && curl -fsSL ${JENKINS_URL} -o /usr/share/jenkins/jenkins.war \
    && echo "${JENKINS_SHA}  /usr/share/jenkins/jenkins.war" | sha256sum -c -

# Change ownership of $REF
RUN chown -R ${DT_USER_NAME} "$REF"

# for main web interface
EXPOSE ${HTTP_PORT}

# will be used by attached slave agents
EXPOSE ${AGENT_PORT}

# switch to `duckie` user
USER ${DT_USER_NAME}

# jenkins scripts
COPY assets/jenkins-support /usr/local/bin/jenkins-support
COPY assets/jenkins.sh /usr/local/bin/jenkins.sh
COPY assets/plugins.sh /usr/local/bin/plugins.sh
COPY assets/install-plugins.sh /usr/local/bin/install-plugins.sh

# switch back to 'root'
USER root
