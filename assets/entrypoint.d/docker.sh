DOCKER_SOCKET=/var/run/docker.sock
DOCKER_GROUP=docker

# get docker GID
DOCKER_GID=$(stat -c '%g' ${DOCKER_SOCKET})

# make sure that the docker group does not exist before attempting to create one
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
