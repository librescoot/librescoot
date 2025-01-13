#!/bin/bash
set -e

cd /yocto

# Configure Git globally
echo "Configuring Git..."
git config --global user.email "yocto.builder@example.com"
git config --global user.name "Yocto Builder"

# Initialize repo if not already done
if [ ! -d .repo ]; then
    echo "Initializing repo..."
    git config --global color.ui false
    repo init -u https://github.com/nxp-imx/imx-manifest.git -b imx-linux-scarthgap -m imx-6.6.23-2.0.0.xml
    repo sync
fi

# Clone required layers if not present
clone_layer() {
    local name=$1
    local branch=$2
    local repo_url=$3
    local path=$4

    if [ ! -d "$path" ]; then
        echo "Cloning $name layer..."
        git clone -b "$branch" "$repo_url" "$path"
    else
        cd "$path"
        git checkout "$branch"
        git pull
        cd /yocto
    fi
}

clone_layer "meta-mender" "scarthgap" "https://github.com/mendersoftware/meta-mender" "sources/meta-mender"
clone_layer "meta-flutter" "scarthgap" "https://github.com/meta-flutter/meta-flutter.git" "sources/meta-flutter"
clone_layer "meta-librescoot" "scarthgap" "https://github.com/librescoot/meta-librescoot" "sources/meta-librescoot"

echo "Setting up build environment..."
DISTRO=librescoot-mdb source ./imx-setup-release.sh -b build
BSPDIR="/yocto"

# Update local.conf based on the TARGET environment variable
TARGET="${TARGET:-mdb}"
# Overwrite bblayers.conf
echo "Overwriting bblayers.conf..."

if [ "$TARGET" == "dbc" ]; then
    MACHINE="librescoot-dbc"
    DISTRO="librescoot-dbc"
    cat > /yocto/build/conf/bblayers.conf << 'EOL'
LCONF_VERSION = "7"

BBPATH = "${TOPDIR}"
BSPDIR := "${@os.path.abspath(os.path.dirname(d.getVar('FILE', True)) + '/../..')}"

BBFILES ?= ""
BBLAYERS = " \
  ${BSPDIR}/sources/poky/meta \
  ${BSPDIR}/sources/poky/meta-poky \
  ${BSPDIR}/sources/meta-openembedded/meta-oe \
  ${BSPDIR}/sources/meta-openembedded/meta-multimedia \
  ${BSPDIR}/sources/meta-openembedded/meta-python \
  ${BSPDIR}/sources/meta-freescale \
  ${BSPDIR}/sources/meta-freescale-3rdparty \
  ${BSPDIR}/sources/meta-freescale-distro \
  ${BSPDIR}/sources/meta-mender/meta-mender-core \
  ${BSPDIR}/sources/meta-mender/meta-mender-demo \
  ${BSPDIR}/sources/meta-flutter \
  ${BSPDIR}/sources/meta-librescoot \
  /yocto/build/workspace \
  "
# i.MX Yocto Project Release layers
BBLAYERS += "${BSPDIR}/sources/meta-imx/meta-imx-bsp"
BBLAYERS += "${BSPDIR}/sources/meta-imx/meta-imx-sdk"
BBLAYERS += "${BSPDIR}/sources/meta-imx/meta-imx-ml"
BBLAYERS += "${BSPDIR}/sources/meta-imx/meta-imx-v2x"
BBLAYERS += "${BSPDIR}/sources/meta-nxp-demo-experience"

BBLAYERS += "${BSPDIR}/sources/meta-arm/meta-arm"
BBLAYERS += "${BSPDIR}/sources/meta-arm/meta-arm-toolchain"
BBLAYERS += "${BSPDIR}/sources/meta-browser/meta-chromium"
BBLAYERS += "${BSPDIR}/sources/meta-clang"
BBLAYERS += "${BSPDIR}/sources/meta-openembedded/meta-gnome"
BBLAYERS += "${BSPDIR}/sources/meta-openembedded/meta-networking"
BBLAYERS += "${BSPDIR}/sources/meta-openembedded/meta-filesystems"
BBLAYERS += "${BSPDIR}/sources/meta-qt6"
BBLAYERS += "${BSPDIR}/sources/meta-security/meta-parsec"
BBLAYERS += "${BSPDIR}/sources/meta-security/meta-tpm"
BBLAYERS += "${BSPDIR}/sources/meta-virtualization"
EOL
    cat > /yocto/build/conf/local.conf << EOL
