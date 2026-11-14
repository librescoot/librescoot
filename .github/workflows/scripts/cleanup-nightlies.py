#!/usr/bin/env python3
"""Keep the qualified Nightly bridge when pruning old prereleases."""
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote

BRIDGE_TAG = re.compile(r"^nightly-\d{8}T\d{6}$")
SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def plan(releases, bridge, bridge_tag, keep_latest=30):
    if not BRIDGE_TAG.fullmatch(bridge_tag or ""):
        raise ValueError("OTA_NIGHTLY_BRIDGE_TAG must name the qualified Nightly bridge")
    if (not isinstance(bridge, dict) or bridge.get("tag_name") != bridge_tag or
            bridge.get("draft") is not False or bridge.get("prerelease") is not True):
        raise ValueError("Nightly bridge pin does not resolve to a published prerelease")
    assets = bridge.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Nightly bridge has no assets")
    for board in ("mdb", "dbc"):
        name = f"librescoot-unu-{board}-{bridge_tag}.mender"
        matches = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
        if (len(matches) != 1 or not isinstance(matches[0].get("digest"), str) or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", matches[0]["digest"]) or
                not isinstance(matches[0].get("size"), int) or matches[0]["size"] <= 0):
            raise ValueError(f"Nightly bridge is missing a digested {board} image")
    if not isinstance(releases, list) or keep_latest < 0:
        raise ValueError("invalid release list or retention count")
    candidates = []
    seen = set()
    for release in releases:
        if not isinstance(release, dict):
            raise ValueError("invalid release entry")
        tag = release.get("tag_name")
        if (release.get("draft") is False and release.get("prerelease") is True and
                release.get("target_commitish") == "wrynose" and isinstance(tag, str) and "nightly" in tag):
            if not SAFE_TAG.fullmatch(tag) or tag in seen:
                raise ValueError("unsafe or duplicate Nightly tag")
            seen.add(tag)
            candidates.append(tag)
    return [tag for tag in candidates[keep_latest:] if tag != bridge_tag]


def gh(*args):
    return subprocess.run(["gh", *args], check=True, text=True, capture_output=True).stdout


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    bridge_tag = os.environ.get("OTA_NIGHTLY_BRIDGE_TAG", "")
    if not BRIDGE_TAG.fullmatch(bridge_tag):
        raise ValueError("OTA_NIGHTLY_BRIDGE_TAG must name the qualified Nightly bridge")
    bridge = json.loads(gh("api", f"repos/{repo}/releases/tags/{quote(bridge_tag, safe='')}"))
    releases = json.loads(gh("api", f"repos/{repo}/releases?per_page=100"))
    deletions = plan(releases, bridge, bridge_tag)
    print(f"Keeping {bridge_tag}; deleting {len(deletions)} old Nightly releases", flush=True)
    for tag in deletions:
        subprocess.run(["gh", "release", "delete", tag, "--repo", repo, "--yes", "--cleanup-tag"], check=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Nightly cleanup refused: {error}", file=sys.stderr)
        sys.exit(1)
