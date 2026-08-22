#!/usr/bin/env bash
set -euo pipefail

# Generate the release changelog.
#
# Nightly (nightly.env leaves SRCREVs empty, AUTOREV): diff all tracked repos
# between the previous nightly release timestamp and this build's start time.
#
# Testing & stable (both source stable.env with pinned SRCREVs): for each
# pinned SRCREV and LAYER_VERSION_meta_librescoot, diff the exact commits
# between the previous release of the same channel and this one via the
# /compare API. Repos that exist in the workflow but are not pinned in
# stable.env fall back to the time-window query for that section only.
#
# Required env vars:
#   CHANNEL        nightly | testing | stable
#   CURRENT_SHA    github.sha of this build
#   UNTIL_ISO      ISO timestamp when this pipeline started
#   REPO           owner/repo of the repository running this workflow
#   GITHUB_TOKEN   token used for GitHub API auth
#   GITHUB_OUTPUT  path to the step output file (Actions provides this)

: "${CHANNEL:?}"
: "${CURRENT_SHA:?}"
: "${UNTIL_ISO:?}"
: "${REPO:?}"
: "${GITHUB_TOKEN:?}"
: "${GITHUB_OUTPUT:?}"

AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json")

declare -A SRCREV_REPO=(
  [SRCREV_alarm_service]="librescoot/alarm-service"
  [SRCREV_battery_service]="librescoot/battery-service"
  [SRCREV_bluetooth_service]="librescoot/bluetooth-service"
  [SRCREV_boot_animation]="librescoot/boot-animation"
  [SRCREV_data_server]="librescoot/data-server"
  [SRCREV_dbc_backlight_service]="librescoot/dbc-backlight-service"
  [SRCREV_dbc_dispatcher]="librescoot/dbc-dispatcher"
  [SRCREV_ecu_service]="librescoot/ecu-service"
  [SRCREV_keycard_service]="librescoot/keycard-service"
  [SRCREV_lsc]="librescoot/lsc"
  [SRCREV_modem_service]="librescoot/modem-service"
  [SRCREV_motion_service]="librescoot/motion-service"
  [SRCREV_pm_service]="librescoot/pm-service"
  [SRCREV_radio_gaga]="rescoot/radio-gaga"
  [SRCREV_scootui_qt]="librescoot/scootui-qt"
  [SRCREV_scootui_tui]="librescoot/scootui-tui"
  [SRCREV_settings_service]="librescoot/settings-service"
  [SRCREV_ums_service]="librescoot/ums-service"
  [SRCREV_uplink_service]="librescoot/uplink-service"
  [SRCREV_update_service]="librescoot/update-service"
  [SRCREV_vehicle_service]="librescoot/vehicle-service"
  [SRCREV_version_service]="librescoot/version-service"
)

META_REPO="librescoot/meta-librescoot"
TOP_REPO="librescoot/librescoot"

UNPINNED_REPOS=(
  "librescoot/redis-ipc"
  "librescoot/librefsm"
  "librescoot/pn7150"
  "librescoot/kernel-module-imx-pwm-led"
)

NIGHTLY_TIMEWINDOW_REPOS=(
  "librescoot/librescoot"
  "librescoot/meta-librescoot"
  "librescoot/ecu-service"
  "librescoot/vehicle-service"
  "librescoot/battery-service"
  "librescoot/bluetooth-service"
  "librescoot/modem-service"
  "librescoot/version-service"
  "librescoot/update-service"
  "librescoot/ums-service"
  "librescoot/settings-service"
  "librescoot/pm-service"
  "librescoot/dbc-backlight-service"
  "librescoot/lsc"
  "librescoot/alarm-service"
  "librescoot/data-server"
  "rescoot/radio-gaga"
  "librescoot/uplink-service"
  "librescoot/redis-ipc"
  "librescoot/librefsm"
  "librescoot/pn7150"
  "librescoot/boot-animation"
  "librescoot/dbc-dispatcher"
  "librescoot/kernel-module-imx-pwm-led"
  "librescoot/keycard-service"
  "librescoot/scootui-qt"
  "librescoot/scootui-tui"
)

CHANGELOG=""
HAS_CHANGES=false

RELEASES_JSON=$(curl -sS "${AUTH[@]}" \
  "https://api.github.com/repos/${REPO}/releases?per_page=100")
