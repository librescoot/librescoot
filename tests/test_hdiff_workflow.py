"""Ensure experimental nightlies preserve the legacy update path."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class HDiffWorkflowTest(unittest.TestCase):
    def test_nightly_has_both_delta_formats(self):
        workflow = yaml.load((ROOT / '.github/workflows/build.yml').read_text(), Loader=yaml.BaseLoader)
        job = workflow['jobs']['create-release']
        steps = job['steps']
        install = next(s for s in steps if s.get('name') == 'Install HDiffPatch encoder')
        self.assertEqual(install['if'], "needs.prepare.outputs.channel == 'nightly'")
        self.assertIn('628963bf2ee9108a97260fa5eef44acd9ec94369b76090a957c9182b3abbb558', install['run'])
        create = next(s for s in steps if s.get('name') == 'Create delta patches')['run']
        self.assertIn('"$OUTPUT_DELTA"', create)
        self.assertIn('"$OUTPUT_HDIFF" --hdiffpatch', create)
        self.assertIn('needs.prepare.outputs.channel', create)
        self.assertIn('refs/heads/feat/hdiffpatch', job['if'])
        self.assertIn("inputs.meta_librescoot_branch == 'feat/hdiffpatch'", job['if'])
        self.assertIn('target_commitish', next(s for s in steps if s.get('name') == 'Create Github release')['with'])


if __name__ == '__main__':
    unittest.main()
