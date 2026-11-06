"""Keep experimental HDiff metadata separate from legacy xdelta assets."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'mender-delta-create.py'
spec = importlib.util.spec_from_file_location('delta_create', SCRIPT)
creator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creator)


def artifact(path, payload):
    with tarfile.open(path, 'w') as archive:
        for name, data in {'version': b'v', 'manifest': b'm', 'header.tar.gz': b'h',
                           'data/0000.tar.gz': payload}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


class HDiffDeltaTest(unittest.TestCase):
    def test_explicit_algorithm_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new, out = (root / n for n in ('old.mender', 'new.mender', 'out.delta'))
            artifact(old, b'old'); artifact(new, b'new')
            def run(args, **kwargs):
                self.assertEqual(args[:4], ['hdiffz', '-m-4', '-p-2', '-c-zstd-20'])
                Path(args[-1]).write_bytes(b'encoded')
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(creator, 'get_artifact_name', return_value='test'), \
                 patch.object(creator, 'get_payload_checksum', return_value='checksum'), \
                 patch.object(creator.subprocess, 'run', side_effect=run), \
                 contextlib.redirect_stdout(io.StringIO()):
                creator.create_delta_patch(old, new, out, 'hdiffpatch')
            with tarfile.open(out, 'r:gz') as archive:
                metadata = json.load(archive.extractfile('./metadata.json'))
                change = metadata['changes']['data/0000.tar.gz']
                self.assertEqual(change['algorithm'], 'hdiffpatch')
                self.assertEqual(change['patch'], 'data_0000.tar.gz.hdiff')
                self.assertEqual(archive.extractfile('./patches/' + change['patch']).read(), b'encoded')

    def test_unknown_algorithm_fails(self):
        with self.assertRaises(ValueError):
            creator.create_delta_patch('old', 'new', 'out', 'unknown')


if __name__ == '__main__':
    unittest.main()
