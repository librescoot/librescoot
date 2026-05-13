#!/bin/bash
set -e

cd /yocto

# Source environment file based on BUILD_CHANNEL
if [ "$BUILD_CHANNEL" = "nightly" ]; then
    ENV_FILE="/yocto/nightly.env"
    echo "Build channel is NIGHTLY. Using ${ENV_FILE}"
elif [ "$BUILD_CHANNEL" = "testing" ] || [ "$BUILD_CHANNEL" = "stable" ]; then
    ENV_FILE="/yocto/stable.env"
    echo "Build channel is ${BUILD_CHANNEL^^}. Using ${ENV_FILE}"
else
    # Default fallback with cascading check
    if [ -f "/yocto/versions.env" ]; then
        ENV_FILE="/yocto/versions.env"
        echo "Build channel not specified or unknown. Using ${ENV_FILE}"
    else
        ENV_FILE="/yocto/nightly.env"
        echo "Build channel not specified and versions.env not found. Falling back to ${ENV_FILE}"
    fi
fi

# Save any LAYER_VERSION overrides from the environment before sourcing
# the env file, which would clobber them
declare -A _saved_overrides
for var in $(compgen -v LAYER_VERSION_); do
    if [ -n "${!var}" ]; then
        _saved_overrides[$var]="${!var}"
    fi
done

if [ -f "$ENV_FILE" ]; then
    echo "Sourcing ${ENV_FILE}..."
    source "$ENV_FILE"
elif [ -f "/opt/yocto-env/$(basename $ENV_FILE)" ]; then
    # Fallback if mounted or copied elsewhere
    echo "Sourcing $(basename $ENV_FILE) from /opt/yocto-env..."
    source "/opt/yocto-env/$(basename $ENV_FILE)"
else
    echo "Warning: Environment file ${ENV_FILE} not found."
fi

# Restore env overrides that were set before sourcing
for var in "${!_saved_overrides[@]}"; do
    echo "Restoring override: ${var}=${_saved_overrides[$var]}"
    export "$var=${_saved_overrides[$var]}"
done
unset _saved_overrides

# Set default branch if not provided
BRANCH="${BRANCH:-scarthgap}"
META_LIBRESCOOT_BRANCH="${META_LIBRESCOOT_BRANCH:-scarthgap}"
echo "Using Yocto branch: ${BRANCH}"
echo "Using meta-librescoot branch: ${META_LIBRESCOOT_BRANCH}"

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

# Retry a command with exponential backoff
retry_with_backoff() {
    local max_attempts=5
    local delay=5
    local attempt=1
    while true; do
        if "$@"; then
            return 0
        fi
        if [ $attempt -ge $max_attempts ]; then
            echo "Failed after $max_attempts attempts: $*"
            return 1
        fi
        echo "Attempt $attempt failed, retrying in ${delay}s..."
        sleep $delay
        delay=$((delay * 2))
        attempt=$((attempt + 1))
    done
}

# Clone required layers if not present
clone_layer() {
    local name=$1
    local ref=$2  # Can be branch, tag, or commit
    local repo_url=$3
    local path=$4

    if [ ! -d "$path" ]; then
        echo "Cloning $name layer..."
        retry_with_backoff git clone "$repo_url" "$path"
        cd "$path"
    else
        cd "$path"
        # Only reset/clean if HEAD exists (repo has a valid checkout)
        if git rev-parse --verify HEAD >/dev/null 2>&1; then
            git clean -fdx
            git reset --hard HEAD
            if [ -f .git/MERGE_HEAD ]; then
                git merge --abort
            fi
        fi
        # Fetch all refs (branches, tags, etc.)
        retry_with_backoff git fetch origin --tags --force
    fi

    # Determine if ref is a branch, tag, or commit
    if git show-ref --verify --quiet "refs/remotes/origin/$ref"; then
        # It's a remote branch
        echo "Checking out branch $ref..."
        git checkout -f "$ref"
        git reset --hard "origin/$ref"
        git pull || true
    elif git show-ref --verify --quiet "refs/tags/$ref"; then
        # It's a tag
        echo "Checking out tag $ref..."
        git checkout -f "$ref"
    else
        # Assume it's a commit hash or short hash
        echo "Checking out commit $ref..."
        git checkout -f "$ref"
    fi

    cd - > /dev/null
}

