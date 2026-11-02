import pathlib
import subprocess
import tempfile
import unittest

ENTRYPOINT = pathlib.Path(__file__).resolve().parents[1] / "docker/entrypoint.sh"


class RadioReleaseVersionTest(unittest.TestCase):
    def test_override_is_optional_and_validated(self):
        text = ENTRYPOINT.read_text()
        block = text.split('# The radio release version', 1)[1].split('# Apply DISTRO_CODENAME', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / 'local.conf'
            block = '# The radio release version' + block.replace('/yocto/build/conf/local.conf', str(output))
            for version, success in [('', True), ('v1.2.3', True), ('v1.2.3-1-g123', False), ('v01.2.3', False)]:
                output.unlink(missing_ok=True)
                result = subprocess.run(['bash', '-c', block], env={'RADIO_GAGA_RELEASE_VERSION': version}, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, version)
                if version == 'v1.2.3':
                    self.assertEqual(output.read_text(), 'LIBRESCOOT_GO_RELEASE_VERSION:pn-radio-gaga = "v1.2.3"\n')
                else:
                    self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
