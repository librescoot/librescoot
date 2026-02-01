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
# Environment variables:
#   TARGET          - Build target (mdb/dbc/rpi4, default: mdb)
#   BUILD_CHANNEL   - Channel (nightly/testing/stable, default: nightly)
#   LIBRESCOOT_VERSION - Version string for the build
#   LOCKFILE        - Explicit lockfile path (overrides channel logic)
#   PACKAGE         - Build a specific package instead of full image
#   GENERATE_LOCK   - If "1", generate lockfile after build
#
# Prerequisites: kas must be installed in the Docker image
#   pip3 install kas

set -e

TARGET="${TARGET:-mdb}"
BUILD_CHANNEL="${BUILD_CHANNEL:-nightly}"
LIBRESCOOT_VERSION="${LIBRESCOOT_VERSION:-0.0.1-dev}"

cd /yocto

# Determine kas config to use
if [ -n "${LOCKFILE}" ]; then
    # Explicit lockfile specified
    KAS_CONFIG="${LOCKFILE}"
    echo "Using explicit lockfile: ${KAS_CONFIG}"
elif [ "${BUILD_CHANNEL}" = "stable" ]; then
    # Stable: build from testing lockfile
    KAS_CONFIG="kas/lock/testing-${TARGET}.lock.yml"
    if [ ! -f "$KAS_CONFIG" ]; then
        echo "Error: No testing lockfile found at ${KAS_CONFIG}"
        echo "Stable builds require a tested baseline."
        exit 1
    fi
elif [ "${BUILD_CHANNEL}" = "testing" ]; then
    # Testing: build from nightly lockfile
    KAS_CONFIG="kas/lock/nightly-${TARGET}.lock.yml"
    if [ ! -f "$KAS_CONFIG" ]; then
        echo "Warning: No nightly lockfile at ${KAS_CONFIG}, falling back to AUTOREV"
        KAS_CONFIG="kas/${TARGET}.yml"
    fi
else
    # Nightly/dev: build from config (AUTOREV resolves to latest)
    KAS_CONFIG="kas/${TARGET}.yml"
fi

echo "Building LibreScoot ${TARGET} using kas..."
echo "  Config:  ${KAS_CONFIG}"
echo "  Channel: ${BUILD_CHANNEL}"
echo "  Version: ${LIBRESCOOT_VERSION}"

# Build local.conf overrides via KAS_LOCAL_CONF
KAS_LOCAL_CONF=""
KAS_LOCAL_CONF+="LIBRESCOOT_VERSION = \"${LIBRESCOOT_VERSION}\"\n"
KAS_LOCAL_CONF+="MENDER_ARTIFACT_NAME = \"release-${LIBRESCOOT_VERSION}\"\n"

# Apply SRCREV overrides from environment (for development/testing)
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

export KAS_LOCAL_CONF

# Build
if [ -n "${PACKAGE}" ]; then
    echo "Building specific package: ${PACKAGE}"
    kas build "${KAS_CONFIG}" --target "${PACKAGE}"
else
    echo "Building full image..."
    kas build "${KAS_CONFIG}"
fi

# Optionally generate lockfile after build
if [ "${GENERATE_LOCK}" = "1" ]; then
    LOCKFILE_OUT="kas/lock/${BUILD_CHANNEL}-${TARGET}.lock.yml"
    mkdir -p kas/lock
    echo "Generating lockfile: ${LOCKFILE_OUT}"
    kas dump --lock "kas/${TARGET}.yml" > "${LOCKFILE_OUT}"
    echo "Lockfile written to ${LOCKFILE_OUT}"
fi
