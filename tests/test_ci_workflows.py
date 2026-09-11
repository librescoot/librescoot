"""Offline CI contract tests. Run: python3 -m unittest discover -s tests (PyYAML required)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    # YAML 1.1's boolean resolver otherwise interprets GitHub's `on` as True.
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def shell(script, cwd, **env):
    return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=cwd,
                          env={**os.environ, **env}, text=True, capture_output=True, check=True)


class WorkflowTests(unittest.TestCase):
    def test_run_name_categories(self):
        run_name = workflow('build.yml')['run-name']
        normalized = ' '.join(run_name.split())
        expected = (
            "${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.channel == 'nightly' "
            "&& inputs.meta_librescoot_branch != '' "
            "&& inputs.meta_librescoot_branch != 'wrynose' "
            "&& format('Custom build: {0} (meta: {1})', inputs.channel, "
            "inputs.meta_librescoot_branch) "
            "|| github.event_name == 'workflow_dispatch' "
            "&& format('Manual build: {0}{1}', inputs.channel || 'nightly', "
            "inputs.meta_librescoot_branch != '' "
            "&& format(' (meta: {0})', inputs.meta_librescoot_branch) || '') "
            "|| github.event_name == 'schedule' && 'Scheduled build: nightly' "
            "|| format('Build {0}', github.ref_name) }}"
        )
        self.assertEqual(normalized, expected)

    def test_release_and_minimal_targets(self):
        release = workflow('build.yml')
        minimal = workflow('build-minimal.yml')
        shared = workflow('build-firmware.yml')
        self.assertEqual(set(release['jobs']), {'prepare', 'build', 'create-release'})
        self.assertEqual(set(release['on']), {'schedule', 'push', 'workflow_dispatch'})
        self.assertNotIn('minimal_only', release['on']['workflow_dispatch']['inputs'])
        self.assertEqual(set(minimal['on']), {'workflow_dispatch'})
        self.assertEqual(set(minimal['jobs']), {'prepare', 'build'})
        self.assertEqual(minimal['permissions'], {'contents': 'read'})
        self.assertEqual(set(shared['on']), {'workflow_call'})
        for data, targets in [(release, ['mdb', 'dbc']),
                              (minimal, ['mdb-minimal', 'dbc-minimal'])]:
            build = data['jobs']['build']
            self.assertEqual(build['uses'], './.github/workflows/build-firmware.yml')
            self.assertEqual([v['target'] for v in build['strategy']['matrix']['include']], targets)

    def test_version_channels(self):
        steps = workflow('build.yml')['jobs']['prepare']['steps']
        script = next(s['run'] for s in steps if s.get('id') == 'set-version')
        timestamp = '20260102T030405'
        cases = [
            ('refs/heads/wrynose', '', '', f'nightly-{timestamp}', 'nightly', 'true'),
            ('refs/heads/wrynose', 'nightly', 'wrynose', f'nightly-{timestamp}', 'nightly', 'true'),
            ('refs/heads/wrynose', 'testing', '', f'testing-{timestamp}', 'testing', 'true'),
            ('refs/heads/wrynose', 'nightly', 'test/branch', f'custom-nightly-{timestamp}-test-branch', 'nightly', 'true'),
            ('refs/tags/v1.3.2', '', '', 'v1.3.2', 'stable', 'false'),
        ]
        for ref, channel, branch, version, expected_channel, prerelease in cases:
            with self.subTest(ref=ref, channel=channel, branch=branch), tempfile.TemporaryDirectory() as tmp:
                rendered = script
                for key, value in {'steps.set-timestamp.outputs.timestamp': timestamp,
                                   'github.ref': ref, 'inputs.channel': channel,
                                   'inputs.meta_librescoot_branch': branch}.items():
                    rendered = rendered.replace('${{ ' + key + ' }}', value)
                output = Path(tmp) / 'output'
                shell(rendered, tmp, GITHUB_REF=ref, GITHUB_OUTPUT=str(output))
                values = dict(line.split('=', 1) for line in output.read_text().splitlines())
                self.assertEqual(values, {'version': version, 'tag': version,
                                          'channel': expected_channel, 'prerelease': prerelease})

    def test_change_gate(self):
        steps = workflow('build.yml')['jobs']['prepare']['steps']
        script = next(s['run'] for s in steps if s.get('id') == 'check')
        for event, ref, response, expected in [
            ('schedule', 'refs/heads/wrynose', '[]', 'false'),
            ('schedule', 'refs/heads/wrynose', '[{}]', 'true'),
            ('workflow_dispatch', 'refs/heads/wrynose', '[]', 'true'),
            ('push', 'refs/tags/v1.3.2', '[]', 'true'),
        ]:
            with self.subTest(event=event, response=response), tempfile.TemporaryDirectory() as tmp:
                rendered = script.replace('${{ github.event_name }}', event).replace('${{ github.ref }}', ref)
                output = Path(tmp) / 'output'
                shell('curl() { printf "%s" "$RESPONSE"; };\n' + rendered,
                      tmp, RESPONSE=response, GITHUB_OUTPUT=str(output))
                self.assertEqual(output.read_text().strip(), f'has_changes={expected}')

    def test_xdelta_install_is_idempotent_and_bounded(self):
        steps = workflow('build.yml')['jobs']['create-release']['steps']
        script = next(s['run'] for s in steps if s['name'] == 'Install xdelta3')
        prelude = '''
command() {
    if [ "$1" = -v ] && [ "$2" = xdelta3 ]; then
        return "$XDELTA_STATUS"
    fi
    builtin command "$@"
}
sudo() {
    printf '%s\\n' "$*" >> "$CALLS"
    case "$*" in
        *" install "*) return "${INSTALL_STATUS:-0}" ;;
    esac
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / 'calls'
            shell(prelude + script, tmp, XDELTA_STATUS='0', CALLS=str(calls))
            self.assertFalse(calls.exists())

        expected_calls = [
            'apt-get update',
            'env DEBIAN_FRONTEND=noninteractive apt-get -o '
            'DPkg::Lock::Timeout=300 install -y xdelta3',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / 'calls'
            shell(prelude + script, tmp, XDELTA_STATUS='1', CALLS=str(calls))
            self.assertEqual(calls.read_text().splitlines(), expected_calls)

        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / 'calls'
            result = subprocess.run(
                ['bash', '-e', '-o', 'pipefail', '-c', prelude + script], cwd=tmp,
                env={**os.environ, 'XDELTA_STATUS': '1', 'INSTALL_STATUS': '100',
                     'CALLS': str(calls)}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 100)
            self.assertEqual(calls.read_text().splitlines(), expected_calls)

    @unittest.skipUnless(shutil.which('pigz'), 'pigz required')
    def test_artifact_packaging(self):
        steps = workflow('build-firmware.yml')['jobs']['build']['steps']
        script = next(s['run'] for s in steps if s['name'] == 'Prepare artifacts')
        for target in ['mdb', 'dbc', 'mdb-minimal', 'dbc-minimal']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                board = target.split('-')[0]
                deploy = Path(tmp) / f'yocto/build/tmp/deploy/images/unu-{board}'
                deploy.mkdir(parents=True)
                stem = f'librescoot-{target}-image-unu-{board}-test'
                image = b'firmware-test\0' * 8192
                (deploy / f'{stem}.sdimg').write_bytes(image)
                (deploy / f'{stem}.sdimg.bmap').write_text('bmap')
                (deploy / f'{stem}.mender').write_text('mender')
                for boot in ['zImage', f'librescoot-{board}.dtb', 'u-boot-dtb.imx']:
                    (deploy / boot).write_text('boot')
                rendered = script
                for key, value in {'inputs.target': target, 'inputs.variant_id': f'unu-{target}',
                                   'inputs.version': 'test-version'}.items():
                    rendered = rendered.replace('${{ ' + key + ' }}', value)
                # Execute real packaging without privilege escalation or runner dependencies.
                shell('sudo() { "$@"; };\n' + rendered, tmp)
                artifacts = Path(tmp) / 'artifacts' / target
                prefix = f'librescoot-unu-{target}'
                names = {f'{prefix}-test-version.sdimg.gz', f'{prefix}-test-version.sdimg.bmap'}
                if not target.endswith('-minimal'):
                    names |= {f'{prefix}-test-version.mender', f'{prefix}-boot-test-version.tar.gz'}
                self.assertEqual({p.name for p in artifacts.iterdir()}, names)
                result = subprocess.run(['gzip', '-dc', str(artifacts / f'{prefix}-test-version.sdimg.gz')],
                                        capture_output=True, check=True)
                self.assertEqual(result.stdout, image)
                self.assertTrue((deploy / f'{stem}.sdimg').exists())
                self.assertFalse((deploy / f'{stem}.sdimg.gz').exists())

    def test_dashboard_build_does_not_clean(self):
        script = (ROOT / 'docker/entrypoint.sh').read_text().split('echo "Starting build process..."', 1)[1]
        for target, package, expected in [('dbc', '', 'librescoot-dbc-image --continue'),
                                           ('rpi4', '', 'librescoot-dbc-image --continue'),
                                           ('dbc', 'scootui-qt', 'scootui-qt --continue')]:
            with self.subTest(target=target, package=package), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'calls'
                shell('bitbake() { echo "$*" >> "$CALLS"; };\n' + script,
                      tmp, TARGET=target, PACKAGE=package, CALLS=str(output))
                self.assertEqual(output.read_text().strip(), expected)


if __name__ == '__main__':
    unittest.main()
