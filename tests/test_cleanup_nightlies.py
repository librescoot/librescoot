import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / '.github/workflows/scripts/cleanup-nightlies.py'
spec = importlib.util.spec_from_file_location('cleanup_nightlies', path)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)

PIN = 'nightly-20261115T100000'


def bridge():
    return {'tag_name': PIN, 'draft': False, 'prerelease': True,
            'assets': [{'name': f'librescoot-unu-{board}-{PIN}.mender', 'size': 100,
                        'digest': 'sha256:' + 'a' * 64} for board in ('mdb', 'dbc')]}


def release(tag, **changes):
    return {'tag_name': tag, 'draft': False, 'prerelease': True, 'target_commitish': 'wrynose', **changes}


class CleanupTests(unittest.TestCase):
    def test_retains_latest_and_exact_bridge(self):
        releases = [release(f'nightly-202612{i:02d}T100000') for i in range(1, 6)]
        releases.extend([release(PIN), release('nightly-20261001T100000')])
        self.assertEqual(cleanup.plan(releases, bridge(), PIN, keep_latest=3),
                         ['nightly-20261204T100000', 'nightly-20261205T100000', 'nightly-20261001T100000'])

    def test_bridge_may_be_outside_api_page(self):
        releases = [release('nightly-20261201T100000'), release('nightly-20261001T100000')]
        self.assertEqual(cleanup.plan(releases, bridge(), PIN, keep_latest=1), ['nightly-20261001T100000'])

    def test_invalid_or_missing_pin_never_produces_deletions(self):
        for bad in ('', 'testing-20261115T100000', '../nightly', 'nightly-20261115'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cleanup.plan([release('nightly-old')], bridge(), bad, keep_latest=0)
        for change in ({'draft': True}, {'prerelease': False}, {'tag_name': 'nightly-other'}, {'assets': []}):
            broken = copy.deepcopy(bridge()); broken.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                cleanup.plan([release('nightly-old')], broken, PIN, keep_latest=0)
        broken = bridge(); broken['assets'][0]['digest'] = None
        with self.assertRaises(ValueError):
            cleanup.plan([], broken, PIN)

    def test_never_deletes_stable_testing_draft_or_other_branch(self):
        releases = [release('v1.4.3', prerelease=False), release('testing-20261115T100000'),
                    release('nightly-draft', draft=True), release('nightly-other', target_commitish='other'),
                    release('nightly-old')]
        self.assertEqual(cleanup.plan(releases, bridge(), PIN, keep_latest=0), ['nightly-old'])

    def test_rejects_unsafe_or_duplicate_candidate_tags(self):
        for releases in ([release('-nightly')], [release('nightly-same'), release('nightly-same')]):
            with self.subTest(releases=releases), self.assertRaises(ValueError):
                cleanup.plan(releases, bridge(), PIN, keep_latest=0)


if __name__ == '__main__':
    unittest.main()