MACHINE ??= 'librescoot-dbc'
DISTRO ?= 'librescoot-dbc'
MENDER_ARTIFACT_NAME = "release-1"
INHERIT += "mender-full"
ARTIFACTIMG_FSTYPE = "ext4"
INIT_MANAGER = "systemd"
LIBRESCOOT_VERSION = "0.0.1"

PREFERRED_PROVIDER_u-boot = "u-boot-imx"
PREFERRED_PROVIDER_virtual/bootloader = "u-boot-imx"
PREFERRED_VERSION_u-boot-imx = "2017.03"
PREFERRED_VERSION_linux-imx = "6.6.3+git"

# EXTRA_IMAGE_FEATURES ?= "debug-tweaks"
USER_CLASSES ?= "buildstats"
PATCHRESOLVE = "noop"
PACKAGECONFIG:append:pn-qemu-system-native = " sdl"
CONF_VERSION = "2"
DL_DIR ?= "${BSPDIR}/downloads/"
ACCEPT_FSL_EULA = "1"
HOSTTOOLS += "x86_64-linux-gnu-gcc git-lfs python"
# EXTRA_IMAGE_FEATURES = "debug-tweaks"
EOL
else
    MACHINE="librescoot-mdb"
    DISTRO="librescoot-mdb"
    cat > /yocto/build/conf/bblayers.conf << 'EOL'
LCONF_VERSION = "7"

BBPATH = "${TOPDIR}"
BSPDIR := "${@os.path.abspath(os.path.dirname(d.getVar('FILE', True)) + '/../..')}"

BBFILES ?= ""
BBLAYERS = " \
  ${BSPDIR}/sources/poky/meta \
  ${BSPDIR}/sources/poky/meta-poky \
  ${BSPDIR}/sources/meta-openembedded/meta-oe \
  ${BSPDIR}/sources/meta-openembedded/meta-multimedia \
  ${BSPDIR}/sources/meta-openembedded/meta-python \
  ${BSPDIR}/sources/meta-freescale \
  ${BSPDIR}/sources/meta-freescale-3rdparty \
  ${BSPDIR}/sources/meta-freescale-distro \
  ${BSPDIR}/sources/meta-mender/meta-mender-core \
  ${BSPDIR}/sources/meta-mender/meta-mender-demo \
  ${BSPDIR}/sources/meta-librescoot \
  ${BSPDIR}/sources/meta-flutter \
"
EOL
    echo "Creating local.conf..."
    cat > /yocto/build/conf/local.conf << EOL
MACHINE ??= '${MACHINE}'
DISTRO ?= '${DISTRO}'
MENDER_ARTIFACT_NAME = "release-1"
INHERIT += "mender-full"
ARTIFACTIMG_FSTYPE = "ext4"
INIT_MANAGER = "systemd"
DISTRO_VERSION = "0.0.1"
OLDEST_KERNEL = "5.4.24"
PREFERRED_PROVIDER_u-boot = "u-boot-imx"
PREFERRED_PROVIDER_virtual/bootloader = "u-boot-imx"
PREFERRED_PROVIDER_virtual/kernel="linux-imx"
PREFERRED_VERSION_linux_imx = "5.4.24"
PREFERRED_VERSION_u-boot-imx = "2017.03"
EXTRA_IMAGE_FEATURES ?= "debug-tweaks"
USER_CLASSES ?= "buildstats"
PATCHRESOLVE = "noop"
PACKAGECONFIG:append:pn-qemu-system-native = " sdl"
CONF_VERSION = "2"
DL_DIR ?= "${BSPDIR}/downloads/"
ACCEPT_FSL_EULA = "1"
HOSTTOOLS += "x86_64-linux-gnu-gcc git-lfs python"
EXTRA_IMAGE_FEATURES = "debug-tweaks"
EOL
fi

echo "Starting build process..."

bitbake "librescoot-${TARGET}-image" --continue

