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

Two sites, both with the same `stable` / `main` split.

### librescoot.org (Jekyll)

```bash
cd librescoot.github.io
git checkout stable
git pull
git merge main
git push origin stable
```

If new versions need to appear in the version dropdown, edit `_data/versions.yml` on **both** branches:

```yaml
- label: "v1.1.0"
  baseurl: ""
  description: "stable"
  is_stable: true

- label: "v1.0.3"
  baseurl: "/v1.0.3"   # only if we're keeping older releases live
  description: "previous stable"

- label: "dev"
  baseurl: "/dev"
  description: "nightly"
  is_dev: true
```

The deploy workflow auto-publishes on push to either branch.

### reference.librescoot.org (Zensical + mike)

```bash
cd unu-tech-reference
git checkout stable
git pull
git merge main
```

Then update the stable branch's `.github/workflows/deploy.yml` to deploy the new version as `latest`:

```yaml
- name: Deploy stable -> v1.1.0 + stable + latest aliases
  if: github.ref == 'refs/heads/stable'
  run: |
    mike deploy --push --update-aliases v1.1.0 stable latest
    mike set-default --push latest
```

`--update-aliases` moves the `stable` and `latest` symlinks to the new version. The previous version (`v1.0.3`) stays as a frozen entry in `versions.json`, reachable via the header dropdown.

```bash
git commit .github/workflows/deploy.yml -m "ci: bump stable mike deploy to v1.1.0"
git push origin stable
```

To remove an older version entirely, do it from a local checkout that has mike installed: `mike delete --push v0.9.0`.

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
| librescoot.org canonical | `librescoot/librescoot.github.io` | `stable` | served at `librescoot.org/` |
| librescoot.org dev preview | `librescoot/librescoot.github.io` | `main` | served at `librescoot.org/dev/` |
| librescoot.org version list | `librescoot/librescoot.github.io` | both | `_data/versions.yml` |
| reference.librescoot.org versioned | `librescoot/unu-tech-reference` | `gh-pages` (managed by mike) | `<version>/`, `latest`, `stable` |
| reference.librescoot.org sources | `librescoot/unu-tech-reference` | `stable` + `main` | mike deploy via `.github/workflows/deploy.yml` |

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

- librescoot.org: `git revert` on `stable`, push.
- reference.librescoot.org: re-run mike with the previous version as the `latest` alias target. `mike deploy --push --update-aliases v1.0.3 stable latest && mike set-default --push latest`.
