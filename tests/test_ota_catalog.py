import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ota_catalog import inspect_artifact
spec = importlib.util.spec_from_file_location('cross', ROOT / '.github/workflows/scripts/cross-channel-deltas.py')
cross = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cross)


def tar_bytes(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


class CatalogTests(unittest.TestCase):
    def test_identity_survives_container_change(self):
        header = gzip.compress(tar_bytes({'header-info': json.dumps(dict(
            artifact_provides=dict(artifact_name='release-v1.4.1'),
            artifact_depends=dict(device_type=['unu-mdb']))).encode()}), mtime=0)
        payload = tar_bytes({'rootfs.ext4': b'rootfs'})
        root = hashlib.sha256(b'rootfs').hexdigest()
        files = {'version': b'{"version":3}', 'manifest': f'{root}  data/0000/rootfs.ext4\n'.encode(),
                 'header.tar.gz': header, 'data/0000.tar.gz': gzip.compress(payload, mtime=0)}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'image.mender'
            path.write_bytes(tar_bytes(files))
            a = inspect_artifact(path, 'unu-mdb', 'v1.4.1', 'https://example/image.mender')
            files['data/0000.tar.gz'] = gzip.compress(payload, mtime=123)
            path.write_bytes(tar_bytes(files))
            b = inspect_artifact(path, 'unu-mdb', 'v1.4.1', 'https://example/image.mender')
            self.assertEqual(a['id'], b['id'])
            self.assertEqual(a['payload_tar_sha256'], b['payload_tar_sha256'])
            self.assertNotEqual(a['full']['sha256'], b['full']['sha256'])
            with self.assertRaises(ValueError):
                inspect_artifact(path, 'unu-dbc', 'v1.4.1', 'https://example/image.mender')

    def test_real_cross_channel_delta_reconstructs(self):
        import shutil
        if not shutil.which('xdelta3'):
            self.skipTest('xdelta3 not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for version, data in [('v1.4.1', b'a' * 8192), ('testing-20261105T120000', b'a' * 4096 + b'b' * 4096)]:
                checksum = hashlib.sha256(data).hexdigest()
                header = gzip.compress(tar_bytes({
                    'header-info': json.dumps(dict(artifact_provides=dict(artifact_name='release-' + version),
                        artifact_depends=dict(device_type=['unu-mdb']))).encode(),
                    'headers/0000/type-info': json.dumps(dict(artifact_provides={'rootfs-image.checksum': checksum})).encode(),
                }), mtime=0)
                files = {'version': b'{"version":3}', 'manifest': f'{checksum}  data/0000/rootfs.ext4\n'.encode(),
                         'manifest.sig': b'test signature', 'header.tar.gz': header,
                         'data/0000.tar.gz': gzip.compress(tar_bytes({'rootfs.ext4': data}), mtime=0)}
                path = root / (version + '.mender')
                path.write_bytes(tar_bytes(files))
                paths.append(path)
            spec = importlib.util.spec_from_file_location('delta', ROOT / 'mender-delta-create.py')
            creator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(creator)
            delta = root / 'edge.delta'
            creator.create_delta_patch(str(paths[0]), str(paths[1]), str(delta))
            cross.verify_patch(paths[0], paths[1], delta)
            old = inspect_artifact(paths[0], 'unu-mdb', 'v1.4.1', 'https://example/old.mender')
            new = inspect_artifact(paths[1], 'unu-mdb', 'testing-20261105T120000', 'https://example/new.mender')
            self.assertNotEqual(old['id'], new['id'])

    def test_source_matrix(self):
        def release(tag, pre):
            return dict(tag_name=tag, prerelease=pre, draft=False, published_at=tag)
        releases = [release('v1.4.0', False), release('v1.4.1', False), release('v1.3.0', False),
                    release('testing-20261105T120000', True), release('testing-20261104T120000', True)]
        self.assertEqual([r['tag_name'] for r in cross.select_sources(releases, 'testing', 'x')],
                         ['v1.4.1', 'testing-20261105T120000'])
        self.assertEqual(len(cross.select_sources(releases, 'stable', 'v1.4.2')), 3)


if __name__ == '__main__':
    unittest.main()
