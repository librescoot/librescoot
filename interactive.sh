#!/bin/bash

COMMIT_ID=$(git rev-parse --short HEAD)
IMAGE_NAME="yocto-librescoot:${COMMIT_ID}"

mkdir -p yocto

if ! docker images "${IMAGE_NAME}" | grep -q "${COMMIT_ID}"; then
    echo "Docker image ${IMAGE_NAME} not found, building..."
    docker build \
        --build-arg UID=$(id -u) \
        --build-arg GID=$(id -g) \
        -t "${IMAGE_NAME}" \
        ./docker
else
    echo "Using existing Docker image ${IMAGE_NAME}."
fi

docker run -it --rm \
    -v "$(pwd)/yocto:/yocto" \
    --name yocto-build \
    --entrypoint /bin/bash \
    "${IMAGE_NAME}"
