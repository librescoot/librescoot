"""Offline CI contract tests. Run: python3 -m unittest discover -s tests (PyYAML required)."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
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

    def test_nightly_release_pins_are_opt_in_and_reach_both_build_attempts(self):
        release = workflow('build.yml')
        option = release['on']['workflow_dispatch']['inputs']['use_release_pins']
        self.assertEqual(option['default'], 'false')
        self.assertEqual(release['jobs']['build']['with']['use_release_pins'],
                         '${{ inputs.use_release_pins || false }}')
        shared = workflow('build-firmware.yml')
        self.assertEqual(shared['on']['workflow_call']['inputs']['use_release_pins']['default'], 'false')
        scripts = [step['run'] for step in shared['jobs']['build']['steps']
                   if step.get('name') in ('Build firmware', 'Recover from pseudo abort and retry')]
        self.assertEqual(len(scripts), 2)
        self.assertTrue(all('USE_RELEASE_PINS="${{ inputs.use_release_pins }}"' in script for script in scripts))
        self.assertIn('-e USE_RELEASE_PINS="${USE_RELEASE_PINS}"', (ROOT / 'build.sh').read_text())
        entry = (ROOT / 'docker/entrypoint.sh').read_text()
        selection = entry.split('# Source environment file based on BUILD_CHANNEL', 1)[1].split(
            '# Save any LAYER_VERSION overrides', 1)[0]
        for channel, flag, expected in [('nightly', 'false', '/yocto/nightly.env'),
                                        ('nightly', 'true', '/opt/yocto-env/stable.env'),
                                        ('testing', 'false', '/yocto/stable.env'),
                                        ('stable', 'false', '/yocto/stable.env')]:
            with self.subTest(channel=channel, flag=flag), tempfile.TemporaryDirectory() as tmp:
                result = shell(selection + '\nprintf "%s" "$ENV_FILE"', tmp,
                               BUILD_CHANNEL=channel, USE_RELEASE_PINS=flag)
                self.assertTrue(result.stdout.endswith(expected), result.stdout)

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

    def test_release_uses_pinned_tools_image(self):
        release = workflow('build.yml')
        job = release['jobs']['create-release']
        self.assertRegex(job['container']['image'],
                         r'^ghcr\.io/librescoot/release-tools@sha256:[0-9a-f]{64}$')
        self.assertEqual(release['permissions']['packages'], 'read')
        self.assertEqual(job['defaults']['run']['shell'], 'bash')
        scripts = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertNotIn('apt-get', scripts)
        self.assertNotIn('hdiffpatch_v5.1.3_bin_linux64.zip', scripts)
        dockerfile = (ROOT / 'docker/release.Dockerfile').read_text()
        self.assertIn('xdelta3', dockerfile)
        self.assertIn('hdiffpatch_v5.1.3_bin_linux64.zip', dockerfile)
        self.assertIn('628963bf2ee9108a97260fa5eef44acd9ec94369b76090a957c9182b3abbb558', dockerfile)
        image_workflow = workflow('release-tools-image.yml')
        self.assertEqual(image_workflow['permissions']['packages'], 'write')
        build = next(step for step in image_workflow['jobs']['build']['steps']
                     if step.get('id') == 'image')
        self.assertEqual(build['with']['file'], 'docker/release.Dockerfile')
        self.assertIn('${{ github.sha }}', build['with']['tags'])

    def test_zstd_payload_is_guarded_and_keeps_one_mender_asset(self):
        steps = workflow('build.yml')['jobs']['create-release']['steps']
        position = next(i for i, step in enumerate(steps) if step.get('name') == 'Recompress full Mender payloads after bridge cutover')
        step = steps[position]
        self.assertEqual(step['if'], "${{ vars.OTA_ZSTD_PAYLOADS == 'true' }}")
        script = step['run']
        self.assertLess(script.index('verify-ota-feed-bridges.py'), script.index('mender-recompress-zstd.py'))
        self.assertIn('mv "${source}.zstd.tmp" "$source"', script)
        self.assertNotIn('.zmender', script)
        self.assertLess(position, next(i for i, item in enumerate(steps) if item.get('name') == 'Create delta patches'))
        self.assertLess(position, next(i for i, item in enumerate(steps) if item.get('name') == 'Generate SHA256SUMS'))

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
                # Only the boot asset the bundle carries. A kernel or DTB here is a
                # trap: U-Boot loads both from the rootfs slot, alongside the modules
                # that belong to them.
                (deploy / 'u-boot-dtb.imx').write_text('boot')
                (deploy / 'zImage').write_text('kernel')
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
                if not target.endswith('-minimal'):
                    with tarfile.open(artifacts / f'{prefix}-boot-test-version.tar.gz') as tar:
                        self.assertEqual(tar.getnames(), ['u-boot-dtb.imx'])
                result = subprocess.run(['gzip', '-dc', str(artifacts / f'{prefix}-test-version.sdimg.gz')],
                                        capture_output=True, check=True)
                self.assertEqual(result.stdout, image)
                self.assertTrue((deploy / f'{stem}.sdimg').exists())
                self.assertFalse((deploy / f'{stem}.sdimg.gz').exists())

    def test_pseudo_abort_recipe_detection(self):
        steps = workflow('build-firmware.yml')['jobs']['build']['steps']
        script = next(s['run'] for s in steps if s['name'] == 'Recover from pseudo abort and retry')
        detection = script.split('find yocto/build/tmp/work', 1)[0]
        cases = [
            ("ERROR: librescoot-mdb-image-1.0-r0 do_rootfs: abort()ing pseudo client\n", 'librescoot-mdb-image'),
            ("ERROR: Task (/yocto/sources/meta-librescoot/recipes-fsl/images/librescoot-mdb-image.bb:do_rootfs) failed with exit code '134'\nPseudo log:\npath mismatch [17 links]: rootfs\n", 'librescoot-mdb-image'),
            ("ERROR: Task (/yocto/sources/meta-librescoot/recipes-fsl/images/librescoot-dbc-image.bb:do_rootfs) failed with exit code '134'\nPseudo log:\ninode mismatch: rootfs\n", 'librescoot-dbc-image'),
            ("ERROR: Task (/yocto/sources/meta/recipes-core/example/example_1.2.bb:do_install) failed with exit code '134'\nPseudo log:\ninode mismatch: file\n", 'example'),
            ("ERROR: Task (/yocto/sources/example.bb:do_compile) failed with exit code '134'\n", None),
            ("ERROR: Task (/yocto/sources/example.bb:do_compile) failed with exit code '1'\nPseudo log:\n", None),
        ]
        for log, expected in cases:
            with self.subTest(expected=expected, log=log), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / 'build.log').write_text(log)
                result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', detection],
                                        cwd=tmp, text=True, capture_output=True)
                if expected is None:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    self.assertIn(f'Recipe: {expected}\n', result.stdout)

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
