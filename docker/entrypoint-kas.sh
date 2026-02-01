#!/bin/bash
# kas-based entrypoint for LibreScoot Yocto builds
#
# This is a simplified alternative to entrypoint.sh that uses kas
# (https://kas.readthedocs.io/) for build configuration instead of
# manual repo sync + bblayers.conf generation.
#
# Usage (from docker run):
#   TARGET=mdb  → builds MDB image
#   TARGET=dbc  → builds DBC image
#   TARGET=rpi4 → builds RPi4 dev image
#
# Prerequisites: kas must be installed in the Docker image
#   pip3 install kas

set -e

TARGET="${TARGET:-mdb}"

cd /yocto

# Source environment file for version overrides
if [ "$BUILD_CHANNEL" = "nightly" ]; then
    ENV_FILE="/yocto/nightly.env"
elif [ "$BUILD_CHANNEL" = "testing" ] || [ "$BUILD_CHANNEL" = "stable" ]; then
    ENV_FILE="/yocto/stable.env"
else
    ENV_FILE="/yocto/nightly.env"
fi

if [ -f "$ENV_FILE" ]; then
    echo "Sourcing ${ENV_FILE}..."
    source "$ENV_FILE"
fi

# Determine LIBRESCOOT_VERSION
if [ -z "${LIBRESCOOT_VERSION}" ]; then
    LIBRESCOOT_VERSION="0.0.1-dev"
fi

# Select kas config based on target
case "$TARGET" in
    mdb)  KAS_CONFIG="kas/mdb.yml" ;;
    dbc)  KAS_CONFIG="kas/dbc.yml" ;;
    rpi4) KAS_CONFIG="kas/rpi4.yml" ;;
    *)
        echo "Error: Unknown target '$TARGET'. Use mdb, dbc, or rpi4."
        exit 1
        ;;
esac

echo "Building LibreScoot ${TARGET} using kas..."
echo "  Config: ${KAS_CONFIG}"
echo "  Version: ${LIBRESCOOT_VERSION}"

# Build additional local.conf overrides
KAS_LOCAL_CONF=""
KAS_LOCAL_CONF+="LIBRESCOOT_VERSION = \"${LIBRESCOOT_VERSION}\"\n"
KAS_LOCAL_CONF+="MENDER_ARTIFACT_NAME = \"release-${LIBRESCOOT_VERSION}\"\n"

# Apply SRCREV overrides from environment
for var in $(compgen -v | grep '^SRCREV_'); do
    val="${!var}"
    if [ -n "$val" ]; then
        pkg_name="${var#SRCREV_}"
        pkg_name="${pkg_name//_/-}"
        KAS_LOCAL_CONF+="SRCREV:pn-${pkg_name} = \"${val}\"\n"
    fi
done

if [ -n "$DISTRO_CODENAME" ]; then
    KAS_LOCAL_CONF+="DISTRO_CODENAME = \"${DISTRO_CODENAME}\"\n"
fi

# Export additional local.conf content for kas
export KAS_LOCAL_CONF

# If building a specific package
if [ -n "${PACKAGE}" ]; then
    echo "Building specific package: ${PACKAGE}"
    kas build "${KAS_CONFIG}" --target "${PACKAGE}"
else
    echo "Building full image..."
    kas build "${KAS_CONFIG}"
fi
