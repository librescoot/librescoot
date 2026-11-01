"""Offline pagination and previous release selection tests."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/workflows/scripts/previous-release.sh'


class DeltaReleaseSelectionTests(unittest.TestCase):
    def select(self, pages, channel='stable', current='v1.4.0'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pages.json').write_text(json.dumps(pages))
            curl = root / 'curl'
            curl.write_text('''#!/usr/bin/env python3
import json, os, sys
page = int(sys.argv[-1].split('page=')[-1])
entry = json.load(open(os.environ['PAGES']))[page - 1]
if entry == 'HTTP_ERROR': sys.exit(22)
print(json.dumps(entry))
''')
            curl.chmod(0o755)
            env = {**os.environ, 'PATH': tmp + os.pathsep + os.environ['PATH'],
                   'PAGES': str(root / 'pages.json'), 'REPO': 'owner/repo',
                   'CHANNEL': channel, 'CURRENT_TAG': current, 'GITHUB_TOKEN': 'test'}
            return subprocess.run(['bash', str(SCRIPT)], env=env, text=True, capture_output=True)

    def test_page_two_excludes_current_drafts_and_wrong_kind(self):
        for channel, prefix, prerelease, current in [('stable', 'v', False, 'v1.4.0'),
                ('testing', 'testing-', True, 'testing-current'), ('nightly', 'nightly-', True, 'nightly-current')]:
            with self.subTest(channel=channel):
                def release(tag, draft=False, pre=prerelease):
                    return dict(tag_name=tag, draft=draft, prerelease=pre)
                first = [release(current), release(prefix + 'withdrawn', True),
                         release(prefix + 'wrong', pre=not prerelease)] + [release('other')] * 97
                expected = release(prefix + 'previous')
                result = self.select([first, [expected]], channel, current)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

    def test_no_release(self):
        result = self.select([[dict(tag_name='v1.4.0', draft=False, prerelease=False)]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout))

    def test_page_two_errors_fail_closed(self):
        first = [dict(tag_name='nightly-x', draft=False, prerelease=True)] * 100
        for error in ['HTTP_ERROR', {'message': 'error'}, 'not json array']:
            with self.subTest(error=error):
                result = self.select([first, error])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
