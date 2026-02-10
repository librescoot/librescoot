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

def create_xdelta_patch(old_file, new_file, patch_file):
    cmd = ['xdelta3', '-e', '-9', '-S', 'none', '-s', old_file, new_file, patch_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"xdelta3 failed: {result.stderr}")
    return patch_file

def process_file_for_delta(filepath, work_dir, file_id):
    filename = os.path.basename(filepath)
    metadata = {'original_name': filename, 'compressed': False, 'sha256': calculate_sha256(filepath)}
    if filename.endswith('.gz') and is_gzipped(filepath):
        decompressed_path = os.path.join(work_dir, f"{file_id}.decompressed")
        decompress_gz(filepath, decompressed_path)
        metadata['compressed'] = True
        metadata['decompressed_sha256'] = calculate_sha256(decompressed_path)
        return decompressed_path, metadata
    else:
        return filepath, metadata

def get_file_list(directory):
    files = {}
    base_path = Path(directory)
    for filepath in base_path.rglob('*'):
        if filepath.is_file():
            rel_path = str(filepath.relative_to(base_path))
            files[rel_path] = {'sha256': calculate_sha256(filepath)}
    return files

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


def create_delta_patch(old_mender, new_mender, output_delta):
    with tempfile.TemporaryDirectory() as temp_dir:
        old_dir, new_dir, delta_dir, work_dir = [os.path.join(temp_dir, d) for d in ['old', 'new', 'delta', 'work']]
        for d in [old_dir, new_dir, delta_dir, work_dir]: os.makedirs(d)

        extract_mender(old_mender, old_dir)
        extract_mender(new_mender, new_dir)

        old_files, new_files = get_file_list(old_dir), get_file_list(new_dir)
        
        metadata = {
            'old_payload_checksum': get_payload_checksum(old_dir),
            'new_payload_checksum': get_payload_checksum(new_dir),
            'version': 3, # Mark as new format
            'changes': {}
        }

        patches_dir = os.path.join(delta_dir, 'patches')
        new_files_dir = os.path.join(delta_dir, 'new_files')
        os.makedirs(patches_dir)
        os.makedirs(new_files_dir)

        print("\nAnalyzing differences...")
        for rel_path, new_info in new_files.items():
            old_file_path = os.path.join(old_dir, rel_path)
            new_file_path = os.path.join(new_dir, rel_path)

            # *** THE CRITICAL CHANGE IS HERE ***
            # Treat metadata files as "new" to avoid brittle patches.
            if rel_path in ['manifest', 'header.tar.gz']:
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
                
                patch_name = rel_path.replace('/', '_').replace('\\', '_') + '.xdelta'
                patch_path = os.path.join(patches_dir, patch_name)
                create_xdelta_patch(old_processed, new_processed, patch_path)
                
                metadata['changes'][rel_path] = {
                    'type': 'modified',
                    'patch': patch_name,
                    'old_meta': old_meta,
                    'new_meta': new_meta
                }
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

        print(f"\nCreating delta package: {output_delta}")
        with tarfile.open(output_delta, 'w:gz') as tar:
            tar.add(delta_dir, arcname='.')
        
        print("\n✓ Delta patch created successfully!")

# --- (main function unchanged) ---
def main():
    if len(sys.argv) != 4:
        print(f"Usage: python3 {sys.argv[0]} <old.mender> <new.mender> <output.delta>")
        sys.exit(1)
    if shutil.which('xdelta3') is None:
        print("Error: xdelta3 is not installed or not in PATH.")
        sys.exit(1)
    try:
        create_delta_patch(sys.argv[1], sys.argv[2], sys.argv[3])
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
