#!/bin/bash
# Generate kas lockfiles for a given channel
#
# Usage:
#   ./kas/generate-lockfiles.sh <channel> [target...]
#
# Examples:
#   ./kas/generate-lockfiles.sh nightly          # All targets
#   ./kas/generate-lockfiles.sh testing mdb      # MDB only
#   ./kas/generate-lockfiles.sh stable           # All targets + git tag
#
# Channels:
#   nightly  - Dump current AUTOREV resolutions
#   testing  - Promote from nightly lockfiles
#   stable   - Promote from testing lockfiles + tag

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_DIR="${SCRIPT_DIR}/lock"
ALL_TARGETS=(mdb dbc rpi4)

usage() {
    echo "Usage: $0 <channel> [target...]"
    echo ""
    echo "Channels: nightly, testing, stable"
    echo "Targets:  mdb, dbc, rpi4 (default: all)"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

CHANNEL="$1"
shift

# Determine targets
if [ $# -gt 0 ]; then
    TARGETS=("$@")
else
    TARGETS=("${ALL_TARGETS[@]}")
fi

# Validate channel
case "$CHANNEL" in
    nightly|testing|stable) ;;
    *) echo "Error: Unknown channel '$CHANNEL'"; usage ;;
esac

# Ensure lock directory exists
mkdir -p "$LOCK_DIR"

echo "Generating ${CHANNEL} lockfiles for: ${TARGETS[*]}"

for TARGET in "${TARGETS[@]}"; do
    LOCKFILE="${LOCK_DIR}/${CHANNEL}-${TARGET}.lock.yml"

    case "$CHANNEL" in
        nightly)
            # Dump directly from the kas config (resolves AUTOREV)
            echo "  ${TARGET}: kas dump --lock kas/${TARGET}.yml"
            kas dump --lock "${SCRIPT_DIR}/${TARGET}.yml" > "$LOCKFILE"
            ;;
        testing)
            # Build should have used nightly lockfile; dump the resolved state
            NIGHTLY_LOCK="${LOCK_DIR}/nightly-${TARGET}.lock.yml"
            if [ ! -f "$NIGHTLY_LOCK" ]; then
                echo "  ${TARGET}: WARNING - no nightly lockfile found, dumping from config"
                kas dump --lock "${SCRIPT_DIR}/${TARGET}.yml" > "$LOCKFILE"
            else
                echo "  ${TARGET}: promoting nightly → testing"
                cp "$NIGHTLY_LOCK" "$LOCKFILE"
            fi
            ;;
        stable)
            # Promote from testing lockfile
            TESTING_LOCK="${LOCK_DIR}/testing-${TARGET}.lock.yml"
            if [ ! -f "$TESTING_LOCK" ]; then
                echo "  ${TARGET}: ERROR - no testing lockfile found!"
                echo "  Cannot create stable lockfile without a tested baseline."
                exit 1
            fi
            echo "  ${TARGET}: promoting testing → stable"
            cp "$TESTING_LOCK" "$LOCKFILE"
            ;;
    esac

    echo "  ${TARGET}: wrote ${LOCKFILE}"
done

# For stable releases, create a git tag
if [ "$CHANNEL" = "stable" ]; then
    if [ -n "${LIBRESCOOT_VERSION:-}" ]; then
        echo ""
        echo "Tagging commit as ${LIBRESCOOT_VERSION}..."
        git tag -a "$LIBRESCOOT_VERSION" -m "Stable release ${LIBRESCOOT_VERSION}"
        echo "Created tag: ${LIBRESCOOT_VERSION}"
        echo "Don't forget to push: git push origin ${LIBRESCOOT_VERSION}"
    else
        echo ""
        echo "Note: Set LIBRESCOOT_VERSION to auto-tag stable releases"
        echo "  LIBRESCOOT_VERSION=v1.0.0 ./kas/generate-lockfiles.sh stable"
    fi
fi

echo ""
echo "Done! Lockfiles in ${LOCK_DIR}/"