git config --global --add safe.directory /yocto/sources/meta-librescoot

clone_layer "meta-mender" "${LAYER_VERSION_meta_mender:-scarthgap}" "https://github.com/mendersoftware/meta-mender" "sources/meta-mender"
clone_layer "meta-mender-community" "${LAYER_VERSION_meta_mender_community:-scarthgap}" "https://github.com/mendersoftware/meta-mender-community.git" "sources/meta-mender-community"
clone_layer "meta-flutter" "${LAYER_VERSION_meta_flutter:-scarthgap}" "https://github.com/meta-flutter/meta-flutter.git" "sources/meta-flutter"
clone_layer "meta-librescoot" "${LAYER_VERSION_meta_librescoot:-scarthgap}" "https://github.com/librescoot/meta-librescoot" "sources/meta-librescoot"
clone_layer "meta-openjdk-temurin" "${LAYER_VERSION_meta_openjdk_temurin:-scarthgap}" "https://github.com/lucimber/meta-openjdk-temurin" "sources/meta-openjdk-temurin"
clone_layer "meta-raspberrypi" "${LAYER_VERSION_meta_raspberrypi:-scarthgap}" "https://github.com/agherzan/meta-raspberrypi.git" "sources/meta-raspberrypi"
if [ "${TARGET}" = "rpi4" ]; then
    clone_layer "meta-lts-mixins" "${LAYER_VERSION_meta_lts_mixins:-scarthgap}" "git://git.yoctoproject.org/meta-lts-mixins" "sources/meta-lts-mixins"
fi

# Determine LIBRESCOOT_VERSION - use environment variable if set, otherwise from meta-librescoot repository
if [ -z "${LIBRESCOOT_VERSION}" ]; then
    cd "sources/meta-librescoot"
    META_LIBRESCOOT_VERSION=$(git describe --always --long --tags --dirty 2>/dev/null || echo "0.0.1-dev")
    cd -
    LIBRESCOOT_VERSION="${META_LIBRESCOOT_VERSION}"
    echo "Using Librescoot version from meta-librescoot: ${LIBRESCOOT_VERSION}"
else
    echo "Using Librescoot version from environment variable: ${LIBRESCOOT_VERSION}"
fi

echo "Setting up build environment..."
DISTRO=librescoot-mdb source ./imx-setup-release.sh -b build

# Update local.conf based on the TARGET environment variable
TARGET="${TARGET:-mdb}"
# Overwrite bblayers.conf
echo "Overwriting bblayers.conf..."

if [ "$TARGET" == "rpi4" ]; then
    # rpi4
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
  ${BSPDIR}/sources/meta-mender-community/meta-mender-raspberrypi \
  ${BSPDIR}/sources/meta-lts-mixins \
  ${BSPDIR}/sources/meta-flutter \
  ${BSPDIR}/sources/meta-librescoot \
  ${BSPDIR}/sources/meta-openjdk-temurin \
  ${BSPDIR}/sources/meta-raspberrypi \
  "

BBLAYERS += "${BSPDIR}/sources/meta-openembedded/meta-initramfs"

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
    echo "Overwriting local.conf..."
    cat > /yocto/build/conf/local.conf << EOL
MACHINE ??= 'librescoot-dbc-rpi4'
DISTRO ?= 'librescoot-dbc'
LIBRESCOOT_VERSION = "${LIBRESCOOT_VERSION:-0.0.1}"
MENDER_ARTIFACT_NAME = "release-${LIBRESCOOT_VERSION:-1}"
INHERIT += "mender-full"
INHERIT += "image-buildinfo"
ARTIFACTIMG_FSTYPE = "ext4"
INIT_MANAGER = "systemd"
PRSERV_HOST = "localhost:0"
ERROR_QA:remove = "version-going-backwards"
WARN_QA:append = " version-going-backwards"

