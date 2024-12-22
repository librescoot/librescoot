#!/bin/bash

mkdir -p yocto

sudo chown -R 999:999 yocto

if ! sudo docker images | grep -q yocto-librescoot; then
    sudo docker build -t yocto-librescoot ./docker
fi

sudo docker run -it --rm \
    -v $(pwd)/yocto:/yocto \
    --name yocto-build \
    yocto-librescoot
