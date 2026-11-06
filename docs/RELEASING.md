# Releasing

Only a maintainer can release. Publishing is done by `.github/workflows/release.yml` on a `v*` tag; nothing is uploaded from a laptop.

## One-time setup

1. **PyPI project.** Sign in to PyPI as the owner of the `whatsent` name and add a pending publisher under *Your projects → Publishing*:
   - PyPI project name: `whatsent`
   - Owner: `sundaysebasidian-byte`
   - Repository name: `whatsent`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

   After the first successful release the publisher is attached to the project; later releases need no change.
2. **GitHub environment.** In *Settings → Environments*, create an environment named `pypi`. Add required reviewers if the release should need a second approval. No secrets are needed: the workflow authenticates with the OIDC token (`id-token: write`) and never stores a PyPI API token.

If the PyPI project already exists under another owner, the publisher must be added by that owner instead, and `docs`/`pyproject.toml` URLs must change with it.

## Per release

1. Update the version in both places, which the workflow checks against each other:
   - `pyproject.toml`: `[project] version`
   - `src/whatsent/__init__.py`: `__version__`
2. Add a `## X.Y.Z` section at the top of `CHANGELOG.md`, with one bullet per user-visible change. This section becomes the GitHub Release body, so write it for someone deciding whether to upgrade.
3. Run the suite locally (`pytest`, `node --test tests/ui_workflows.test.js`) and confirm `python -m build` plus `twine check dist/*` are clean.
4. Commit, then tag and push the tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

5. Watch the `release` workflow. In order it: checks that the tag equals `project.version`; builds the sdist and wheel; runs `twine check`; installs the wheel in a clean virtualenv outside the checkout and checks `whatsent --version` and `whatsent demo --out`; publishes to PyPI; creates the GitHub Release from the CHANGELOG section.

## If something fails

- **Tag does not match the version**: delete the tag (`git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`), fix the version, and tag again. The version was never published, so the tag can still be moved.
- **A job after publishing fails** (for example the GitHub Release step): do not move the tag and do not publish a new version just to retry. Re-run only the failed job from the Actions page; `publish` would fail because PyPI refuses a second upload of the same files. If the release must be created by hand, use the notes extracted from `CHANGELOG.md` with `gh release create vX.Y.Z --notes-file <file>`.
- **A bad release reached PyPI**: PyPI does not allow re-uploading a version or deleting files. Yank the release on PyPI, publish a patch version, and say so in `CHANGELOG.md`.

The `pages` workflow publishes the leaderboard from `main` on every push and is not part of a release.
