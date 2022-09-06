#!/bin/bash

source /environment.sh

# initialize launch file
dt-launchfile-init

# YOUR CODE BELOW THIS LINE
# ----------------------------------------------------------------------------


# NOTE: Use the variable DT_REPO_PATH to know the absolute path to your code
# NOTE: Use `dt-exec COMMAND` to run the main process (blocking process)

# define constants
DOCKER_SOCKET=/var/run/docker.sock
JENKINS_HOME=/home/duckie
DOCKER_GROUP=docker

# make sure that a docker socket is present
if [ ! -S ${DOCKER_SOCKET} ]; then
    echo "Docker socket NOT found!"
    echo "Make sure that you mounted the Docker socket to '${DOCKER_SOCKET}'."
    echo "Exiting..."
    exit 1
fi

# make sure that the JENKINS_HOME is mounted
mountpoint -q ${JENKINS_HOME}
if [ $? -ne 0 ]; then
  echo "ERROR: The path '${JENKINS_HOME}' is not mounted. Refusing to run without external bind."
  exit 2
fi

# get docker GID
DOCKER_GID=$(stat -c '%g' ${DOCKER_SOCKET})

# make sure that the docker group does not exist
if [ $(getent group ${DOCKER_GROUP}) ]; then
  echo "Group '${DOCKER_GROUP}' found. No need to create it."
else
  # try to create a new group with GID=DOCKER_GID
  echo "Creating group '${DOCKER_GROUP}'..."
  sudo groupadd --system --gid ${DOCKER_GID} ${DOCKER_GROUP}
  if [ $? -ne 0 ]; then
    exit
  fi
  sudo usermod -a -G ${DOCKER_GROUP} `whoami`
  echo "Done!"
fi

# run jenkins
dt-exec sudo -u duckie /bin/bash -c "/usr/local/bin/jenkins.sh $*"

# ----------------------------------------------------------------------------
# YOUR CODE ABOVE THIS LINE

# wait for app to end
dt-launchfile-join
