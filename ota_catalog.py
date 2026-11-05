"""Immutable identities and descriptors for rootfs-image OTA artifacts."""
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stream_digest(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
    return h.hexdigest()


def inspect_artifact(filename, variant, version, url):
    with tarfile.open(filename, 'r:') as artifact:
        manifest = artifact.extractfile('manifest').read()
        header = artifact.extractfile('header.tar.gz').read()
        with tarfile.open(fileobj=io.BytesIO(header), mode='r:gz') as headers:
            info = json.load(headers.extractfile('header-info'))
        name = info['artifact_provides']['artifact_name']
        devices = info['artifact_depends']['device_type']
        if variant not in devices or name != 'release-' + version:
            raise ValueError('artifact name/device type does not match release')
        payloads = [m for m in artifact.getmembers() if m.name.startswith('data/') and m.isfile()]
        if len(payloads) != 1:
            raise ValueError('expected one rootfs payload')
        # The xdelta input is the entire uncompressed payload tar, including padding.
        with gzip.GzipFile(fileobj=artifact.extractfile(payloads[0])) as payload:
            payload_hash = stream_digest(payload)
            payload_size = payload.tell()
        with gzip.GzipFile(fileobj=artifact.extractfile(payloads[0])) as payload:
            with tarfile.open(fileobj=payload, mode='r|') as rootfs:
                members = (m for m in rootfs if m.isfile())
                member = next(members)
                rootfs_hash = stream_digest(rootfs.extractfile(member))
                if next(members, None) is not None:
                    raise ValueError('expected one rootfs image')
        entries = [line.split() for line in manifest.decode().splitlines()]
        if not any(len(e) == 2 and e[0] == rootfs_hash and e[1].startswith('data/') for e in entries):
            raise ValueError('rootfs does not match manifest')
        manifest_hash, header_hash = digest(manifest), digest(header)
    identity = digest(f'{variant}\n{name}\n{manifest_hash}\n{header_hash}\n'.encode())
    with open(filename, 'rb') as f:
        transport_hash = stream_digest(f)
    return dict(id=identity, variant_id=variant, version=version, artifact_name=name,
                device_types=devices, manifest_sha256=manifest_hash, header_sha256=header_hash,
                rootfs_sha256=rootfs_hash, payload_tar_sha256=payload_hash, payload_tar_size=payload_size,
                full=dict(url=url, size=Path(filename).stat().st_size, sha256=transport_hash))


def descriptor(old, new, delta_path, delta_url):
    if old['variant_id'] != new['variant_id'] or old['id'] == new['id']:
        raise ValueError('invalid delta endpoints')
    with open(delta_path, 'rb') as f:
        checksum = stream_digest(f)
    return dict(schema_version=2, artifacts=[old, new], deltas=[dict(
        source=old['id'], target=new['id'], url=delta_url,
        size=Path(delta_path).stat().st_size, sha256=checksum)])
