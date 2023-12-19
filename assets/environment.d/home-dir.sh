# make sure that the JENKINS_HOME is mounted (unless ISOLATED=1)

set +e

if ! mountpoint -q ${JENKINS_HOME}; then
    # home is NOT mounted, this is only allowed when ISOLATED=1
    if [ "${ISOLATED:-}" = "1" ]; then
        echo "WARNING: User-data NOT mounted! Changes will be lost when the container is removed."
        mkdir -p ${JENKINS_HOME}
    fi
fi

set -e