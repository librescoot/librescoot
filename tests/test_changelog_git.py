"""Pinned changelog regressions using real Git and an offline GitHub fixture."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/workflows/scripts/changelog.sh'
GIT = shutil.which('git')


class ChangelogGitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        self.env = {
            **os.environ,
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TEST_ASSUME_DIFFERENT_OWNER': '1',
            'GIT_AUTHOR_NAME': 'Release Test',
            'GIT_AUTHOR_EMAIL': 'release@example.org',
            'GIT_COMMITTER_NAME': 'Release Test',
            'GIT_COMMITTER_EMAIL': 'release@example.org',
            'CHANNEL': 'testing',
            'CURRENT_TAG': 'testing-current',
            'CURRENT_SHA': '1' * 40,
            'UNTIL_ISO': '2026-11-12T01:34:25Z',
            'REPO': 'librescoot/librescoot',
            'GITHUB_TOKEN': 'test-token',
            'GITHUB_OUTPUT': str(self.work / 'output'),
            'URL_LOG': str(self.work / 'urls'),
        }
        self.git('init', '-q')
        self.git('remote', 'add', 'origin', str(self.work / 'missing-remote'))
        self.old_sha, self.new_sha = 'a' * 40, 'b' * 40
        self.write_pins(self.old_sha)
        self.git('add', 'stable.env')
        self.git('commit', '-qm', 'previous pins')
        self.git('tag', 'testing-previous')
        self.write_pins(self.new_sha)
        tools = self.work / 'bin'
        tools.mkdir()
        curl = tools / 'curl'
        curl.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
url = sys.argv[-1]
with open(os.environ['URL_LOG'], 'a') as log:
    log.write(json.dumps(url) + '\\n')
if '/releases?' in url:
    body = [] if os.environ.get('FIRST_RELEASE') else [
        {'tag_name': 'testing-previous', 'prerelease': True, 'draft': False,
         'published_at': '2026-11-11T15:18:05Z'}]
elif '/compare/' in url:
    body = {'commits': [{'sha': 'f' * 40, 'html_url': 'https://example.org/commit',
                         'commit': {'message': 'reconnect recovery'}}]}
elif '/redis-ipc/commits?' in url and os.environ.get('DEPENDENCY_ACTIVITY'):
    body = [{'sha': 'e' * 40, 'html_url': 'https://example.org/dependency',
             'commit': {'message': 'dependency activity'}}]
else:
    body = []
if '-o' in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_text(json.dumps(body))
    print('200', end='')
else:
    print(json.dumps(body))
''')
        curl.chmod(0o755)
        self.env['PATH'] = str(tools) + os.pathsep + self.env['PATH']

    def git(self, *args):
        return subprocess.run(
            [GIT, '-c', 'safe.directory=' + str(self.work), *args],
            cwd=self.work, env=self.env, text=True, capture_output=True, check=True,
        )

    def write_pins(self, sha):
        (self.work / 'stable.env').write_text(f'SRCREV_ecu_service="{sha}" # v0.11.1\n')

    def run_changelog(self):
        return subprocess.run(['bash', str(SCRIPT)], cwd=self.work, env=self.env,
                              text=True, capture_output=True)

    def test_container_ownership_does_not_hide_commit_delta(self):
        plain = subprocess.run([GIT, 'show', 'testing-previous:stable.env'],
                               cwd=self.work, env=self.env, text=True, capture_output=True)
        self.assertNotEqual(plain.returncode, 0)
        self.assertIn('dubious ownership', plain.stderr)
        result = self.run_changelog()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.work / 'output').read_text()
        self.assertIn('reconnect recovery', output)
        self.assertNotIn('Initial pinned revisions', output)
        urls = [json.loads(line) for line in (self.work / 'urls').read_text().splitlines()]
        self.assertIn(f'https://api.github.com/repos/librescoot/ecu-service/compare/{self.old_sha}...{self.new_sha}', urls)
        self.assertFalse((self.work / '.gitconfig').exists())

    def test_missing_previous_pins_fail_instead_of_claiming_first_release(self):
        self.git('rm', '--cached', 'stable.env')
        self.git('commit', '-qm', 'no pins in previous release')
        self.git('tag', '-f', 'testing-previous')
        result = self.run_changelog()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stable.env', result.stderr)
        self.assertNotIn('treating as first release', result.stderr)
        self.assertFalse((self.work / 'output').exists())

    def test_missing_previous_tag_fetch_error_is_visible(self):
        self.git('tag', '-d', 'testing-previous')
        result = self.run_changelog()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing-remote', result.stderr)
        self.assertFalse((self.work / 'output').exists())

    def test_previous_tag_can_be_fetched_with_scoped_trust(self):
        self.env.pop('GIT_TEST_ASSUME_DIFFERENT_OWNER')
        remote = self.work / 'remote.git'
        self.git('clone', '--bare', str(self.work), str(remote))
        self.git('remote', 'set-url', 'origin', str(remote))
        self.git('tag', '-d', 'testing-previous')
        result = self.run_changelog()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('reconnect recovery', (self.work / 'output').read_text())
        self.assertEqual(self.git('rev-parse', '--verify', 'testing-previous').returncode, 0)

    def test_all_pins_are_mapped_and_excluded_from_dependency_activity(self):
        script = SCRIPT.read_text()
        mapping = dict(re.findall(r'\[(SRCREV_\w+)\]="([^"]+)"', script))
        pins = set(re.findall(r'^(SRCREV_\w+)=', (ROOT / 'stable.env').read_text(), re.M))
        self.assertEqual(set(mapping), pins)
        activity = script.split('DEPENDENCY_ACTIVITY_REPOS=(', 1)[1].split(')', 1)[0]
        self.assertFalse(set(re.findall(r'"([^"]+)"', activity)) & set(mapping.values()))

    def test_dependency_activity_does_not_claim_floating_image_revisions(self):
        self.env['DEPENDENCY_ACTIVITY'] = '1'
        result = self.run_changelog()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.work / 'output').read_text()
        self.assertIn('## Dependency repository activity', output)
        self.assertIn('dependency activity', output)
        self.assertNotIn('track latest at build time', output)

    def test_genuine_first_release_still_lists_pins(self):
        self.env['FIRST_RELEASE'] = '1'
        result = self.run_changelog()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Initial pinned revisions', (self.work / 'output').read_text())


if __name__ == '__main__':
    unittest.main()
