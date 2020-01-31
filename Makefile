ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
ARCH=arm64v8

release: build-all push-all
	echo 'Release: Done!'

build-all: build-jenkins build-proxy
	echo 'Build: Done!'

push-all: push-jenkins push-proxy
	echo 'Push: Done!'

build-jenkins:
	echo '========================================='
	echo 'Building: Jenkins-CI'
	docker build \
		-t duckietown/dt-jenkins-ci:${ARCH} \
		--file ${ROOT_DIR}/Dockerfile.jenkins \
		--build-arg ARCH=${ARCH} \
		${ROOT_DIR}

build-proxy:
	echo '========================================='
	echo 'Building: Jenkins-HTTPS-Proxy'
	docker build \
		-t duckietown/dt-jenkins-proxy:${ARCH} \
		--file ${ROOT_DIR}/Dockerfile.https.proxy \
		--build-arg ARCH=${ARCH} \
		${ROOT_DIR}

push-jenkins:
	echo '========================================='
	echo 'Pushing: Jenkins-CI'
	docker push \
		duckietown/dt-jenkins-ci:${ARCH}

push-proxy:
	echo '========================================='
	echo 'Pushing: Jenkins-HTTPS-Proxy'
	docker push \
		duckietown/dt-jenkins-proxy:${ARCH}
