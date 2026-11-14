#!/usr/bin/env python3
"""Recompress a Mender payload without modifying its signed manifest or header."""
import argparse
import copy
import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

BLOCK = 1024 * 1024
SOURCE = 'data/0000.tar.gz'
TARGET = 'data/0000.tar.zst'


def copy_and_hash(source, output=None):
    digest = hashlib.sha256()
    while block := source.read(BLOCK):
        digest.update(block)
        if output is not None:
            output.write(block)
    return digest.digest()


def recompress(source, destination, level=19):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('source and destination must be different files')
    if destination.exists():
        raise FileExistsError(destination)
    if not 1 <= level <= 19:
        raise ValueError('zstd level must be between 1 and 19')
    with tempfile.TemporaryDirectory(prefix='.mender-zstd-', dir=destination.parent) as temp:
        temp = Path(temp)
        raw, compressed, result = temp / 'payload.tar', temp / 'payload.zst', temp / 'result.mender'
        with tarfile.open(source, 'r:') as archive:
            members = archive.getmembers()
            names = [m.name for m in members]
            if len(names) != len(set(names)):
                raise ValueError('duplicate Mender artifact members')
            if names.count(SOURCE) != 1 or TARGET in names:
                raise ValueError('expected exactly one gzip payload and no zstd payload')
            if not {'version', 'manifest', 'header.tar.gz'}.issubset(names):
                raise ValueError('missing Mender version, manifest or gzip header')
            if any(not m.isfile() for m in members):
                raise ValueError('Mender artifact has a non-file outer member')
            payload = archive.extractfile(SOURCE)
            with gzip.GzipFile(fileobj=payload) as decoded, raw.open('wb') as output:
                expected_hash = copy_and_hash(decoded, output)
            with compressed.open('wb') as output:
                subprocess.run(['zstd', '-q', f'-{level}', '-T2', '-c', str(raw)], stdout=output, check=True)
            with subprocess.Popen(['zstd', '-q', '-d', '-c', str(compressed)], stdout=subprocess.PIPE) as decoder:
                actual_hash = copy_and_hash(decoder.stdout)
                decoder.stdout.close()
                if decoder.wait() != 0:
                    raise ValueError('zstd verification failed')
            if actual_hash != expected_hash:
                raise ValueError('recompressed payload does not match the original')
            with tarfile.open(result, 'w:', format=tarfile.PAX_FORMAT) as out:
                for member in members:
                    info = copy.copy(member)
                    if member.name == SOURCE:
                        info.name = TARGET
                        info.size = compressed.stat().st_size
                        info.pax_headers = {k: v for k, v in info.pax_headers.items() if k not in ('path', 'size')}
                        with compressed.open('rb') as stream:
                            out.addfile(info, stream)
                    else:
                        with archive.extractfile(member) as stream:
                            out.addfile(info, stream)
        # Never replace an existing output, including in a concurrent build.
        os.link(result, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('--level', type=int, default=19)
    args = parser.parse_args()
    recompress(args.source, args.destination, args.level)


if __name__ == '__main__':
    main()
