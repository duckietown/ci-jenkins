# parameters
ARG REPO_NAME="ci-jenkins"
ARG DESCRIPTION="Jenkins application image for the Duckietown CI Infrastructure"
ARG MAINTAINER="Andrea F. Daniele (afdaniele@ttic.edu)"
# pick an icon from: https://fontawesome.com/v4.7.0/icons/
ARG ICON="cube"

ARG USER=duckie
ARG GROUP=duckie
ARG UID=1000
ARG GID=1000
ARG HTTP_PORT=8080
ARG AGENT_PORT=50000
ARG JENKINS_HOME=/home/duckie/user-data
ARG REF=/usr/share/jenkins/ref

# Jenkins version (and jenkins.war SHA-256 checksum, download will be validated using it)
ARG JENKINS_VERSION=2.346.3
ARG JENKINS_SHA=141e8c5890a31a5cf37a970ce3e15273c1c74d8759e4a5873bb5511c50b47d89

# ==================================================>
# ==> Do not change the code below this line
ARG ARCH
ARG DISTRO=daffy
ARG DOCKER_REGISTRY=docker.io
ARG BASE_IMAGE=dt-commons
ARG BASE_TAG=${DISTRO}-${ARCH}
ARG LAUNCHER=default

# define base image
FROM ${DOCKER_REGISTRY}/duckietown/${BASE_IMAGE}:${BASE_TAG} as BASE

# recall all arguments
ARG DISTRO
ARG REPO_NAME
ARG DESCRIPTION
ARG MAINTAINER
ARG ICON
ARG BASE_TAG
ARG BASE_IMAGE
ARG LAUNCHER
# - buildkit
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT

# check build arguments
RUN dt-build-env-check "${REPO_NAME}" "${MAINTAINER}" "${DESCRIPTION}"

# define/create repository path
ARG REPO_PATH="${SOURCE_DIR}/${REPO_NAME}"
ARG LAUNCH_PATH="${LAUNCH_DIR}/${REPO_NAME}"
RUN mkdir -p "${REPO_PATH}" "${LAUNCH_PATH}"
WORKDIR "${REPO_PATH}"

# keep some arguments as environment variables
ENV DT_MODULE_TYPE="${REPO_NAME}" \
    DT_MODULE_DESCRIPTION="${DESCRIPTION}" \
    DT_MODULE_ICON="${ICON}" \
    DT_MAINTAINER="${MAINTAINER}" \
    DT_REPO_PATH="${REPO_PATH}" \
    DT_LAUNCH_PATH="${LAUNCH_PATH}" \
    DT_LAUNCHER="${LAUNCHER}"

# install apt dependencies
COPY ./dependencies-apt.txt "${REPO_PATH}/"
RUN dt-apt-install ${REPO_PATH}/dependencies-apt.txt

# install python3 dependencies
ARG PIP_INDEX_URL="https://pypi.org/simple"
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
COPY ./dependencies-py3.* "${REPO_PATH}/"
RUN python3 -m pip install -r ${REPO_PATH}/dependencies-py3.txt

# copy the source code
COPY ./packages "${REPO_PATH}/packages"

# install launcher scripts
COPY ./launchers/. "${LAUNCH_PATH}/"
RUN dt-install-launchers "${LAUNCH_PATH}"

# define default command
CMD ["bash", "-c", "dt-launcher-${DT_LAUNCHER}"]

# store module metadata
LABEL org.duckietown.label.module.type="${REPO_NAME}" \
    org.duckietown.label.module.description="${DESCRIPTION}" \
    org.duckietown.label.module.icon="${ICON}" \
    org.duckietown.label.platform.os="${TARGETOS}" \
    org.duckietown.label.platform.architecture="${TARGETARCH}" \
    org.duckietown.label.platform.variant="${TARGETVARIANT}" \
    org.duckietown.label.code.location="${REPO_PATH}" \
    org.duckietown.label.code.version.distro="${DISTRO}" \
    org.duckietown.label.base.image="${BASE_IMAGE}" \
    org.duckietown.label.base.tag="${BASE_TAG}" \
    org.duckietown.label.maintainer="${MAINTAINER}"
# <== Do not change the code above this line
# <==================================================

ARG USER
ARG GROUP
ARG UID
ARG GID
ARG HTTP_PORT
ARG AGENT_PORT
ARG JENKINS_HOME
ARG JENKINS_VERSION
ARG JENKINS_SHA
ARG REF
ARG ARCH

ARG DOCKER_DOWNLOAD_URL="https://download.docker.com/linux/static/stable"
ARG DOCKER_VERSION="20.10.7"

ARG DOCKER_BUILDX_VERSION="0.9.1"
ARG DOCKER_BUILDX_DOWNLOAD_URL="https://github.com/docker/buildx/releases/download/v${DOCKER_BUILDX_VERSION}/buildx-v${DOCKER_BUILDX_VERSION}.linux"

ENV JENKINS_HOME ${JENKINS_HOME}
ENV JENKINS_SLAVE_AGENT_PORT ${AGENT_PORT}
ENV JENKINS_VERSION ${JENKINS_VERSION}
ENV REF ${REF}
ENV JENKINS_UC https://updates.jenkins.io
ENV JENKINS_UC_EXPERIMENTAL=https://updates.jenkins.io/experimental
ENV JENKINS_INCREMENTALS_REPO_MIRROR=https://repo.jenkins-ci.org/incrementals
ENV COPY_REFERENCE_FILE_LOG ${JENKINS_HOME}/copy_reference_file.log
ENV JENKINS_ENABLE_FUTURE_JAVA=true

# Configure PATH
ENV PATH=${JENKINS_HOME}/.local/bin/:${PATH}

# Can be used to customize where jenkins.war get downloaded from
ARG JENKINS_URL=https://repo.jenkins-ci.org/public/org/jenkins-ci/main/jenkins-war/${JENKINS_VERSION}/jenkins-war-${JENKINS_VERSION}.war

# Upgrade env (excluding ROS)
RUN rm /etc/apt/sources.list.d/ros.list \
  && apt update \
  && apt-get upgrade -y \
  && rm -rf /var/lib/apt/lists/*

# Give Jenkins user superpowers
RUN echo "${USER} ALL = (ALL) NOPASSWD: ALL" > /etc/sudoers.d/${USER}

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

# give the jenkins USER the power to create GROUPs
RUN echo 'jenkins ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers.d/jenkins_no_password

# could use ADD but this one does not check Last-Modified header neither does it allow to control checksum
# see https://github.com/docker/docker/issues/8331
RUN echo "Downloading Jenkins from '${JENKINS_URL}'..." \
    && curl -fsSL ${JENKINS_URL} -o /usr/share/jenkins/jenkins.war \
    && echo "${JENKINS_SHA}  /usr/share/jenkins/jenkins.war" | sha256sum -c -

# Change ownership of $REF
RUN chown -R ${USER} "$REF"

# for main web interface:
EXPOSE ${HTTP_PORT}

# will be used by attached slave agents:
EXPOSE ${AGENT_PORT}

# switch to `duckie` user
USER ${USER}

# jenkins scripts
COPY assets/jenkins-support /usr/local/bin/jenkins-support
COPY assets/jenkins.sh /usr/local/bin/jenkins.sh
COPY assets/plugins.sh /usr/local/bin/plugins.sh
COPY assets/install-plugins.sh /usr/local/bin/install-plugins.sh