# EXTRA_IMAGE_FEATURES ?= "debug-tweaks"
USER_CLASSES ?= "buildstats"
PACKAGE_CLASSES ?= "package_rpm"
PATCHRESOLVE = "noop"
PACKAGECONFIG:append:pn-qemu-system-native = " sdl"
CONF_VERSION = "2"
DL_DIR ?= "/yocto/downloads/"
ACCEPT_FSL_EULA = "1"
LICENSE_FLAGS_ACCEPTED += "synaptics-killswitch commercial"
HOSTTOOLS += "x86_64-linux-gnu-gcc git-lfs python"
# EXTRA_IMAGE_FEATURES = "debug-tweaks"
DEFAULT_TIMEZONE = "Europe/Berlin"

# Track package sizes and file lists across builds
INHERIT += "buildhistory"
BUILDHISTORY_COMMIT = "1"
BUILDHISTORY_FEATURES = "image package"
EOL
elif [ "$TARGET" == "dbc" ]; then
    # dbc
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
  ${BSPDIR}/sources/meta-flutter \
  ${BSPDIR}/sources/meta-librescoot \
  ${BSPDIR}/sources/meta-openjdk-temurin \
  "

BBLAYERS += "${BSPDIR}/sources/meta-openembedded/meta-initramfs"

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
    echo "Overwriting local.conf..."
    cat > /yocto/build/conf/local.conf << EOL
MACHINE ??= 'unu-dbc'
DISTRO ?= 'librescoot-dbc'
LIBRESCOOT_VERSION = "${LIBRESCOOT_VERSION:-0.0.1}"
MENDER_ARTIFACT_NAME = "release-${LIBRESCOOT_VERSION:-1}"
INHERIT += "mender-full"
INHERIT += "image-buildinfo" 
ARTIFACTIMG_FSTYPE = "ext4"
INIT_MANAGER = "systemd"
PRSERV_HOST = "localhost:0"
ERROR_QA:remove = "version-going-backwards"
WARN_QA:append = " version-going-backwards"

PREFERRED_PROVIDER_u-boot = "u-boot-imx"
PREFERRED_PROVIDER_virtual/bootloader = "u-boot-imx"
PREFERRED_VERSION_u-boot-imx = "2017.03"
PREFERRED_VERSION_linux-imx = "6.6.3+git"

# EXTRA_IMAGE_FEATURES ?= "debug-tweaks"
USER_CLASSES ?= "buildstats"
PACKAGE_CLASSES ?= "package_rpm"
PATCHRESOLVE = "noop"
PACKAGECONFIG:append:pn-qemu-system-native = " sdl"
CONF_VERSION = "2"
DL_DIR ?= "/yocto/downloads/"
LICENSE_FLAGS_ACCEPTED += "synaptics-killswitch commercial"
ACCEPT_FSL_EULA = "1"
HOSTTOOLS += "x86_64-linux-gnu-gcc git-lfs python"
# EXTRA_IMAGE_FEATURES = "debug-tweaks"
DEFAULT_TIMEZONE = "Europe/Berlin"

# Track package sizes and file lists across builds
INHERIT += "buildhistory"
BUILDHISTORY_COMMIT = "1"
BUILDHISTORY_FEATURES = "image package"
EOL
else
    # mdb
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
  ${BSPDIR}/sources/meta-openembedded/meta-networking \
  ${BSPDIR}/sources/meta-openembedded/meta-python \
  ${BSPDIR}/sources/meta-freescale \
  ${BSPDIR}/sources/meta-freescale-3rdparty \
  ${BSPDIR}/sources/meta-freescale-distro \
  ${BSPDIR}/sources/meta-mender/meta-mender-core \
  ${BSPDIR}/sources/meta-librescoot \
  ${BSPDIR}/sources/meta-flutter \
"
EOL
    echo "Overwriting local.conf..."
    cat > /yocto/build/conf/local.conf << EOL
