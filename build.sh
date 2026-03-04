#!/bin/bash

if [ -z "$1" ]; then
    echo "Error: No target specified."
    echo "Usage: $0 <target> [branch]"
    echo "Example: $0 mdb"
    echo "         $0 dbc"
    echo "         $0 rpi4"
    echo "         $0 mdb feature-branch"
    exit 1
fi

TARGET=$1
BRANCH=${2:-scarthgap}  # Default to scarthgap branch if not specified
COMMIT_ID=$(git rev-parse --short HEAD)

IMAGE_NAME="yocto-librescoot:${COMMIT_ID}"

mkdir -p yocto
sudo chown 999:999 yocto

git_dirty=false
image_exists=false

git diff-index --quiet HEAD -- || git_dirty=true
sudo docker images | grep -q "${COMMIT_ID}" && image_exists=true
echo "git_dirty: $git_dirty  image_exists: $image_exists"

if [ $git_dirty = "true" -o $image_exists = "false" ]; then
    echo "Building Docker image ${IMAGE_NAME}..."
    sudo docker build -t "${IMAGE_NAME}" -f ./docker/Dockerfile .
else
    echo "Using existing Docker image ${IMAGE_NAME}."
fi

echo "Building target: ${TARGET}"

sudo docker run -it --rm \
    -v "$(pwd)/yocto:/yocto" \
    --name "yocto-build" \
    -e TARGET="${TARGET}" \
    -e BRANCH="${BRANCH}" \
    -e META_LIBRESCOOT_BRANCH="${META_LIBRESCOOT_BRANCH}" \
    -e LIBRESCOOT_VERSION="${LIBRESCOOT_VERSION}" \
    -e PACKAGE="${PACKAGE}" \
    -e SCOOTUI_VERSION_UPDATE="${SCOOTUI_VERSION_UPDATE}" \
    -e SCOOTUI_SRCREV="${SCOOTUI_SRCREV}" \
    -e SCOOTUI_BRANCH="${SCOOTUI_BRANCH}" \
    -e SCOOTUI_BRANCH="${SCOOTUI_BRANCH}" \
    -e BUILD_CHANNEL="${BUILD_CHANNEL}" \
    -e LAYER_VERSION_meta_librescoot="${LAYER_VERSION_meta_librescoot}" \
    "${IMAGE_NAME}"
