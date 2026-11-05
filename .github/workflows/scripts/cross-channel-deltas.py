#!/usr/bin/env python3
"""Generate bounded, explicit stable/testing delta edges without changing legacy assets."""
import argparse
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ota_catalog import descriptor, inspect_artifact, stream_digest


def select_sources(releases, channel, current, feed='releases'):
    published = [r for r in releases if not r.get('draft') and r['tag_name'] != current]
    if feed == 'canary':
        # Existing regular images remain useful bootstrap bases, but canary
        # artifacts are never candidates for regular clients or regular CI.
        canary = [dict(r, tag_name=r['tag_name'].removeprefix('canary-')) for r in published if r['tag_name'].startswith('canary-')]
        published = [r for r in published if not r['tag_name'].startswith('canary-')] + canary
    stable = [r for r in published if r['tag_name'].startswith('v') and (feed == 'canary' or not r['prerelease'])]
    testing = [r for r in published if r['prerelease'] and r['tag_name'].startswith('testing-')]
    stable.sort(key=lambda r: r['published_at'], reverse=True)
    testing.sort(key=lambda r: r['published_at'], reverse=True)
    return (stable[:1] + testing[:1]) if channel == 'testing' else (stable[:2] + testing[:1])


def fetch_json(url):
    headers = {'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        return json.load(response)


def download(asset, path):
    checksum = asset.get('digest', '')
    if not checksum.startswith('sha256:'):
        raise ValueError('source release asset has no SHA256 digest')
    subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--retry', '3',
                    '--connect-timeout', '15', '--max-time', '900', '-o', str(path), asset['browser_download_url']], check=True)
    with path.open('rb') as stream:
        if stream_digest(stream) != checksum[7:]:
            raise ValueError('source artifact checksum mismatch')


def verify_patch(old, new, delta):
    # Verify exactly the bytes the device's xdelta path consumes and produces.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, source in [('old', old), ('new', new)]:
            with tarfile.open(source, 'r:') as artifact:
                members = [m for m in artifact if m.name.startswith('data/') and m.isfile()]
                if len(members) != 1:
                    raise ValueError('unexpected payload layout')
                with gzip.GzipFile(fileobj=artifact.extractfile(members[0])) as payload, (tmp / name).open('wb') as out:
                    shutil.copyfileobj(payload, out)
        with tarfile.open(delta, 'r:gz') as archive:
            metadata = json.load(archive.extractfile('./metadata.json'))
            patches = [c['patch'] for c in metadata['changes'].values() if c['type'] == 'modified']
            if len(patches) != 1:
                raise ValueError('expected exactly one rootfs patch')
            with archive.extractfile('./patches/' + patches[0]) as source, (tmp / 'patch').open('wb') as out:
                shutil.copyfileobj(source, out)
        subprocess.run(['xdelta3', '-d', '-s', str(tmp / 'old'), str(tmp / 'patch'), str(tmp / 'result')], check=True)
        with (tmp / 'new').open('rb') as wanted, (tmp / 'result').open('rb') as got:
            if stream_digest(wanted) != stream_digest(got):
                raise ValueError('delta reconstruction does not match target payload')
        with tarfile.open(new, 'r:') as target, tarfile.open(delta, 'r:gz') as archive:
            for name in ['version', 'manifest', 'header.tar.gz', 'manifest.sig']:
                if name in target.getnames():
                    if target.extractfile(name).read() != archive.extractfile('./new_files/' + name).read():
                        raise ValueError('delta changed target metadata/signature')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', choices=['stable', 'testing', 'nightly'], required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--repo', default='librescoot/librescoot')
    parser.add_argument('--feed', choices=['releases', 'canary'], default='releases')
    parser.add_argument('--release-tag')
    parser.add_argument('--allow-return', action='store_true', help='publish tested testing-to-current-stable rollback edges')
    parser.add_argument('--artifacts', type=Path, default=Path('artifacts'))
    args = parser.parse_args()
    if args.channel == 'nightly':
        return
    releases = []
    for page in range(1, 11):
        batch = fetch_json(f'https://api.github.com/repos/{args.repo}/releases?per_page=100&page={page}')
        if not isinstance(batch, list):
            raise ValueError('invalid GitHub releases response')
        releases.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('release pagination limit exceeded')
    release_tag = args.release_tag or args.version
    if args.feed == 'canary' and any(r['tag_name'] != release_tag and r['tag_name'].removeprefix('canary-') == args.version for r in releases):
        raise ValueError('canary target version must not collide with another published image')
    sources = select_sources(releases, args.channel, release_tag, args.feed)
    spec = importlib.util.spec_from_file_location('delta_create', ROOT / 'mender-delta-create.py')
    creator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(creator)
    base_url = f'https://github.com/{args.repo}/releases/download/'
    with tempfile.TemporaryDirectory() as tmp:
        for variant in ['unu-mdb', 'unu-dbc']:
            target_name = f'librescoot-{variant}-{args.version}.mender'
            matches = list(args.artifacts.rglob(target_name))
            if len(matches) != 1:
                raise ValueError('missing or ambiguous new artifact: ' + target_name)
            target_path = matches[0]
            target = inspect_artifact(target_path, variant, args.version, base_url + release_tag + '/' + target_name)
            # A standalone artifact descriptor also supports a channel's first release.
            (args.artifacts / f'ota-v2-{variant}-{args.version}.json').write_text(json.dumps(
                dict(schema_version=2, artifacts=[target], deltas=[]), indent=2) + '\n')
            for release in sources:
                tag = release['tag_name']
                filename = f'librescoot-{variant}-{tag}.mender'
                assets = [a for a in release['assets'] if a['name'] == filename]
                if len(assets) != 1:
                    continue  # A partial release is not a source for this board.
                if not assets[0].get('digest', '').startswith('sha256:'):
                    print(f'Skipping {filename}: source has no verifiable release digest', file=sys.stderr)
                    continue
                old_path = Path(tmp) / filename
                download(assets[0], old_path)
                old = inspect_artifact(old_path, variant, tag, assets[0]['browser_download_url'])
                pairs = [(old, target, old_path, target_path)]
                # Explicit return to current stable; never mutate the old stable release.
                if args.allow_return and args.channel == 'testing' and tag.startswith('v'):
                    pairs.append((target, old, target_path, old_path))
                for source, dest, source_path, dest_path in pairs:
                    name = f'librescoot-{variant}-from-{source["id"]}-to-{dest["id"]}.delta'
                    output = args.artifacts / name
                    creator.create_delta_patch(str(source_path), str(dest_path), str(output))
                    verify_patch(source_path, dest_path, output)
                    doc = descriptor(source, dest, output, base_url + release_tag + '/' + name)
                    (args.artifacts / (name + '.json')).write_text(json.dumps(doc, indent=2) + '\n')


if __name__ == '__main__':
    main()
