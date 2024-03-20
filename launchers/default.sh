#!/bin/bash

source /environment.sh

# initialize launch file
dt-launchfile-init

# YOUR CODE BELOW THIS LINE
# ----------------------------------------------------------------------------


# NOTE: Use the variable DT_PROJECT_PATH to know the absolute path to your code
# NOTE: Use `dt-exec COMMAND` to run the main process (blocking process)

# define constants
DOCKER_SOCKET=/var/run/docker.sock
DOCKER_GROUP=docker

# make sure that a docker socket is present
if [ ! -S ${DOCKER_SOCKET} ]; then
    echo "FATAL: Docker socket NOT found!"
    echo "Make sure that you mounted the Docker socket to '${DOCKER_SOCKET}'."
    echo "Exiting..."
    exit 1
fi

# make sure that the JENKINS_HOME is mounted (unless ISOLATED=1)
mountpoint -q ${JENKINS_HOME}
if [ $? -ne 0 ]; then
    if [ "${ISOLATED}" != "1" ]; then
        echo "FATAL: User-data NOT mounted!"
        echo "Make sure that you mounted the path '${JENKINS_HOME}'."
        echo "Exiting..."
        exit 2
    fi
fi

# run jenkins
dt-exec /usr/local/bin/jenkins.sh $*


# ----------------------------------------------------------------------------
# YOUR CODE ABOVE THIS LINE

dt-launchfile-join