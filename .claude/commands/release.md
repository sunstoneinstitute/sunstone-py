# Release sunstone-py

You are performing a release of the sunstone-py package. Arguments: $ARGUMENTS

## Step 1: Determine bump level

Parse `$ARGUMENTS` for `--bump {major,minor,patch}`. If no `--bump` argument is provided, determine the bump level automatically:

1. Find the latest version tag: `git tag --sort=-v:refname | head -1`
2. Get the diff summary since that tag: `git log <tag>..HEAD --oneline`
3. Classify:
   - **minor**: if there are any `feat:` commits (new features, new CLI commands, new modules)
   - **patch**: if only `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, or similar non-feature commits
   - **NEVER bump major** unless the user explicitly passed `--bump major`

State the bump level and why.

## Step 2: Ensure documentation is up to date

Before generating the changelog, review the commits since the last version tag (`git log <tag>..HEAD --oneline`) and check that user-facing documentation reflects them. In particular:

- **README.md** — new features, CLI commands, options, or changed usage.
- **CLAUDE.md** — package structure (new/removed modules), plugin system, or workflow changes.
- **docs/** and docstrings — any API surface that changed.
- **`sunstone-dev:dataset` skill** in the claude-plugins repo (`~/git/sunstone/claude-plugins/plugins/sunstone-dev/skills/dataset/`) — update if the release changes the public DataFrame/dataset API, `datasets.yaml` schema, or data-science workflow the skill documents. This skill lives in a separate repo, so flag it for a follow-up commit/PR there rather than editing it as part of this release. Every claude-plugins PR must carry a version bump label: apply `bump-minor` (use it whether or not the change adds a new capability — if it's not a new capability, still `bump-minor`), and never use `bump-major`. Add the `documentation` label too for doc updates.

For each change that affects how users interact with the package, confirm the docs match. If anything is stale, update it now (or flag it to the user) so the release ships with accurate documentation. If everything is already current, say so and move on.

## Step 3: Generate changelog entry

First, check if CHANGELOG.md already has entries under `## [Unreleased]`. If it does, use those as the starting point — they were written incrementally during development and are likely accurate. Supplement with any commits not already covered.

If `[Unreleased]` is empty, review the commits since the last version tag and write a changelog entry from scratch.

Format as [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Use these category prefixes per line (no group headings):

- `- Added:` — new features
- `- Changed:` — changes in existing functionality
- `- Improved:` — material performance improvement
- `- Fixed:` — bug fixes
- `- Removed:` — removed features

Be concise but descriptive. Each entry should be one line. Fold multiple lines describing the same change into a single line. Keep every line user-focused, internal CI refactors are not interesting for the user. Rephrase and reorganize as necessary.

Do NOT include the version header line — the release script adds that. The release script also clears the `[Unreleased]` section automatically, so don't worry about duplication.

## Step 4: Confirm with user

Show the user:
- Current version → new version
- The bump level and reasoning
- The changelog entry

Ask for confirmation before proceeding. If the user wants changes, revise accordingly.

## Step 5: Run the release script

Once confirmed, pipe the changelog entry to the release script:

```bash
echo '<changelog entry>' | uv run python scripts/release.py --bump <level>
```

Make sure to properly escape the changelog text for the shell. Use a heredoc if the changelog contains quotes or special characters:

```bash
uv run python scripts/release.py --bump <level> <<'CHANGELOG'
<changelog entry>
CHANGELOG
```

## Step 6: Report result

Show the user the new version tag and remind them to push with tags when ready:

```
git push && git push --tags
```