if ! echo "$RELEASES_JSON" | jq empty 2>/dev/null; then
  echo "Warning: could not parse releases JSON from GitHub API" >&2
  RELEASES_JSON="[]"
fi

# Append a commit list (same shape as list-commits or .commits[] from compare)
# under a section header for the given repo. Returns non-zero when there are
# no commits to emit (caller decides whether to skip the header).
render_commits() {
  local repo="$1"
  local commits_json="$2"
  local header="${3:-### ${repo}}"

  local count
  count=$(echo "$commits_json" | jq 'length' 2>/dev/null || echo 0)
  if [ "$count" -eq 0 ]; then
    return 1
  fi

  HAS_CHANGES=true
  CHANGELOG="${CHANGELOG}${header}\n\n"

  local commit sha message url short_message
  while IFS= read -r commit; do
    sha=$(echo "$commit" | jq -r '.sha')
    message=$(echo "$commit" | jq -r '.commit.message' | sed 's/"/\\"/g')
    url=$(echo "$commit" | jq -r '.html_url')
    short_message=$(echo "$message" | head -n1)
    short_message=$(echo "$short_message" | sed "s|#\([0-9]\+\)|${repo}#\1|g")
    CHANGELOG="${CHANGELOG}* [\`${sha:0:7}\`](${url}) - ${short_message}\n"
  done < <(echo "$commits_json" | jq -c '.[]')
  CHANGELOG="${CHANGELOG}\n"
  return 0
}

# Diff a repo between two commit SHAs via the /compare API. On 404 (force-push
# erased the old SHA) emit a short fallback line instead of a commit list.
compare_repo() {
  local repo="$1" old="$2" new="$3"
  local tmp http
  tmp=$(mktemp)
  http=$(curl -sS -o "$tmp" -w '%{http_code}' "${AUTH[@]}" \
    "https://api.github.com/repos/${repo}/compare/${old}...${new}")

  if [ "$http" = "200" ]; then
    local commits
    commits=$(jq -c '.commits' < "$tmp")
    render_commits "$repo" "$commits" || {
      HAS_CHANGES=true
      CHANGELOG="${CHANGELOG}### ${repo}\n\n"
      CHANGELOG="${CHANGELOG}* \`${old:0:7}\` → \`${new:0:7}\` (no commits in range)\n\n"
    }
  else
    echo "Warning: compare ${repo} ${old}...${new} returned HTTP ${http}" >&2
    HAS_CHANGES=true
    CHANGELOG="${CHANGELOG}### ${repo}\n\n"
    CHANGELOG="${CHANGELOG}* \`${old:0:7}\` → \`${new:0:7}\` (history rewritten, no diff available)\n\n"
  fi
  rm -f "$tmp"
}

commits_timewindow() {
  local repo="$1" since="$2" until="$3"
  local commits
  commits=$(curl -sS "${AUTH[@]}" \
    "https://api.github.com/repos/${repo}/commits?since=${since}&until=${until}")
  if ! echo "$commits" | jq empty 2>/dev/null; then
    echo "Warning: could not parse commits for ${repo}" >&2
    return 0
  fi
  render_commits "$repo" "$commits" || true
}

parse_env_var() {
  # Extract a single variable's value from an env file, stripping surrounding
  # double quotes. Returns empty if not found.
  local file="$1" name="$2"
  awk -v name="$name" '
    $0 ~ "^[[:space:]]*"name"=" {
      sub("^[[:space:]]*"name"=", "", $0)
      gsub(/^"|"$/, "", $0)
      print
      exit
    }' "$file"
}

parse_env_prefix_keys() {
  # Print the names of every variable in the env file whose name starts with
  # the given prefix (one per line).
  local file="$1" prefix="$2"
  awk -v pre="$prefix" '
    match($0, "^[[:space:]]*"pre"[A-Za-z0-9_]+=") {
      key=substr($0, RSTART, RLENGTH-1)
      sub(/^[[:space:]]+/, "", key)
      print key
    }' "$file"
}

