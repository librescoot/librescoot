"""Compression changes must still produce a delta over the raw payload."""
import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'mender-delta-create.py'
spec = importlib.util.spec_from_file_location('delta_create_formats', SCRIPT)
creator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creator)


def artifact(path, payload, fmt):
    compressed = gzip.compress(payload, mtime=0) if fmt == 'gz' else subprocess.run(
        ['zstd', '-q', '-c'], input=payload, stdout=subprocess.PIPE, check=True).stdout
    with tarfile.open(path, 'w') as archive:
        for name, data in {'version': b'v', 'manifest': b'm', 'header.tar.gz': b'h',
                           f'data/0000.tar.{fmt}': compressed}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


@unittest.skipUnless(shutil.which('zstd') and shutil.which('xdelta3'), 'needs zstd and xdelta3')
class PayloadFormatTest(unittest.TestCase):
    def test_all_payload_format_transitions_are_raw_deltas(self):
        for oldfmt, newfmt in [('gz', 'gz'), ('gz', 'zst'), ('zst', 'gz'), ('zst', 'zst')]:
            for algorithm in ['xdelta3', 'hdiffpatch']:
                with self.subTest(old=oldfmt, new=newfmt, algorithm=algorithm), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    old, new, out = (root / name for name in ('old.mender', 'new.mender', 'out.delta'))
                    old_raw = b'unchanged rootfs data ' * 5000
                    new_raw = old_raw + b' changed content '
                    artifact(old, old_raw, oldfmt); artifact(new, new_raw, newfmt)
                    def fake_hdiff(args, **kwargs):
                        self.assertEqual(Path(args[-3]).read_bytes(), old_raw)
                        self.assertEqual(Path(args[-2]).read_bytes(), new_raw)
                        Path(args[-1]).write_bytes(b'encoded')
                        return subprocess.CompletedProcess(args, 0, '', '')
                    real_run = creator.subprocess.run
                    def run(args, **kwargs):
                        return fake_hdiff(args, **kwargs) if args[0] == 'hdiffz' else real_run(args, **kwargs)
                    with patch.object(creator, 'get_artifact_name', return_value='test'), \
                         patch.object(creator, 'get_payload_checksum', return_value='checksum'), \
                         patch.object(creator.subprocess, 'run', side_effect=run), \
                         contextlib.redirect_stdout(io.StringIO()):
                        creator.create_delta_patch(old, new, out, algorithm)
                    with tarfile.open(out, 'r:gz') as archive:
                        metadata = json.load(archive.extractfile('./metadata.json'))
                        changes = {k: v for k, v in metadata['changes'].items() if k.startswith('data/')}
                        self.assertEqual(list(changes), [f'data/0000.tar.{newfmt}'])
                        change = next(iter(changes.values()))
                        self.assertEqual(change['type'], 'modified')
                        self.assertTrue(change['old_meta']['compressed'])
                        self.assertTrue(change['new_meta']['compressed'])
                        self.assertEqual(change['old_meta']['decompressed_size'], len(old_raw))
                        self.assertEqual(change['new_meta']['decompressed_size'], len(new_raw))
                        patch_bytes = archive.extractfile('./patches/' + change['patch']).read()
                        if algorithm == 'xdelta3':
                            source = root / 'old-raw'; source.write_bytes(old_raw)
                            patch_path = root / 'payload.xdelta'; patch_path.write_bytes(patch_bytes)
                            result = subprocess.run(['xdelta3', '-d', '-c', '-s', str(source), str(patch_path)],
                                                    stdout=subprocess.PIPE, check=True)
                            self.assertEqual(result.stdout, new_raw)
                        else:
                            self.assertEqual(patch_bytes, b'encoded')

    @unittest.skipUnless(shutil.which('hdiffz') and shutil.which('hpatchz'), 'needs HDiffPatch tools')
    def test_real_hdiff_round_trip_across_compression_change(self):
        for oldfmt, newfmt in [('gz', 'zst'), ('zst', 'gz'), ('zst', 'zst')]:
            with self.subTest(old=oldfmt, new=newfmt), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                old, new, delta = (root / name for name in ('old.mender', 'new.mender', 'out.hdelta'))
                before = b'unchanged filesystem bytes ' * 5000
                after = before + b' updated bytes'
                artifact(old, before, oldfmt); artifact(new, after, newfmt)
                with patch.object(creator, 'get_artifact_name', return_value='test'), \
                     patch.object(creator, 'get_payload_checksum', return_value='checksum'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    creator.create_delta_patch(old, new, delta, 'hdiffpatch')
                with tarfile.open(delta, 'r:gz') as archive:
                    metadata = json.load(archive.extractfile('./metadata.json'))
                    change = metadata['changes'][f'data/0000.tar.{newfmt}']
                    patch_path = root / 'payload.hdiff'
                    patch_path.write_bytes(archive.extractfile('./patches/' + change['patch']).read())
                source = root / 'source'; source.write_bytes(before)
                result = root / 'result'
                subprocess.run(['hpatchz', str(source), str(patch_path), str(result)],
                               stdout=subprocess.DEVNULL, check=True)
                self.assertEqual(result.read_bytes(), after)

    def test_ambiguous_rootfs_members_are_rejected(self):
        with self.assertRaises(ValueError):
            creator.payload_paths({'data/0000.tar.gz': {}, 'data/0000.tar.zst': {}})

    def test_invalid_zstd_does_not_generate_an_uncompressed_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.tar.zst'; path.write_bytes(b'not zstd')
            with self.assertRaises(subprocess.CalledProcessError):
                creator.process_file_for_delta(str(path), tmp, 'bad')


if __name__ == '__main__':
    unittest.main()
