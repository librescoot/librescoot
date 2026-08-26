# Releasing

How a change gets from a green nightly to a tagged stable image.

## Channels

| Channel | Env file | Trigger | Version label |
|---------|----------|---------|---------------|
| `nightly` | `nightly.env` (mostly empty, AUTOREVs) | scheduled (cron, daily 01:00 UTC) or `gh workflow run build.yml -f channel=nightly` | `nightly-<TIMESTAMP>` |
| `testing` | `stable.env` (pinned SRCREVs) | `gh workflow run build.yml -f channel=testing` | `testing-<TIMESTAMP>` |
| `stable` | `stable.env` (pinned SRCREVs) | `git push origin v<X.Y.Z>` (tag push) | `v<X.Y.Z>` |

Both `testing` and `stable` build the same set of SRCREVs (whatever's pinned in `stable.env`). The difference is just the trigger and the version label, plus the pre-release flag on the GitHub Release. Use `testing` to validate a `stable.env` change before tagging, then push the tag.

`nightly` is on its own track. It tracks AUTOREV (HEAD of every service repo), so it's only useful if you trust whatever happens to be on `wrynose` / `main` at build time.

`wrynose` is the current Yocto base and the default branch of this repo. `scarthgap` is the older base, covering anything before 1.2.x. It still exists, but releases are not cut from it.

## Promoting a release

The full path: bump SRCREVs, run a `testing` build, soak it, push a tag for `stable`, bump the docs sites.

### 1. Bump SRCREVs

```bash
cd librescoot

# Bump every service's pinned SRCREV to its current upstream tip:
./update_env.py --target stable --all

# Or pick specific ones:
./update_env.py --target stable alarm-service motion-service

git diff stable.env
git commit stable.env -m "stable: bump <services>"
git push origin wrynose
```

`update_env.py` rewrites `SRCREV_<service>=...` lines with the latest commit hash from each repo's GitHub HEAD.

### 2. Run a testing build

```bash
gh workflow run build.yml --repo librescoot/librescoot --ref wrynose -f channel=testing
gh run list --repo librescoot/librescoot --workflow build.yml --limit 1
```

A `testing` build produces `testing-<TIMESTAMP>` artifacts using the SRCREVs you just pinned. Same image content as the eventual stable, different label.

### 3. Soak on a deployed scooter

```bash
ssh deep-blue 'lsc ota channel mdb testing && lsc ota channel dbc testing'
ssh deep-blue 'lsc ota check'
ssh deep-blue 'lsc ota status'
```

Wait for both partitions to install, reboot, and come back `idle` on the new `testing-<TIMESTAMP>`. Smoke-test what changed.

### 4. Tag stable

```bash
git tag -a v1.1.0 -m "v1.1.0: <one-line summary>"
git push origin v1.1.0
```

The tag push triggers a `stable` channel build that produces `v1.1.0` artifacts. Same SRCREVs as the testing build, different label, marked non-prerelease on the Release.

Channel-set scooters back to `stable` if you flipped them earlier:

```bash
ssh deep-blue 'lsc ota channel mdb stable && lsc ota channel dbc stable && lsc ota check'
```

## Bumping the docs sites

Two sites. Neither uses a `stable` branch any more, whatever an older copy of this file told you.

### librescoot.org (Jekyll)

Every version is a folder on `main`: `docs/<minor>/` for frozen stable snapshots, `docs/dev/`
for the working tree, with German mirrors under `de/docs/`. There is no `stable` branch on the
remote. Promoting a minor is one script plus a review:

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
