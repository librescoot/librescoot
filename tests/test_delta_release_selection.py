import json
from pathlib import Path
import subprocess
import unittest


class DeltaReleaseSelectionTests(unittest.TestCase):
    def select(self, releases, prefix, prerelease):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/build.yml').read_text()
        line = next(line for line in workflow.splitlines() if 'PREV_RELEASE=$(' in line)
        expression = line.split('| jq -r "', 1)[1].rsplit('")', 1)[0]
        expression = expression.replace('${{ needs.prepare.outputs.prerelease }}', json.dumps(prerelease))
        expression = expression.replace('$PREFIX', prefix).replace('\\"', '"')
        return json.loads(subprocess.check_output(['jq', '-r', expression], input=json.dumps(releases), text=True))

    def test_ignore_withdrawn_drafts_in_every_channel(self):
        for prefix, prerelease in [('testing-', True), ('nightly-', True), ('v', False)]:
            with self.subTest(prefix=prefix):
                releases = [
                    dict(tag_name=prefix + 'new', draft=True, prerelease=prerelease),
                    dict(tag_name='unrelated', draft=False, prerelease=prerelease),
                    dict(tag_name=prefix + 'wrong-kind', draft=False, prerelease=not prerelease),
                    dict(tag_name=prefix + 'published', draft=False, prerelease=prerelease),
                    dict(tag_name=prefix + 'older', draft=False, prerelease=prerelease),
                ]
                self.assertEqual(self.select(releases, prefix, prerelease), releases[3])

    def test_only_drafts_has_no_delta_base(self):
        releases = [dict(tag_name='testing-withdrawn', draft=True, prerelease=True)]
        self.assertIsNone(self.select(releases, 'testing-', True))


if __name__ == '__main__':
    unittest.main()
