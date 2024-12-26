#!/bin/bash

if [ -z "$1" ]; then
    echo "Error: No target specified."
    echo "Usage: $0 <target>"
    echo "Example: $0 mdb"
    echo "         $0 dbc"
    exit 1
fi

TARGET=$1
COMMIT_ID=$(git rev-parse --short HEAD)

IMAGE_NAME="yocto-librescoot:${COMMIT_ID}"

mkdir -p yocto

if ! docker images | grep -q "${COMMIT_ID}"; then
    echo "Building Docker image ${IMAGE_NAME}..."
    docker build \
        --build-arg UID=$(id -u) \
        --build-arg GID=$(id -g) \
        -t "${IMAGE_NAME}" \
        ./docker
else
    echo "Using existing Docker image ${IMAGE_NAME}."
fi

echo "Building target: ${TARGET}"

docker run -it --rm \
    -v "$(pwd)/yocto:/yocto" \
    --name yocto-build \
    -e TARGET="${TARGET}" \
    "${IMAGE_NAME}"

