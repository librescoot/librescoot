#!/usr/bin/env bash
# Print the newest published release in the channel, excluding the current tag.
set -euo pipefail
: "${REPO:?}" "${CHANNEL:?}" "${GITHUB_TOKEN:?}"
case "$CHANNEL" in
  stable) prefix=v; prerelease=false ;;
  testing) prefix=testing-; prerelease=true ;;
  nightly) prefix=nightly-; prerelease=true ;;
  *) echo "Unknown channel: $CHANNEL" >&2; exit 1 ;;
esac
for page in $(seq 1 100); do
  releases=$(curl --fail --silent --show-error --location --connect-timeout 15 --retry 3 --retry-delay 5 \
    -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/${REPO}/releases?per_page=100&page=${page}")
  if ! jq -e 'type == "array"' >/dev/null 2>&1 <<< "$releases"; then
    echo "Error: GitHub API did not return a release list on page $page" >&2
    exit 1
  fi
  release=$(jq -c --arg prefix "$prefix" --arg current "${CURRENT_TAG:-}" --argjson prerelease "$prerelease" \
    '[.[] | select(.draft == false and .prerelease == $prerelease and .tag_name != $current and (.tag_name | startswith($prefix)))] | .[0] // null' <<< "$releases")
  if [ "$release" != null ]; then
    echo "$release"
    exit 0
  fi
  if [ "$(jq 'length' <<< "$releases")" -lt 100 ]; then
    echo null
    exit 0
  fi
done
echo 'Error: release pagination limit reached' >&2
exit 1
