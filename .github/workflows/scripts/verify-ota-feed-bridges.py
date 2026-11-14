#!/usr/bin/env python3
"""Refuse zstd-only firmware until the live legacy feeds are pinned to bridges."""
import json
import os
import re
import sys
import time
import urllib.request

CHANNELS = ('stable', 'testing', 'nightly')
BASE = 'https://downloads.librescoot.org/releases'


def verify(legacy, v2, bridge, current_tag):
    if not isinstance(bridge, dict) or bridge.get('version') != 1:
        raise ValueError('missing versioned bridge manifest')
    bridges = bridge.get('bridges')
    if not isinstance(bridges, dict) or any(c not in bridges for c in CHANNELS):
        raise ValueError('all three bridge releases must be pinned')
    if not isinstance(legacy, dict) or not isinstance(v2, dict):
        raise ValueError('legacy and v2 latest manifests must be objects')
    tags = {}
    for channel in CHANNELS:
        item = bridges[channel]
        if not isinstance(item, dict) or legacy.get(channel) != item:
            raise ValueError(f'{channel}: legacy latest does not match the verified bridge')
        tag = item.get('tag_name', '')
        if channel == 'stable':
            if tag != 'v1.4.3':
                raise ValueError('stable bridge must be v1.4.3')
        elif not re.fullmatch(rf'{channel}-\d{{8}}T\d{{6}}', tag):
            raise ValueError(f'{channel}: invalid channel bridge tag')
        if not isinstance(v2.get(channel), dict) or not v2[channel].get('tag_name'):
            raise ValueError(f'{channel}: v2 latest is missing')
        for board in ('mdb', 'dbc'):
            expected = f'librescoot-unu-{board}-{tag}.mender'
            candidates = [a for a in item.get('assets', []) if a.get('name') == expected]
            if len(candidates) != 1 or not re.fullmatch(r'[a-f0-9]{64}', candidates[0].get('sha256') or ''):
                raise ValueError(f'{channel}: bridge lacks verified {board} artifact')
        tags[channel] = tag
    if current_tag in tags.values() or current_tag == 'v1.4.3':
        raise ValueError('the bridge itself must remain gzip-compressed')
    return tags


def fetch(path):
    request = urllib.request.Request(f'{BASE}/{path}?build-check={time.time_ns()}',
        headers={'Cache-Control': 'no-cache', 'User-Agent': 'librescoot-firmware-release'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    tag = os.environ.get('CURRENT_TAG', '')
    if not tag:
        raise ValueError('CURRENT_TAG is required')
    tags = verify(fetch('latest.json'), fetch('v2/latest.json'), fetch('v2/bridge.json'), tag)
    print('Legacy feeds pinned to bridge releases:', tags)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'OTA bridge verification failed: {error}', file=sys.stderr)
        sys.exit(1)
