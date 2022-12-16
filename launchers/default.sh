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
DOCKER_GROUP=docker

# impersonate
if [ "${IMPERSONATE:-}" != "" ]; then
    echo "Impersonating user with UID: ${IMPERSONATE}"
    usermod -u ${IMPERSONATE} ${DT_USER_NAME}
    groupmod -g ${IMPERSONATE} ${DT_USER_NAME}
fi

# make sure that a docker socket is present
if [ ! -S ${DOCKER_SOCKET} ]; then
    echo "FATAL: Docker socket NOT found!"
    echo "Make sure that you mounted the Docker socket to '${DOCKER_SOCKET}'."
    echo "Exiting..."
    exit 1
fi

# make sure that the JENKINS_HOME is mounted
mountpoint -q ${JENKINS_HOME}
if [ $? -ne 0 ]; then
    if [ "${ISOLATED}" != "1" ]; then
        echo "FATAL: User-data NOT mounted!"
        echo "Make sure that you mounted the path '${JENKINS_HOME}'."
        echo "Exiting..."
        exit 2
    else
        echo "WARNING: User-data NOT mounted! Changes will be lost when the container is removed."
        sudo -u ${DT_USER_NAME} /bin/bash -c "mkdir -p ${JENKINS_HOME}"
    fi
fi

# get docker GID
DOCKER_GID=$(stat -c '%g' ${DOCKER_SOCKET})

# make sure that the docker group does not exist
if [ $(getent group ${DOCKER_GROUP}) ]; then
    echo "Group '${DOCKER_GROUP}' found. No need to create it."
else
    # try to create a new group with GID=DOCKER_GID
    echo "Creating group '${DOCKER_GROUP}' with GID ${DOCKER_GID}..."
    groupadd --system --gid ${DOCKER_GID} ${DOCKER_GROUP}
    if [ $? -ne 0 ]; then
        exit
    fi
    echo "Adding user '${DT_USER_NAME}' to group '${DOCKER_GROUP}'..."
    usermod -a -G ${DOCKER_GROUP} ${DT_USER_NAME}
    echo "Done!"
fi

# run jenkins
dt-exec sudo -H -E -u ${DT_USER_NAME} /bin/bash -c "/usr/local/bin/jenkins.sh $*"

# ----------------------------------------------------------------------------
# YOUR CODE ABOVE THIS LINE

# wait for app to end
dt-launchfile-join
