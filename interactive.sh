#!/bin/bash

COMMIT_ID=$(git rev-parse --short HEAD)
IMAGE_NAME="yocto-librescoot:${COMMIT_ID}"

mkdir -p yocto
sudo chown 999:999 yocto

if ! sudo docker images | grep -q "${COMMIT_ID}"; then
    echo "Building Docker image ${IMAGE_NAME}..."
    sudo docker build -t "${IMAGE_NAME}" ./docker
else
    echo "Using existing Docker image ${IMAGE_NAME}."
fi

sudo docker run -it --rm \
    -v "$(pwd)/yocto:/yocto" \
    --name yocto-build-interactive \
    --entrypoint /bin/bash \
    "${IMAGE_NAME}"

