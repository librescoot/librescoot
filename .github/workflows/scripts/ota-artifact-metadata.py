#!/usr/bin/env python3
"""Describe OTA assets from their actual Mender and delta contents."""
import argparse
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

HEX = re.compile(r"^[a-f0-9]{64}$")
VARIANTS = ("unu-mdb", "unu-dbc")


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def small_member(archive, name, limit=1024 * 1024):
    member = archive.getmember(name)
    if not member.isfile() or member.size > limit:
        raise ValueError(f"invalid {name}")
    data = archive.extractfile(member)
    if data is None:
        raise ValueError(f"missing {name}")
    return data.read()


def inspect_full(path, tag, variant):
    with tarfile.open(path, "r:") as artifact:
        if json.loads(small_member(artifact, "version")) != {"format": "mender", "version": 3}:
            raise ValueError(f"{path.name}: unsupported artifact version")
        header_bytes = small_member(artifact, "header.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(header_bytes), mode="r:gz") as header:
            info = json.loads(small_member(header, "header-info"))
            type_info = json.loads(small_member(header, "headers/0000/type-info"))
        identity = info.get("artifact_provides", {}).get("artifact_name")
        if identity != f"release-{tag}" or variant not in info.get("artifact_depends", {}).get("device_type", []):
            raise ValueError(f"{path.name}: artifact identity or variant mismatch")
        rootfs_sha = type_info.get("artifact_provides", {}).get("rootfs-image.checksum")
        if not isinstance(rootfs_sha, str) or not HEX.fullmatch(rootfs_sha):
            raise ValueError(f"{path.name}: missing rootfs checksum")
        manifest = small_member(artifact, "manifest").decode("utf-8").splitlines()
        payload_hashes = [line.split()[0] for line in manifest if len(line.split()) == 2 and line.split()[1].startswith("data/")]
        if payload_hashes != [rootfs_sha]:
            raise ValueError(f"{path.name}: manifest and rootfs checksum differ")
        members = [m for m in artifact.getmembers() if m.name.startswith("data/")]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError(f"{path.name}: expected one payload")
        member = members[0]
        stream = artifact.extractfile(member)
        if stream is None:
            raise ValueError(f"{path.name}: payload missing")
        magic = stream.read(4)
        if member.name == "data/0000.tar.gz" and magic.startswith(b"\x1f\x8b"):
            compression = "gzip"
        elif member.name == "data/0000.tar.zst" and magic == b"\x28\xb5\x2f\xfd":
            compression = "zstd"
        else:
            raise ValueError(f"{path.name}: invalid payload name or compression magic")
    return {
        "size": path.stat().st_size,
        "sha256": digest(path),
        "ota": {"schema": 1, "kind": "full", "variant": variant, "artifact": identity,
                "payload_compression": compression, "requires": ["artifact.mender-v3", f"payload.{compression}"]},
        "rootfs_sha256": rootfs_sha,
    }


def compression_name(name):
    if name == "0000.tar.gz":
        return "gzip"
    if name == "0000.tar.zst":
        return "zstd"
    raise ValueError(f"unsupported payload member {name!r}")


def inspect_delta(path, variant, previous, target, algorithm):
    with tarfile.open(path, "r:gz") as archive:
        meta = json.loads(small_member(archive, "metadata.json"))
    if meta.get("old_artifact_name") != previous["ota"]["artifact"] or meta.get("new_artifact_name") != target["ota"]["artifact"]:
        raise ValueError(f"{path.name}: delta artifact identities do not match images")
    if meta.get("old_payload_checksum") != previous["rootfs_sha256"] or meta.get("new_payload_checksum") != target["rootfs_sha256"]:
        raise ValueError(f"{path.name}: delta rootfs checksums do not match images")
    payload_changes = []
    for name, change in meta.get("changes", {}).items():
        if change.get("type") != "modified":
            continue
        if (change.get("algorithm") or "xdelta3") != algorithm:
            raise ValueError(f"{path.name}: mixed or incorrect patch algorithm")
        if name.startswith("data/"):
            payload_changes.append(change)
    if len(payload_changes) != 1:
        raise ValueError(f"{path.name}: expected one modified payload")
    change = payload_changes[0]
    old_fmt = compression_name(change.get("old_meta", {}).get("original_name"))
    new_fmt = compression_name(change.get("new_meta", {}).get("original_name"))
    if old_fmt != previous["ota"]["payload_compression"] or new_fmt != target["ota"]["payload_compression"]:
        raise ValueError(f"{path.name}: delta payload formats do not match images")
    requirements = ["artifact.mender-v3", f"delta.{algorithm}-v1"]
    requirements.extend(f"payload.{fmt}" for fmt in sorted({old_fmt, new_fmt}))
    return {"size": path.stat().st_size, "sha256": digest(path), "ota": {
        "schema": 1, "kind": "delta", "variant": variant, "algorithm": algorithm,
        "base": {"artifact": previous["ota"]["artifact"], "rootfs_sha256": previous["rootfs_sha256"], "payload_compression": old_fmt},
        "target": {"artifact": target["ota"]["artifact"], "rootfs_sha256": target["rootfs_sha256"], "payload_compression": new_fmt},
        "requires": requirements,
    }}


def single(root, name):
    paths = list(root.rglob(name))
    if len(paths) != 1:
        raise ValueError(f"expected one {name}, found {len(paths)}")
    return paths[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-tag")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = {}
    for variant in VARIANTS:
        name = f"librescoot-{variant}-{args.tag}.mender"
        full = inspect_full(single(args.artifacts, name), args.tag, variant)
        assets[name] = {k: v for k, v in full.items() if k != "rootfs_sha256"}
        delta_paths = [(ext, algorithm) for ext, algorithm in (("delta", "xdelta3"), ("hdelta", "hdiffpatch"))
                       if list(args.artifacts.rglob(f"librescoot-{variant}-{args.tag}.{ext}"))]
        if delta_paths:
            if args.previous is None or not args.previous_tag:
                raise ValueError("previous images and tag are required to attest deltas")
            previous = inspect_full(single(args.previous, f"librescoot-{variant}-previous.mender"), args.previous_tag, variant)
            for ext, algorithm in delta_paths:
                name = f"librescoot-{variant}-{args.tag}.{ext}"
                assets[name] = inspect_delta(single(args.artifacts, name), variant, previous, full, algorithm)
    args.output.write_text(json.dumps({"version": 1, "tag": args.tag, "assets": assets}, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
