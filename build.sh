#!/bin/bash

if [ -z "$1" ]; then
    echo "Error: No target specified."
    echo "Usage: $0 <target> [branch]"
    echo "Example: $0 mdb"
    echo "         $0 dbc"
    echo "         $0 mdb feature-branch"
    exit 1
fi

TARGET=$1
BRANCH=${2:-scarthgap}  # Default to scarthgap branch if not specified
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

echo "Building target: ${TARGET}"

sudo docker run -it --rm \
    -v "$(pwd)/yocto:/yocto" \
    --name yocto-build \
    -e TARGET="${TARGET}" \
    -e BRANCH="${BRANCH}" \
    "${IMAGE_NAME}"
