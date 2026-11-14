"""Verify payload-only recompression preserves signed Mender metadata."""
import gzip
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'mender-recompress-zstd.py'
spec = importlib.util.spec_from_file_location('recompress', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_artifact(path, entries):
    with tarfile.open(path, 'w') as archive:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


@unittest.skipUnless(shutil.which('zstd') and shutil.which('openssl'), 'needs zstd and openssl')
class RecompressTest(unittest.TestCase):
    def test_signed_manifest_and_header_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private, public = root / 'private.pem', root / 'public.pem'
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(private)],
                           check=True, stderr=subprocess.DEVNULL)
            subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)],
                           check=True, stdout=subprocess.DEVNULL)
            manifest = b'fixed Mender manifest\n'
            (root / 'manifest').write_bytes(manifest)
            subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(private), '-in',
                            str(root / 'manifest'), '-out', str(root / 'signature')], check=True)
            signature = (root / 'signature').read_bytes()
            payload = b'realistic rootfs tar bytes ' * 10000
            entries = [('version', b'{"format":"mender","version":3}'),
                       ('manifest', manifest), ('manifest.sig', signature),
                       ('header.tar.gz', b'header bytes are immutable'),
                       ('data/0000.tar.gz', gzip.compress(payload, mtime=0))]
            source, target = root / 'input.mender', root / 'output.mender'
            write_artifact(source, entries)
            original = hashlib.sha256(source.read_bytes()).digest()
            module.recompress(source, target, level=3)
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original)
            with tarfile.open(target, 'r:') as result:
                self.assertEqual(result.getnames(), [n if n != module.SOURCE else module.TARGET for n, _ in entries])
                for name, data in entries[:-1]:
                    self.assertEqual(result.extractfile(name).read(), data)
                compressed = root / 'data.zst'
                compressed.write_bytes(result.extractfile(module.TARGET).read())
            decoded = subprocess.run(['zstd', '-d', '-q', '-c', str(compressed)], stdout=subprocess.PIPE, check=True).stdout
            self.assertEqual(decoded, payload)
            subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(public),
                            '-in', str(root / 'manifest'), '-sigfile', str(root / 'signature')],
                           check=True, stdout=subprocess.DEVNULL)

    @unittest.skipUnless(os.environ.get('MENDER_ARTIFACT'), 'set MENDER_ARTIFACT to run real signature verification')
    def test_real_signed_mender_artifact_still_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key, public = root / 'key.pem', root / 'public.pem'
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(key)],
                           check=True, stderr=subprocess.DEVNULL)
            subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(public)],
                           check=True, stdout=subprocess.DEVNULL)
            payload = root / 'rootfs.ext4'; payload.write_bytes(b'rootfs test data' * 10000)
            before, after = root / 'before.mender', root / 'after.mender'
            mender = os.environ['MENDER_ARTIFACT']
            subprocess.run([mender, 'write', 'rootfs-image', '--no-progress', '-n', 'release-v1.4.3',
                            '-c', 'unu-mdb', '-f', str(payload), '-k', str(key), '-o', str(before)],
                           check=True, stdout=subprocess.DEVNULL)
            module.recompress(before, after, level=3)
            for artifact in (before, after):
                subprocess.run([mender, 'read', '--no-progress', '-k', str(public), str(artifact)],
                               check=True, stdout=subprocess.DEVNULL)
            with tarfile.open(after, 'r:') as archive:
                self.assertIn('header.tar.gz', archive.getnames())
                self.assertIn('data/0000.tar.zst', archive.getnames())

    def test_rejects_invalid_or_duplicate_artifacts_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'input.mender'; output = root / 'out.mender'
            base = [('version', b'v'), ('manifest', b'm'), ('header.tar.gz', b'h')]
            for bad in [base, base + [(module.SOURCE, b'not gzip')],
                        base + [(module.SOURCE, gzip.compress(b'payload')), (module.SOURCE, b'duplicate')],
                        base + [(module.SOURCE, gzip.compress(b'payload')), (module.TARGET, b'duplicate')]]:
                write_artifact(source, bad)
                with self.assertRaises((ValueError, OSError, EOFError)):
                    module.recompress(source, output, level=3)
                self.assertFalse(output.exists())
            write_artifact(source, base + [(module.SOURCE, gzip.compress(b'payload'))])
            output.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                module.recompress(source, output, level=3)
            self.assertEqual(output.read_bytes(), b'keep')
            with self.assertRaises(ValueError):
                module.recompress(source, source)
            with self.assertRaises(ValueError):
                module.recompress(source, root / 'other', level=20)


if __name__ == '__main__':
    unittest.main()
