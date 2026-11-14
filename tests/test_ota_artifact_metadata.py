import gzip
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/workflows/scripts/ota-artifact-metadata.py'
spec = importlib.util.spec_from_file_location('ota_metadata', SCRIPT)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


def add(tar, name, contents):
    info = tarfile.TarInfo(name)
    info.size = len(contents)
    tar.addfile(info, io.BytesIO(contents))


def image(path, tag, variant, compression, checksum):
    header = io.BytesIO()
    with tarfile.open(fileobj=header, mode='w:gz') as tar:
        add(tar, 'header-info', json.dumps({'artifact_provides': {'artifact_name': f'release-{tag}'},
                                           'artifact_depends': {'device_type': [variant]}}).encode())
        add(tar, 'headers/0000/type-info', json.dumps({'artifact_provides': {'rootfs-image.checksum': checksum}}).encode())
    with tarfile.open(path, mode='w') as tar:
        add(tar, 'version', b'{"format":"mender","version":3}')
        add(tar, 'manifest', f'{checksum}  data/0000/rootfs.ext4\n'.encode())
        add(tar, 'header.tar.gz', header.getvalue())
        name = 'data/0000.tar.gz' if compression == 'gzip' else 'data/0000.tar.zst'
        body = gzip.compress(b'payload') if compression == 'gzip' else b'\x28\xb5\x2f\xfdtest'
        add(tar, name, body)


def delta(path, old, new, oldsha, newsha, algorithm):
    info = {'old_artifact_name': old, 'new_artifact_name': new, 'old_payload_checksum': oldsha,
            'new_payload_checksum': newsha, 'changes': {'data/0000.tar.zst': {
                'type': 'modified', 'algorithm': algorithm,
                'old_meta': {'original_name': '0000.tar.gz'}, 'new_meta': {'original_name': '0000.tar.zst'}}}}
    with tarfile.open(path, mode='w:gz') as tar:
        add(tar, 'metadata.json', json.dumps(info).encode())


class MetadataTests(unittest.TestCase):
    def test_full_and_delta_metadata_are_bound_to_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old, new, patch = root / 'old.mender', root / 'new.mender', root / 'update.hdelta'
            image(old, 'v1.4.2', 'unu-mdb', 'gzip', 'a' * 64)
            image(new, 'v1.4.3', 'unu-mdb', 'zstd', 'b' * 64)
            delta(patch, 'release-v1.4.2', 'release-v1.4.3', 'a' * 64, 'b' * 64, 'hdiffpatch')
            old_info = metadata.inspect_full(old, 'v1.4.2', 'unu-mdb')
            new_info = metadata.inspect_full(new, 'v1.4.3', 'unu-mdb')
            result = metadata.inspect_delta(patch, 'unu-mdb', old_info, new_info, 'hdiffpatch')
            self.assertEqual(result['ota']['base']['rootfs_sha256'], 'a' * 64)
            self.assertEqual(result['ota']['target']['payload_compression'], 'zstd')
            self.assertEqual(set(result['ota']['requires']), {'artifact.mender-v3', 'delta.hdiffpatch-v1', 'payload.gzip', 'payload.zstd'})
            self.assertEqual(result['sha256'], metadata.digest(patch))
            with self.assertRaises(ValueError):
                metadata.inspect_delta(patch, 'unu-mdb', old_info, new_info, 'xdelta3')
            with self.assertRaises(ValueError):
                metadata.inspect_full(new, 'v1.4.3', 'unu-dbc')
            old_info['rootfs_sha256'] = 'c' * 64
            with self.assertRaises(ValueError):
                metadata.inspect_delta(patch, 'unu-mdb', old_info, new_info, 'hdiffpatch')


if __name__ == '__main__':
    unittest.main()
