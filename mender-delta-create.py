#!/usr/bin/env python3
"""
Creates optimized delta patches between Mender update files.
"""
import sys
import os
import tarfile
import tempfile
import shutil
import subprocess
import json
import hashlib
import gzip
from datetime import datetime, timezone
from pathlib import Path

# --- (calculate_sha256, extract_mender, decompress_gz, is_gzipped, create_xdelta_patch functions are unchanged) ---
def calculate_sha256(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def extract_mender(mender_file, extract_dir):
    print(f"Extracting {mender_file}...")
    with tarfile.open(mender_file, 'r') as tar:
        tar.extractall(extract_dir)
    return extract_dir

def decompress_gz(gz_file, output_file):
    with gzip.open(gz_file, 'rb') as f_in:
        with open(output_file, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

def is_gzipped(filepath):
    try:
        with gzip.open(filepath, 'rb') as f: f.read(1)
        return True
    except: return False

# Cap encoder memory while matching across a complete 512 MiB MDB image.
# The decoder does not need to allocate this whole source window.
SOURCE_WINDOW_BYTES = 512 * 1024 * 1024


def compressed_size(filepath):
    import zlib
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    size = 0
    with open(filepath, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(compressor.compress(block))
    return size + len(compressor.flush())


def create_xdelta_patch(old_file, new_file, patch_file):
    base = ['xdelta3', '-e', '-9', '-S', 'none']
    candidates = [(patch_file, []), (patch_file + '.large-window', ['-B', str(SOURCE_WINDOW_BYTES)])]
    try:
        for candidate, options in candidates:
            cmd = base + options + ['-s', old_file, new_file, candidate]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"xdelta3 failed: {result.stderr}")
        sizes = [compressed_size(candidate) for candidate, _ in candidates]
        print(f"  Compressed patch candidates: default={sizes[0]}, large-window={sizes[1]} bytes")
        if sizes[1] < sizes[0]:
            os.replace(candidates[1][0], patch_file)
        return patch_file
    finally:
        if os.path.exists(candidates[1][0]):
            os.remove(candidates[1][0])

def payload_paths(files):
    paths = [path for path in files if path in ('data/0000.tar.gz', 'data/0000.tar.zst')]
    if len(paths) > 1:
        raise ValueError('artifact contains multiple rootfs payloads')
    return paths[0] if paths else None


def process_file_for_delta(filepath, work_dir, file_id):
    filename = os.path.basename(filepath)
    metadata = {'original_name': filename, 'compressed': False, 'sha256': calculate_sha256(filepath), 'size': os.path.getsize(filepath)}
    if filename.endswith('.gz') and is_gzipped(filepath):
        decompressed_path = os.path.join(work_dir, f"{file_id}.decompressed")
        decompress_gz(filepath, decompressed_path)
    elif filename.endswith('.tar.zst'):
        decompressed_path = os.path.join(work_dir, f"{file_id}.decompressed")
        with open(decompressed_path, 'wb') as output:
            subprocess.run(['zstd', '-q', '-d', '-c', filepath], stdout=output, check=True)
    else:
        return filepath, metadata
    metadata['compressed'] = True
    metadata['decompressed_sha256'] = calculate_sha256(decompressed_path)
    metadata['decompressed_size'] = os.path.getsize(decompressed_path)
    return decompressed_path, metadata

def get_file_list(directory):
    files = {}
    base_path = Path(directory)
    for filepath in base_path.rglob('*'):
        if filepath.is_file():
            rel_path = str(filepath.relative_to(base_path))
            files[rel_path] = {'sha256': calculate_sha256(filepath)}
    return files

def get_artifact_name(mender_dir):
    header_path = os.path.join(mender_dir, 'header.tar.gz')
    if not os.path.exists(header_path): return None
    with tempfile.TemporaryDirectory() as temp_dir:
        with tarfile.open(header_path, 'r:gz') as tar:
            tar.extractall(temp_dir)
        header_info_path = os.path.join(temp_dir, 'header-info')
        if os.path.exists(header_info_path):
            with open(header_info_path, 'r') as f:
                header_info = json.load(f)
                return header_info.get('artifact_provides', {}).get('artifact_name')
    return None

def get_payload_checksum(mender_dir):
    header_path = os.path.join(mender_dir, 'header.tar.gz')
    if not os.path.exists(header_path): return None
    with tempfile.TemporaryDirectory() as temp_dir:
        with tarfile.open(header_path, 'r:gz') as tar:
            tar.extractall(temp_dir)
        type_info_path = next(Path(temp_dir).rglob('type-info'), None)
        if type_info_path:
            with open(type_info_path, 'r') as f:
                type_info = json.load(f)
                return type_info.get('artifact_provides', {}).get('rootfs-image.checksum')
    return None


def create_delta_patch(old_mender, new_mender, output_delta, algorithm='xdelta3'):
    if algorithm not in ('xdelta3', 'hdiffpatch'):
        raise ValueError(f'unsupported delta algorithm: {algorithm}')
    with tempfile.TemporaryDirectory() as temp_dir:
        old_dir, new_dir, delta_dir, work_dir = [os.path.join(temp_dir, d) for d in ['old', 'new', 'delta', 'work']]
        for d in [old_dir, new_dir, delta_dir, work_dir]: os.makedirs(d)

        extract_mender(old_mender, old_dir)
        extract_mender(new_mender, new_dir)

        old_files, new_files = get_file_list(old_dir), get_file_list(new_dir)
        old_payload, new_payload = payload_paths(old_files), payload_paths(new_files)
        old_names = {}
        if old_payload and new_payload and old_payload != new_payload:
            # Compression is an outer representation. Delta the raw payloads
            # even when the member changes from .tar.gz to .tar.zst or back.
            old_files[new_payload] = old_files.pop(old_payload)
            old_names[new_payload] = old_payload

        metadata = {
            'old_artifact_name': get_artifact_name(old_dir),
            'new_artifact_name': get_artifact_name(new_dir),
            'old_payload_checksum': get_payload_checksum(old_dir),
            'new_payload_checksum': get_payload_checksum(new_dir),
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'version': 3,
            'changes': {}
        }

        patches_dir = os.path.join(delta_dir, 'patches')
        new_files_dir = os.path.join(delta_dir, 'new_files')
        os.makedirs(patches_dir)
        os.makedirs(new_files_dir)

        print("\nAnalyzing differences...")
        for rel_path, new_info in new_files.items():
            old_file_path = os.path.join(old_dir, old_names.get(rel_path, rel_path))
            new_file_path = os.path.join(new_dir, rel_path)

            # Metadata and its signature travel verbatim. The device's xdelta
            # path reconstructs the payload, not arbitrary metadata files.
            if rel_path in ['version', 'manifest', 'manifest.sig', 'header.tar.gz']:
                print(f"  Including new metadata file: {rel_path}")
                dest_path = os.path.join(new_files_dir, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(new_file_path, dest_path)
                metadata['changes'][rel_path] = {'type': 'new'}
                continue

            if rel_path in old_files and old_files[rel_path]['sha256'] != new_info['sha256']:
                print(f"  Modified: {rel_path}")
                old_processed, old_meta = process_file_for_delta(old_file_path, work_dir, f"old_{rel_path.replace('/', '_')}")
                new_processed, new_meta = process_file_for_delta(new_file_path, work_dir, f"new_{rel_path.replace('/', '_')}")
                
                patch_name = rel_path.replace('/', '_').replace('\\', '_') + ('.hdiff' if algorithm == 'hdiffpatch' else '.xdelta')
                patch_path = os.path.join(patches_dir, patch_name)
                if algorithm == 'hdiffpatch':
                    cmd = ['hdiffz', '-m-4', '-p-2', '-c-zstd-20', old_processed, new_processed, patch_path]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise RuntimeError(f'hdiffz failed: {result.stderr}')
                else:
                    create_xdelta_patch(old_processed, new_processed, patch_path)
                
                metadata['changes'][rel_path] = {
                    'type': 'modified',
                    'patch': patch_name,
                    'old_meta': old_meta,
                    'new_meta': new_meta
                }
                if algorithm == 'hdiffpatch':
                    metadata['changes'][rel_path]['algorithm'] = algorithm
            elif rel_path not in old_files:
                print(f"  New: {rel_path}")
                dest_path = os.path.join(new_files_dir, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(new_file_path, dest_path)
                metadata['changes'][rel_path] = {'type': 'new'}

        for rel_path in old_files:
            if rel_path not in new_files:
                print(f"  Deleted: {rel_path}")
                metadata['changes'][rel_path] = {'type': 'deleted'}

        with open(os.path.join(delta_dir, 'metadata.json'), 'w') as f:
            json.dump(metadata, indent=2, fp=f)

        # metadata.json goes in first so a reader can check which base the
        # delta applies to without unpacking the patches. The order is spelled
        # out here rather than left to tarfile's directory walk.
        print(f"\nCreating delta package: {output_delta}")
        with tarfile.open(output_delta, 'w:gz') as tar:
            tar.add(os.path.join(delta_dir, 'metadata.json'), arcname='./metadata.json')
            for entry in ('new_files', 'patches'):
                tar.add(os.path.join(delta_dir, entry), arcname=f'./{entry}')
        
        print("\n✓ Delta patch created successfully!")

# --- (main function unchanged) ---
def main():
    if len(sys.argv) not in (4, 5) or (len(sys.argv) == 5 and sys.argv[4] != '--hdiffpatch'):
        print(f"Usage: python3 {sys.argv[0]} <old.mender> <new.mender> <output.delta|output.hdelta> [--hdiffpatch]")
        sys.exit(1)
    algorithm = 'hdiffpatch' if len(sys.argv) == 5 else 'xdelta3'
    executable = 'hdiffz' if algorithm == 'hdiffpatch' else 'xdelta3'
    if shutil.which(executable) is None:
        print(f"Error: {executable} is not installed or not in PATH.")
        sys.exit(1)
    try:
        create_delta_patch(sys.argv[1], sys.argv[2], sys.argv[3], algorithm)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
