"""Offline release changelog tests with mocked GitHub and Git responses."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/workflows/scripts/changelog.sh'


class ChangelogTests(unittest.TestCase):
    def test_env_values_ignore_version_comments(self):
        parser = SCRIPT.read_text().split('parse_env_var() {', 1)[1].split('parse_env_prefix_keys() {', 1)[0]
        parser = 'parse_env_var() {' + parser
        cases = [
            ('KEY="abc123" # v1.2.3\n', 'abc123'),
            ('  KEY="abc123"\r\n', 'abc123'),
            ('KEY=abc123 # release\n', 'abc123'),
            ('KEY="" # AUTOREV\n', ''),
            ('KEY=\n', ''),
            ('UNRELATED="value"\n', ''),
            ('KEY="$(touch unexpected)" # inert text\n', '$(touch unexpected)'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / 'pins.env'
            for content, expected in cases:
                with self.subTest(content=content):
                    env_file.write_text(content)
                    result = subprocess.run(
                        ['bash', '-euc', parser + '\nparse_env_var "$1" KEY', 'test', str(env_file)],
                        cwd=tmp, text=True, capture_output=True, check=True)
                    self.assertEqual(result.stdout.rstrip('\n'), expected)
                    self.assertFalse((Path(tmp) / 'unexpected').exists())

    def test_pinned_comparisons_with_inline_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            tools = work / 'bin'
            tools.mkdir()
            old_meta, new_meta = 'a' * 40, 'b' * 40
            old_battery, new_battery = 'c' * 40, 'd' * 40
            unchanged = 'e' * 40
            def pins(meta, battery):
                return (f'LAYER_VERSION_meta_librescoot="{meta}" # v1.5.0\n'
                        f'SRCREV_battery_service="{battery}" # v0.7.0\n'
                        f'SRCREV_radio_gaga="{unchanged}" # v0.6.0\n')
            (work / 'previous.env').write_text(pins(old_meta, old_battery))
            (work / 'stable.env').write_text(pins(new_meta, new_battery))
            (tools / 'git').write_text('#!/bin/sh\nif [ "$1" = show ]; then cat "$OLD_ENV"; fi\n')
            (tools / 'curl').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
url = sys.argv[-1]
with open(os.environ['URL_LOG'], 'a') as log:
    log.write(json.dumps(url) + '\\n')
if any(c in url for c in ' "#\\r\\n'):
    sys.exit(3)
if '/releases?' in url:
    body = [{'tag_name':'testing-previous', 'prerelease':True, 'published_at':'2026-10-16T06:51:18Z'}]
elif '/compare/' in url:
    body = {'commits':[{'sha':'f'*40, 'html_url':'https://example.org/commit', 'commit':{'message':'example change'}}]}
else:
    body = []
if '-o' in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(body))
    print('200', end='')
else:
    print(json.dumps(body))
''')
            for tool in tools.iterdir():
                tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                   'CHANNEL': 'testing', 'CURRENT_SHA': '1' * 40,
                   'UNTIL_ISO': '2026-10-19T21:27:29Z', 'REPO': 'librescoot/librescoot',
                   'GITHUB_TOKEN': 'test-token', 'GITHUB_OUTPUT': str(work / 'output'),
                   'OLD_ENV': str(work / 'previous.env'), 'URL_LOG': str(work / 'urls')}
            result = subprocess.run(['bash', str(SCRIPT)], cwd=work, env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            urls = [json.loads(line) for line in (work / 'urls').read_text().splitlines()]
            comparisons = [url for url in urls if '/compare/' in url]
            self.assertEqual(comparisons, [
                'https://api.github.com/repos/librescoot/librescoot/compare/testing-previous...' + '1' * 40,
                f'https://api.github.com/repos/librescoot/meta-librescoot/compare/{old_meta}...{new_meta}',
                f'https://api.github.com/repos/librescoot/battery-service/compare/{old_battery}...{new_battery}',
            ])
            output = (work / 'output').read_text()
            self.assertIn('### librescoot/meta-librescoot', output)
            self.assertIn('### librescoot/battery-service', output)
            self.assertNotIn('### rescoot/radio-gaga', output)
            self.assertIn('has_changes=true', output)
