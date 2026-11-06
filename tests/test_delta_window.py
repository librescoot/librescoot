"""Source-window selection and actual VCDIFF compatibility."""
import importlib.util
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'mender-delta-create.py'
spec = importlib.util.spec_from_file_location('delta_create', SCRIPT)
delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta)


class DeltaWindowTests(unittest.TestCase):
    def test_selects_smaller_compressed_patch_not_raw_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / 'patch')
            def run(cmd, **kwargs):
                payload = b'x' * 10000 if '-B' in cmd else bytes(range(256)) * 4
                Path(cmd[-1]).write_bytes(payload)
                return subprocess.CompletedProcess(cmd, 0, '', '')
            with patch.object(delta.subprocess, 'run', side_effect=run):
                delta.create_xdelta_patch('old', 'new', out)
            self.assertEqual(Path(out).read_bytes(), b'x' * 10000)
            self.assertFalse(Path(out + '.large-window').exists())

    def test_keeps_default_when_smaller(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / 'patch')
            def run(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(os.urandom(2000) if '-B' in cmd else b'a' * 100)
                return subprocess.CompletedProcess(cmd, 0, '', '')
            with patch.object(delta.subprocess, 'run', side_effect=run):
                delta.create_xdelta_patch('old', 'new', out)
            self.assertEqual(Path(out).read_bytes(), b'a' * 100)

    def test_failure_does_not_silently_use_incomplete_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / 'patch')
            def run(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b'candidate')
                return subprocess.CompletedProcess(cmd, 1 if '-B' in cmd else 0, '', 'failed')
            with patch.object(delta.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(RuntimeError, 'failed'):
                    delta.create_xdelta_patch('old', 'new', out)
            self.assertFalse(Path(out + '.large-window').exists())

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
    def test_real_moved_source_reconstructs_with_normal_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new, encoded, result = (root / n for n in ('old', 'new', 'delta', 'result'))
            rng = random.Random(42)
            blocks = [rng.randbytes(1024 * 1024) for _ in range(3)]
            old.write_bytes(b''.join(blocks))
            new.write_bytes(blocks[2] + blocks[0] + blocks[1])
            with patch.object(delta, 'SOURCE_WINDOW_BYTES', 4 * 1024 * 1024):
                delta.create_xdelta_patch(str(old), str(new), str(encoded))
            subprocess.run(['xdelta3', '-d', '-s', str(old), str(encoded), str(result)], check=True)
            self.assertEqual(result.read_bytes(), new.read_bytes())


if __name__ == '__main__':
    unittest.main()
