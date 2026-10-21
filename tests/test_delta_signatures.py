"""Regression tests for opaque signature metadata in delta generation."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'mender-delta-create.py'
spec = importlib.util.spec_from_file_location('delta_create', SCRIPT)
delta_create = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta_create)


def artifact(path, signature):
    files = {'version': b'{"format":"mender","version":3}',
             'manifest': b'manifest', 'header.tar.gz': b'header',
             'data/0000.tar.gz': b'unchanged-payload'}
    if signature is not None:
        files['manifest.sig'] = signature
    with tarfile.open(path, 'w') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


class DeltaSignatures(unittest.TestCase):
    def test_signature_transitions(self):
        for old_sig, new_sig in [(None, b'first'), (b'first', b'next'),
                                 (b'same', b'same'), (b'old', None), (None, None)]:
            with self.subTest(old=old_sig, new=new_sig), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                old, new, delta = (root / n for n in ('old.mender', 'new.mender', 'out.delta'))
                artifact(old, old_sig)
                artifact(new, new_sig)
                with patch.object(delta_create, 'get_artifact_name', return_value='test'), \
                     patch.object(delta_create, 'get_payload_checksum', return_value='checksum'), \
                     patch.object(delta_create, 'create_xdelta_patch') as xdelta, \
                     contextlib.redirect_stdout(io.StringIO()):
                    delta_create.create_delta_patch(old, new, delta)
                xdelta.assert_not_called()
                with tarfile.open(delta, 'r:gz') as archive:
                    self.assertEqual(archive.getnames()[0], './metadata.json')
                    metadata = json.load(archive.extractfile('./metadata.json'))
                    changes = metadata['changes']
                    for name in ('version', 'manifest', 'header.tar.gz'):
                        self.assertEqual(changes[name], {'type': 'new'})
                    if new_sig is not None:
                        self.assertEqual(changes['manifest.sig'], {'type': 'new'})
                        self.assertEqual(archive.extractfile('./new_files/manifest.sig').read(), new_sig)
                    elif old_sig is not None:
                        self.assertEqual(changes['manifest.sig'], {'type': 'deleted'})
                    else:
                        self.assertNotIn('manifest.sig', changes)


if __name__ == '__main__':
    unittest.main()
