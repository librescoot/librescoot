# Releasing

How a change gets from a green nightly to a tagged stable image.

## Channels

| Channel | Env file | Trigger | Version label |
|---------|----------|---------|---------------|
| `nightly` | `nightly.env` (mostly empty, AUTOREVs) | scheduled (00:57 Europe/Berlin, subject to scheduler delays) or manual workflow | `nightly-<TIMESTAMP>` |
| `testing` | `stable.env` (pinned SRCREVs) | `gh workflow run build.yml -f channel=testing` | `testing-<TIMESTAMP>` |
| `stable` | `stable.env` (pinned SRCREVs) | `git push origin v<X.Y.Z>` (tag push) | `v<X.Y.Z>` |

Both `testing` and `stable` use the SRCREVs in `stable.env` when built from the same umbrella commit without overrides. The version label and channel-specific behavior can still differ. Record and compare all inputs, including layer pins and any unpinned sources; equal service pins alone do not establish identical images. Use `testing` to validate the intended candidate before tagging.

`nightly` is on its own track. It tracks AUTOREV (HEAD of every service repo), so it's only useful if you trust whatever happens to be on `wrynose` / `main` at build time.

`wrynose` is the current Yocto base and the default branch of this repo. `scarthgap` is the older base, covering anything before 1.2.x. It still exists, but releases are not cut from it.

## Minimal bootstrap images

Scheduled builds, release tags and manual `build.yml` runs build only the full
MDB and DBC images. Minimal bootstrap images are rebuilt separately, on purpose:

```bash
gh workflow run build-minimal.yml --repo librescoot/librescoot --ref wrynose -f channel=testing
```

The **Build minimal images** workflow builds both `mdb-minimal` and `dbc-minimal`.
It defaults to `testing` (`stable.env` pins); select `nightly` for floating service
revisions. An optional `meta_librescoot_branch` input overrides the channel's
meta-librescoot ref.

Download the `.sdimg.gz` images and available `.sdimg.bmap` files from the run's
Actions artifacts. They are retained for 90 days, subject to repository retention
limits; archive them separately if needed longer. This workflow creates no GitHub
release, delta patches or site rebuilds. Existing release assets are unchanged.
The former `build.yml` input `minimal_only` is replaced by this workflow.

Both workflows use `build-firmware.yml` for the same build, pseudo-abort recovery,
systemd verification and artifact packaging steps. Image compression uses `pigz`
at level 9 with at most eight threads; runners install it on demand if missing.

Release metadata is prepared in one job. Dashboard builds use Yocto's normal
source-revision and dependency tracking instead of unconditionally cleaning
`scootui-qt`, preserving incremental build state.

Offline workflow contract tests (requires Python 3, PyYAML, Bash, jq, gzip and
pigz; the packaging test skips if pigz is unavailable):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

## Release packaging image

The `create-release` job runs in the digest-pinned `ghcr.io/librescoot/release-tools` image. It includes `xdelta3`, Python, Git, curl, jq and the checksum-verified HDiffPatch encoder, so release jobs do not install these tools at runtime. The Yocto build uses a separate image from `docker/Dockerfile`.

To update release tools, modify `docker/release.Dockerfile`, build and test the image, and run the **Build release tools image** workflow on the intended commit. It publishes a SHA-tagged image and records its digest in the job summary. Update `create-release.container.image` to that immutable digest, run the workflow contract and delta tests, then verify an actual Testing release. The package is linked to this repository and the job uses its GitHub token with package-read permission. Do not use a mutable tag in the release job.

## Software bills of materials

Each firmware build retains Yocto's self-contained SPDX 3 image document as
`librescoot-<variant>-<version>.spdx.json.gz`. It includes the image's package,
file, relationship and license graph, not just the image recipe. A missing or
incomplete image document fails artifact collection.

The compressed document is included in the board's Actions artifact. Full
nightly, testing and stable releases also publish it as a release asset covered
by `SHA256SUMS`. Minimal builds retain it in their Actions artifacts without
creating a release. Decompress a document with `gzip -dc <file>.spdx.json.gz`.

## HDiffPatch Nightly and Testing deltas

