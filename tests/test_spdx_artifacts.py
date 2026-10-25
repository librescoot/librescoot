"""SPDX artifact collection and firmware workflow contracts."""
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/workflows/scripts/collect-spdx.py'
SPEC = importlib.util.spec_from_file_location('collect_spdx', SCRIPT)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)
DOCUMENT = {
    '@context': 'https://spdx.org/rdf/3.0.1/spdx-context.jsonld',
    '@graph': [
        {'type': 'SpdxDocument', '@id': 'urn:document'},
        {'type': 'software_Sbom', '@id': 'urn:sbom'},
        {'type': 'software_Package', '@id': 'urn:package', 'name': 'example'},
        {'type': 'simplelicensing_LicenseExpression', '@id': 'urn:license',
         'simplelicensing_licenseExpression': 'MIT'},
    ],
}


class SpdxArtifactTests(unittest.TestCase):
    def test_preserves_complete_document_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = json.dumps(DOCUMENT, indent=2).encode()
            timestamped = root / 'image-machine-20261025.spdx.json'
            timestamped.write_bytes(data)
            (root / 'image-machine.spdx.json').symlink_to(timestamped.name)
            first = root / 'artifacts/first.spdx.json.gz'
            second = root / 'artifacts/second.spdx.json.gz'
            for output in (first, second):
                COLLECTOR.collect(root, 'image-machine', output)
                self.assertEqual(gzip.decompress(output.read_bytes()), data)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(timestamped.read_bytes(), data)

    def test_rootfs_image_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'image-machine.rootfs.spdx.json').write_text(json.dumps(DOCUMENT))
            output = root / 'result.gz'
            COLLECTOR.collect(root, 'image-machine', output)
            self.assertEqual(json.loads(gzip.decompress(output.read_bytes())), DOCUMENT)

    def test_missing_or_incomplete_image_fails_before_creating_output(self):
        for document in (None, {}, {'@graph': [{'type': 'software_Package'}]}):
            with self.subTest(document=document), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if document is not None:
                    (root / 'image-machine.spdx.json').write_text(json.dumps(document))
                output = root / 'result.gz'
                with self.assertRaises(ValueError):
                    COLLECTOR.collect(root, 'image-machine', output)
                self.assertFalse(output.exists())

    def test_collects_each_workflow_target_before_upload(self):
        workflow = yaml.load((ROOT / '.github/workflows/build-firmware.yml').read_text(),
                             Loader=yaml.BaseLoader)
        steps = workflow['jobs']['build']['steps']
        names = [step['name'] for step in steps]
        self.assertLess(names.index('Prepare artifacts'), names.index('Collect SPDX SBOM'))
        self.assertLess(names.index('Collect SPDX SBOM'), names.index('Upload firmware artifacts'))
        script = next(step['run'] for step in steps if step['name'] == 'Collect SPDX SBOM')
        for target in ('mdb', 'dbc', 'mdb-minimal', 'dbc-minimal', 'rpi4'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                machine = 'librescoot-dbc-rpi4' if target == 'rpi4' else 'unu-' + target.split('-')[0]
                image_target = 'dbc' if target == 'rpi4' else target
                deploy = root / 'yocto/build/tmp/deploy/images' / machine
                deploy.mkdir(parents=True)
                (deploy / f'librescoot-{image_target}-image-{machine}.spdx.json').write_text(json.dumps(DOCUMENT))
                collector = root / SCRIPT.relative_to(ROOT)
                collector.parent.mkdir(parents=True)
                shutil.copyfile(SCRIPT, collector)
                rendered = script
                for key, value in {'inputs.target': target, 'inputs.variant_id': machine,
                                   'inputs.version': 'test-version'}.items():
                    rendered = rendered.replace('${{ ' + key + ' }}', value)
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', rendered], cwd=root,
                               check=True, capture_output=True, text=True)
                output = root / f'artifacts/{target}/librescoot-{machine}-test-version.spdx.json.gz'
                self.assertEqual(json.loads(gzip.decompress(output.read_bytes())), DOCUMENT)

    def test_release_upload_and_checksums_include_spdx(self):
        workflow = yaml.load((ROOT / '.github/workflows/build.yml').read_text(), Loader=yaml.BaseLoader)
        steps = workflow['jobs']['create-release']['steps']
        upload = next(step for step in steps if step['name'] == 'Create Github release')
        self.assertIn('artifacts/**/*', upload['with']['files'])
        script = next(step['run'] for step in steps if step['name'] == 'Generate SHA256SUMS')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / 'artifacts/board'
            artifacts.mkdir(parents=True)
            name = 'librescoot-unu-mdb-test.spdx.json.gz'
            (artifacts / name).write_bytes(gzip.compress(json.dumps(DOCUMENT).encode()))
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root,
                           check=True, capture_output=True, text=True)
            sums = (root / 'artifacts/SHA256SUMS').read_text()
            self.assertEqual(sums.split()[1], name)


if __name__ == '__main__':
    unittest.main()