timewindow_changelog() {
  # Determine the SINCE timestamp from the previous release of the same
  # channel. Falls back to last 24h on first release.
  local prefix since until="${UNTIL_ISO}" prev_tag="" tag_ts=""
  case "$CHANNEL" in
    nightly) prefix="nightly-" ;;
    testing) prefix="testing-" ;;
    stable)  prefix="v" ;;
  esac

  prev_tag=$(echo "$RELEASES_JSON" | jq -r \
    "[.[] | select(.tag_name | startswith(\"${prefix}\"))] | .[0].tag_name // empty")

  if [ -n "$prev_tag" ]; then
    if [ "$CHANNEL" = "stable" ]; then
      since=$(echo "$RELEASES_JSON" | jq -r \
        "[.[] | select(.tag_name == \"${prev_tag}\")] | .[0].published_at // empty")
    else
      tag_ts=${prev_tag#"$prefix"}
      since=$(echo "$tag_ts" | sed 's/\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)T\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)/\1-\2-\3T\4:\5:\6Z/')
    fi
  fi

  if [ -z "${since:-}" ]; then
    since=$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')
    echo "No previous ${CHANNEL} release found, falling back to last 24 hours: ${since} (until ${until})" >&2
  else
    echo "Changelog since previous ${CHANNEL} release: ${since} (until ${until})" >&2
  fi

  local repo
  for repo in "${NIGHTLY_TIMEWINDOW_REPOS[@]}"; do
    commits_timewindow "$repo" "$since" "$until"
  done
}