Normal Nightly and Testing releases additionally contain `.hdelta` assets, generated with
HDiffPatch 5.1.3 and identified inside their metadata as `hdiffpatch`. The
ordinary `.delta` files remain present for older clients. A client with the
HDiffPatch decoder chooses the smaller supported delta per chain step; an old
client continues to select the ordinary asset. Stable releases and custom
nightlies do not emit `.hdelta` assets.

## Signed artifact delta compatibility

`mender-delta-create.py` includes the target `version`, `manifest`, optional
`manifest.sig` and `header.tar.gz` verbatim as new metadata. They are never
xdelta-patched. This lets a compatible update-service reconstruct a signed
artifact without changing the signed manifest or losing its signature.
A signed target needs an update-service repacker that retains `manifest.sig`
immediately after `manifest`; older repackers omit it.

For each changed payload, the generator builds xdelta patches with the default
source window and a 512 MiB source window, then packages the one with the smaller
compressed size. This retains compact patches for small changes while finding
moved data in 512 MiB root filesystems. The large-window encoder can use roughly
1.6 GiB of RAM; decoding uses the existing xdelta3 interface and does not require
an equally large allocation. Release jobs process boards sequentially.

Offline generator regressions run with the workflow tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

For real signing and reconstruction tests, see the
[update-service test instructions](https://github.com/librescoot/update-service#signed-artifact-and-delta-compatibility).
They use disposable keys, the artifact tool and optionally the actual Mender
client with an isolated test module. These tests need no production secrets.

The generator handles signed and unsigned targets; it does not verify their
signatures or authorize a release. Publishing signed artifacts and configuring
client signature enforcement are separate release steps.

## Promoting a release

The full path is to agree on scope, review and pin exact component revisions, run a `testing` build, validate it on an appropriate test vehicle, and only then publish the stable tag and matching documentation. A tag push starts the stable build and may publish a GitHub Release; obtain release authorization before pushing it.

Before selecting revisions, compare each component with the preceding stable release and review changes, tests, dependencies, local and remote branches, tags, and uncommitted work. Resolve annotated tags to commit objects with `git rev-parse <tag>^{commit}`. Record intended inclusions, exclusions and unresolved risks. Service tags alone do not pin recipes that use `AUTOREV`; `stable.env` provides the relevant overrides. Confirm the pinned commits are reachable from their intended remotes.

Treat the umbrella commit, layer revisions, component pins, channel, workflow inputs and resulting artifact hashes as the candidate. If any input changes after validation, assess the effect and repeat the relevant build and tests. Review documentation, settings and release notes against the exact candidate.

### 1. Bump SRCREVs

```bash
cd librescoot

# Select components only after reviewing their current upstream revisions:
./update_env.py --target stable alarm-service motion-service

git diff stable.env
git commit stable.env -m "stable: bump <services>"
git push origin wrynose
```

`update_env.py` rewrites the selected entries with upstream HEAD, not necessarily a release tag. Verify every resulting full SHA, including annotated tag resolution and any layer pins, before committing. Do not use `--all` as a substitute for the scope review.

### 2. Run a testing build

```bash
gh workflow run build.yml --repo librescoot/librescoot --ref wrynose -f channel=testing
gh run list --repo librescoot/librescoot --workflow build.yml --limit 1
```

A `testing` build produces `testing-<TIMESTAMP>` artifacts using the pins in the selected commit. Record the workflow run, commit and inputs. Channel-specific configuration and unpinned sources can still differ from the eventual stable build. Monitor the run until both image builds and the release job finish; a successful image build alone does not mean a release was created.

Check the published release and downloaded assets before testing. Downloading all assets needs several gigabytes of free space:

```bash
TAG=testing-YYYYMMDDThhmmss
mkdir -p "release-check/$TAG"
gh release view "$TAG" --repo librescoot/librescoot
gh release download "$TAG" --repo librescoot/librescoot --dir "release-check/$TAG"
cd "release-check/$TAG"
sha256sum -c SHA256SUMS
for delta in *.delta *.hdelta; do
    [ -f "$delta" ] || continue
    printf '\n%s\n' "$delta"
    tar -xOzf "$delta" ./metadata.json | jq '{old_artifact_name, new_artifact_name, changes}'
done
```

Confirm the MDB and DBC images and their expected delta formats exist, and that each delta names the intended base and target. The first release in a channel can have no delta. A checksum match proves the downloaded bytes match the release manifest, not that installation succeeds. Record the run URL, results and any exceptions.

### 3. Soak on a deployed scooter

```bash
ssh deep-blue 'lsc ota channel mdb testing && lsc ota channel dbc testing'
ssh deep-blue 'lsc ota check'
ssh deep-blue 'lsc ota status'
```

Wait for both boards to install, reboot, and come back `idle` on the new `testing-<TIMESTAMP>`. Record the test target, starting versions, installed versions, update path and results. Test affected features and failure/recovery paths; agree on an observation period and any exceptions. Use vehicle controls only with an explicitly authorized and safe test setup. Smoke-test what changed, plus these release-wide checks:

- **MDB time synchronization:** `chronyc tracking` on the MDB must report a normal leap status and a current reference time from an external NTP source.
- **MDB-to-DBC time synchronization:** after the DBC boots, `chronyc sources` on the DBC must select the MDB and the DBC clock must converge to the MDB clock. Verify the active USB and PPP transports and their current addresses on the target.

### 4. Tag stable

```bash
git tag -a v1.1.0 -m "v1.1.0: <one-line summary>"
git push origin v1.1.0
```

The tag push triggers a `stable` channel build that produces `v1.1.0` artifacts and a non-prerelease GitHub Release. When the tag points to the tested commit it uses the same committed pins; check channel-specific behavior and any unpinned inputs separately.

Verify the build's actual MDB and DBC artifacts, `SHA256SUMS`, release assets and delta base/target before distributing it. Preserve the generated technical changelog when adding reviewed release notes. Verify published documentation and the selected release on the download sites.

Channel-set scooters back to `stable` if you flipped them earlier:

```bash
ssh deep-blue 'lsc ota channel mdb stable && lsc ota channel dbc stable && lsc ota check'
```

## Bumping the docs sites

Two sites. Neither uses a `stable` branch any more, whatever an older copy of this file told you.

### librescoot.org (Jekyll)

Every version is a folder on `main`: `docs/<minor>/` for frozen stable snapshots, `docs/dev/`
for the working tree, with German mirrors under `de/docs/`. There is no `stable` branch on the
remote. Keep the settings overview in step with each stable release:

- For a patch release, update `docs/<minor>/settings.html` for any settings
  added or changed in that release, with the patch-version markers used on the
  page. Review the schema revision pinned in `stable.env` to confirm the page
  matches the released image.
- When promoting a new minor, update `docs/dev/settings.html` to match the
  settings schema pinned for the release and carry forward patch-version
  markers. The promotion script copies this page into the new minor snapshot.

Promoting a minor is one script plus a review:

```bash
cd librescoot.github.io
git switch main && git pull
scripts/release-new-minor.sh 1.3
```

That copies `docs/dev/` into `docs/1.3/`, rewrites permalinks and absolute `/docs/dev/*` hrefs,
moves the bare `/docs/<page>` and `/docs/stable/<page>` aliases off the previous minor onto the
new one, bumps `docs_path_prefix` in `_config.yml`, and prepends the `_data/versions.yml` entry
while clearing `is_stable` from the previous one. Read its header comment before running it.

Then inspect the diff, spot-check a build, and push `main`. The deploy workflow publishes on
push. `/docs/stable/` follows whichever minor is current, so no link needs updating by hand.

### reference.librescoot.org (Zensical + mike)

`unu-tech-reference` has its own `RELEASING.md` and that file is authoritative. The short
version:

1. Branch the snapshot off the release and push it:

   ```bash
   cd unu-tech-reference
   git switch -c docs/v1.3.0 origin/main
   # trim anything that does not describe what shipped, commit
   git push -u origin docs/v1.3.0
   ```

   CI deploys `v1.3.0` as a selectable version. It does not become stable yet.

2. Promote it: Actions -> Deploy versioned docs -> Run workflow, `promote` = `v1.3.0`. That
   moves the `stable` and `latest` aliases and makes it the default served at `/`.

A push never moves the aliases; publishing a version and promoting it are separate on purpose.
The whole pipeline lives in one reusable workflow, `deploy-impl.yml` on `main`, and each
`docs/v*` branch carries only a thin caller, so pipeline fixes are one commit rather than one
per snapshot.

> **Do not push to `origin/stable` in that repo.** It still carries an old workflow that fires
> on push and runs `mike deploy --push --update-aliases v1.0.3 stable latest` followed by
> `mike set-default --push latest`. A single push there reverts the entire docs site to v1.0.3.
> Deleting that branch is tracked in bean `librescoot-0f05`.

To check what is actually published, read `versions.json` on the `gh-pages` branch. A deploy
workflow sitting on some other branch is not evidence of what the site serves.

To remove an older version entirely, do it from a local checkout that has mike installed:
`mike delete --push v0.9.0`.

## Tagging individual service repos

Each service is independently versioned via `git describe --tags`. The Makefile bakes the version into the binary:

```makefile
VERSION = $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS = -ldflags "-w -s -X main.version=$(VERSION)"
```

Cut a service-level tag before bumping `stable.env`:

```bash
cd <service-repo>
git tag -a v0.5.0 -m "feat: ..."
git push origin v0.5.0
```

Then `update_env.py --target stable <service>` picks up the tagged commit.

`update_env.py` reads each repo's HEAD, not its tags, so it only lands on the tag if you tagged HEAD. Tag first, then bump. To confirm a pin sits on a release rather than a few commits past one, `git describe --tags <sha>` in the service repo should print a bare `vX.Y.Z` with no `-N-g<sha>` suffix.

## Where things live

| Concern | Repo | Branch | Path |
|---------|------|--------|------|
| Channel SRCREV pins (testing, stable) | `librescoot/librescoot` | `wrynose` | `stable.env` |
| Channel SRCREV pins (nightly, mostly AUTOREV) | `librescoot/librescoot` | `wrynose` | `nightly.env` |
| SRCREV bump tooling | `librescoot/librescoot` | `wrynose` | `update_env.py` |
| Changelog generator | `librescoot/librescoot` | `wrynose` | `.github/workflows/scripts/changelog.sh` |
| Build pipeline | `librescoot/librescoot` | `wrynose` | `.github/workflows/build.yml` |
| Image recipes | `librescoot/meta-librescoot` | `wrynose` | Yocto layer |
| librescoot.org stable docs | `librescoot/librescoot.github.io` | `main` | `docs/<minor>/`, `de/docs/<minor>/` |
| librescoot.org dev preview | `librescoot/librescoot.github.io` | `main` | `docs/dev/`, served at `librescoot.org/docs/dev/` |
| librescoot.org version list | `librescoot/librescoot.github.io` | `main` | `_data/versions.yml`, `docs_path_prefix` in `_config.yml` |
| librescoot.org promotion | `librescoot/librescoot.github.io` | `main` | `scripts/release-new-minor.sh` |
| reference.librescoot.org published site | `librescoot/unu-tech-reference` | `gh-pages` (managed by mike) | `<version>/`, `latest`, `stable`, `versions.json` |
| reference.librescoot.org snapshots | `librescoot/unu-tech-reference` | `docs/vX.Y.Z` | thin caller workflow only |
| reference.librescoot.org pipeline | `librescoot/unu-tech-reference` | `main` | `.github/workflows/deploy-impl.yml` |

## Rollback

If a stable build is bad, revert `stable.env` and re-tag:

```bash
cd librescoot
git revert <bad-commit>
git push origin wrynose
git tag -a v1.1.1 -m "revert v1.1.0: <reason>"
git push origin v1.1.1
```

Scooters that already updated to the bad release pick up `v1.1.1` on their next OTA check. There's no in-place rollback CLI; the previous image is on the inactive Mender partition until the next OTA writes over it, but switching back requires u-boot env manipulation, which is out of scope here.

For docs-only rollbacks:

- librescoot.org: `git revert` on `main`, push.
- reference.librescoot.org: re-run Deploy versioned docs with `promote` set to the previous version. That moves `stable` and `latest` back without touching any snapshot.