MACHINE ??= 'unu-mdb'
DISTRO ?= 'librescoot-mdb'
LIBRESCOOT_VERSION = "${LIBRESCOOT_VERSION:-0.0.1}"
MENDER_ARTIFACT_NAME = "release-${LIBRESCOOT_VERSION:-1}"
INHERIT += "mender-full"
INHERIT += "image-buildinfo" 
ARTIFACTIMG_FSTYPE = "ext4"
INIT_MANAGER = "systemd"
PRSERV_HOST = "localhost:0"
OLDEST_KERNEL = "5.4.24"
PREFERRED_PROVIDER_u-boot = "u-boot-imx"
PREFERRED_PROVIDER_virtual/bootloader = "u-boot-imx"
PREFERRED_PROVIDER_virtual/kernel="linux-imx"
PREFERRED_VERSION_linux-imx = "5.4.24+git"
PREFERRED_VERSION_linux-libc-headers = "5.4.25"
PREFERRED_VERSION_u-boot-imx = "2017.03"
EXTRA_IMAGE_FEATURES ?= "debug-tweaks"
USER_CLASSES ?= "buildstats"
PACKAGE_CLASSES ?= "package_rpm"
PATCHRESOLVE = "noop"
PACKAGECONFIG:append:pn-qemu-system-native = " sdl"
CONF_VERSION = "2"
DL_DIR ?= "/yocto/downloads/"
ACCEPT_FSL_EULA = "1"
HOSTTOOLS += "x86_64-linux-gnu-gcc git-lfs python"
EXTRA_IMAGE_FEATURES = "debug-tweaks"
DEFAULT_TIMEZONE = "Europe/Berlin"
ERROR_QA:remove = "version-going-backwards"
WARN_QA:append = " version-going-backwards"

# Track package sizes and file lists across builds
INHERIT += "buildhistory"
BUILDHISTORY_COMMIT = "1"
BUILDHISTORY_FEATURES = "image package"
EOL
fi

# Apply SRCREV overrides from environment variables.
# This must run AFTER the TARGET-specific local.conf is written above,
# otherwise the overrides get clobbered.
echo "Applying version overrides..."
for var in $(compgen -v | grep '^SRCREV_'); do
    val="${!var}"
    if [ -n "$val" ]; then
        # Convert SRCREV_package_name to SRCREV_pn-package-name
        # Replace underscores with dashes in the package name part
        pkg_name="${var#SRCREV_}"
        pkg_name="${pkg_name//_/-}"
        echo "Overriding ${pkg_name} with ${val}"
        echo "SRCREV:pn-${pkg_name} = \"${val}\"" >> /yocto/build/conf/local.conf
    fi
done

# Apply DISTRO_CODENAME override if set
if [ -n "$DISTRO_CODENAME" ]; then
    echo "Overriding DISTRO_CODENAME with ${DISTRO_CODENAME}"
    echo "DISTRO_CODENAME = \"${DISTRO_CODENAME}\"" >> /yocto/build/conf/local.conf
fi

# Apply SCOOTUI_VERSION_UPDATE if set (for scootui builds)
if [ -n "$SCOOTUI_VERSION_UPDATE" ]; then
    echo "Overriding scootui version with ${SCOOTUI_VERSION_UPDATE}"
    echo "PV:pn-scootui = \"${SCOOTUI_VERSION_UPDATE}\"" >> /yocto/build/conf/local.conf
fi

echo "Starting build process..."

# Check if PACKAGE is set to build only specific packages
if [ -n "${PACKAGE}" ]; then
    if [ "${PACKAGE}" = "scootui" ]; then
        bitbake -c clean scootui
    fi
    if [ "${PACKAGE}" = "scootui-qt" ]; then
	bitbake -c clean scootui-qt
    fi
    echo "Building specific package: ${PACKAGE}"
    bitbake "${PACKAGE}" --continue
else
    # Determine the image name based on TARGET
    if [ "${TARGET}" = "rpi4" ]; then
        IMAGE_NAME="librescoot-dbc-image"
    else
        IMAGE_NAME="librescoot-${TARGET}-image"
    fi

    echo "Building full image: ${IMAGE_NAME}"

    # Clean scootui for both dbc and rpi4 targets
    if [ "${TARGET}" = "dbc" ] || [ "${TARGET}" = "rpi4" ]; then
        bitbake -c clean scootui-qt
    fi

    bitbake "${IMAGE_NAME}" --continue
fi