srcrev_changelog() {
  local prev_tag="" prev_published_at=""

  if [ "$CHANNEL" = "stable" ]; then
    prev_tag=$(echo "$RELEASES_JSON" | jq -r \
      '[.[] | select(.prerelease == false and (.tag_name | startswith("v")))] | .[0].tag_name // empty')
    prev_published_at=$(echo "$RELEASES_JSON" | jq -r \
      '[.[] | select(.prerelease == false and (.tag_name | startswith("v")))] | .[0].published_at // empty')
  else
    prev_tag=$(echo "$RELEASES_JSON" | jq -r \
      '[.[] | select(.prerelease == true and (.tag_name | startswith("testing-")))] | .[0].tag_name // empty')
    prev_published_at=$(echo "$RELEASES_JSON" | jq -r \
      '[.[] | select(.prerelease == true and (.tag_name | startswith("testing-")))] | .[0].published_at // empty')
  fi

  local curr_env="stable.env"
  if [ ! -f "$curr_env" ]; then
    echo "Error: ${curr_env} not found in working directory" >&2
    return 1
  fi

  if [ -z "$prev_tag" ]; then
    echo "No previous ${CHANNEL} release found; emitting initial pinned revisions" >&2
    initial_pinned_revisions "$curr_env"
    return 0
  fi

  echo "Diffing ${CHANNEL} against previous release ${prev_tag}" >&2

  # Make sure the previous tag is present locally before git show.
  git fetch --tags --force origin >/dev/null 2>&1 || true

  local prev_env
  prev_env=$(mktemp)
  if ! git show "${prev_tag}:stable.env" > "$prev_env" 2>/dev/null; then
    echo "Warning: could not read stable.env at ${prev_tag}; treating as first release" >&2
    rm -f "$prev_env"
    initial_pinned_revisions "$curr_env"
    return 0
  fi

  # Top-level repo: diff the release tags directly.
  compare_repo "$TOP_REPO" "$prev_tag" "$CURRENT_SHA"

  # meta-librescoot: diff only when both values are pinned 40-char SHAs.
  local prev_meta curr_meta
  prev_meta=$(parse_env_var "$prev_env" LAYER_VERSION_meta_librescoot)
  curr_meta=$(parse_env_var "$curr_env" LAYER_VERSION_meta_librescoot)
  if [[ "$prev_meta" =~ ^[0-9a-f]{40}$ ]] \
     && [[ "$curr_meta" =~ ^[0-9a-f]{40}$ ]] \
     && [ "$prev_meta" != "$curr_meta" ]; then
    compare_repo "$META_REPO" "$prev_meta" "$curr_meta"
  fi

  # SRCREVs: iterate the union of keys across both env files.
  local -A seen=()
  local key
  while IFS= read -r key; do
    [ -z "$key" ] && continue
    seen[$key]=1
  done < <(parse_env_prefix_keys "$prev_env" SRCREV_; parse_env_prefix_keys "$curr_env" SRCREV_)

  # Stable ordering so the changelog is deterministic run-to-run.
  local sorted_keys
  sorted_keys=$(printf '%s\n' "${!seen[@]}" | sort)

  local repo old new
  while IFS= read -r key; do
    [ -z "$key" ] && continue
    repo="${SRCREV_REPO[$key]:-}"
    if [ -z "$repo" ]; then
      echo "Warning: no repo mapping for ${key}; skipping" >&2
      continue
    fi
    old=$(parse_env_var "$prev_env" "$key")
    new=$(parse_env_var "$curr_env" "$key")
    [ "$old" = "$new" ] && continue

    if [ -z "$old" ] && [ -n "$new" ]; then
      HAS_CHANGES=true
      CHANGELOG="${CHANGELOG}### ${repo}\n\n"
      CHANGELOG="${CHANGELOG}* newly pinned at [\`${new:0:7}\`](https://github.com/${repo}/commit/${new})\n\n"
    elif [ -n "$old" ] && [ -z "$new" ]; then
      HAS_CHANGES=true
      CHANGELOG="${CHANGELOG}### ${repo}\n\n"
      CHANGELOG="${CHANGELOG}* removed (was [\`${old:0:7}\`](https://github.com/${repo}/commit/${old}))\n\n"
    else
      compare_repo "$repo" "$old" "$new"
    fi
  done <<< "$sorted_keys"

  rm -f "$prev_env"

  # Unpinned repos: fall back to time-window between previous release
  # publish time and this build's cutoff.
  if [ ${#UNPINNED_REPOS[@]} -gt 0 ]; then
    local since="$prev_published_at"
    if [ -z "$since" ] || [ "$since" = "null" ]; then
      since=$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')
    fi
    local before_len=${#CHANGELOG}
    local repo
    for repo in "${UNPINNED_REPOS[@]}"; do
      commits_timewindow "$repo" "$since" "$UNTIL_ISO"
    done
    if [ ${#CHANGELOG} -ne "$before_len" ]; then
      # Retroactively prepend the section note. We emit sections individually
      # inside render_commits, so splice the note in before the first one.
      local note="_The components below are not pinned in stable.env and track latest at build time._\n\n"
      CHANGELOG="${CHANGELOG:0:$before_len}## Unpinned components\n\n${note}${CHANGELOG:$before_len}"
    fi
  fi
}

initial_pinned_revisions() {
  local curr_env="$1"
  HAS_CHANGES=true
  CHANGELOG="${CHANGELOG}### Initial pinned revisions\n\n"

  local curr_meta
  curr_meta=$(parse_env_var "$curr_env" LAYER_VERSION_meta_librescoot)
  if [[ "$curr_meta" =~ ^[0-9a-f]{40}$ ]]; then
    CHANGELOG="${CHANGELOG}* \`${META_REPO}\`: [\`${curr_meta:0:7}\`](https://github.com/${META_REPO}/commit/${curr_meta})\n"
  fi

  local sorted_keys
  sorted_keys=$(printf '%s\n' "${!SRCREV_REPO[@]}" | sort)

  local key repo sha
  while IFS= read -r key; do
    repo="${SRCREV_REPO[$key]}"
    sha=$(parse_env_var "$curr_env" "$key")
    [ -z "$sha" ] && continue
    CHANGELOG="${CHANGELOG}* \`${repo}\`: [\`${sha:0:7}\`](https://github.com/${repo}/commit/${sha})\n"
  done <<< "$sorted_keys"
  CHANGELOG="${CHANGELOG}\n"

  # Also emit a time-window section for the unpinned repos so the first
  # release documents recent activity there.
  local since
  since=$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')
  local before_len=${#CHANGELOG}
  local repo
  for repo in "${UNPINNED_REPOS[@]}"; do
    commits_timewindow "$repo" "$since" "$UNTIL_ISO"
  done
  if [ ${#CHANGELOG} -ne "$before_len" ]; then
    local note="_The components below are not pinned in stable.env and track latest at build time._\n\n"
    CHANGELOG="${CHANGELOG:0:$before_len}## Unpinned components\n\n${note}${CHANGELOG:$before_len}"
  fi
}

case "$CHANNEL" in
  nightly)
    timewindow_changelog
    ;;
  testing|stable)
    srcrev_changelog
    ;;
  *)
    echo "Unknown channel: ${CHANNEL}" >&2
    exit 1
    ;;
esac

{
  echo "content<<EOF"
  printf '%b' "$CHANGELOG"
  echo
  echo "EOF"
  echo "has_changes=${HAS_CHANGES}"
} >> "$GITHUB_OUTPUT"
