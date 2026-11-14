import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/workflows/scripts/verify-ota-feed-bridges.py'
spec = importlib.util.spec_from_file_location('verify_ota_feed_bridges', SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
TAGS = {'stable': 'v1.4.3', 'testing': 'testing-20261115T100000', 'nightly': 'nightly-20261115T100000'}


def item(tag):
    return {'tag_name': tag, 'assets': [{'name': f'librescoot-unu-{board}-{tag}.mender', 'sha256': 'a' * 64}
                                        for board in ('mdb', 'dbc')]}


class FeedBridgeGuardTest(unittest.TestCase):
    def setUp(self):
        self.legacy = {channel: item(tag) for channel, tag in TAGS.items()}
        self.bridge = {'version': 1, 'bridges': copy.deepcopy(self.legacy)}
        self.v2 = {channel: {'tag_name': f'future-{channel}'} for channel in TAGS}

    def test_matching_live_indexes_pass(self):
        self.assertEqual(verify.verify(self.legacy, self.v2, self.bridge, 'testing-20261116T100000'), TAGS)

    def test_never_recompress_any_bridge(self):
        for tag in TAGS.values():
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                verify.verify(self.legacy, self.v2, self.bridge, tag)

    def test_unpinned_missing_or_inconsistent_feeds_fail_closed(self):
        cases = []
        old = copy.deepcopy(self.legacy); old['stable']['tag_name'] = 'v1.4.4'; cases.append((old, self.v2, self.bridge))
        missing = copy.deepcopy(self.v2); missing.pop('testing'); cases.append((self.legacy, missing, self.bridge))
        broken = copy.deepcopy(self.bridge); broken['bridges']['nightly']['assets'].pop(); cases.append((self.legacy, self.v2, broken))
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                verify.verify(*args, 'nightly-20261116T100000')


if __name__ == '__main__':
    unittest.main()
