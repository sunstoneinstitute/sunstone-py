# Migration Guide: datasets.lock.yaml (v1.7)

Starting in v1.7, sunstone-py separates `datasets.yaml` into two files:

| File | Who writes it | Committed? |
|------|---------------|------------|
| `datasets.yaml` | You | Yes — human-authored, kept clean |
| `datasets.lock.yaml` | sunstone-py | Yes — auto-generated, marked linguist-generated |

**Why?** Inline `lineage:` blocks in `datasets.yaml` made diffs noisy and created merge conflicts. The lock file holds all auto-generated provenance data (content hashes, timestamps, source references, field derivations) while `datasets.yaml` stays readable.

---

## Step 1: Run the migration command

From your project directory (where `datasets.yaml` lives):

```bash
sunstone dataset migrate
```

This command:

1. Finds all output datasets with inline `lineage:` blocks
2. Moves them to `datasets.lock.yaml`
3. Removes the `lineage:` blocks from `datasets.yaml`
4. Creates or updates `.gitattributes` to mark `datasets.lock.yaml` as linguist-generated

Example output:

```
Migrated lineage for 3 output(s): processed-feed, slaughter-processed, biomass-processed
Updated .gitattributes
```

If there is nothing to migrate:

```
No inline lineage found — nothing to migrate.
```

---

## Step 2: Commit both files

```bash
git add datasets.yaml datasets.lock.yaml .gitattributes
git commit -m "chore: migrate lineage to datasets.lock.yaml"
```

---

## Step 3: Update any CI that uses `sunstone dataset lock`/`unlock`

The old commands have been renamed:

| Old command | New command |
|-------------|-------------|
| `sunstone dataset lock` | `sunstone dataset strict` |
| `sunstone dataset unlock` | `sunstone dataset unstrict` |

The old names are removed in v1.7 — update your scripts and CI workflows accordingly.

---

## Optional: Resolve and verify the lock file

After migrating, you can regenerate content hashes for all inputs and outputs:

```bash
sunstone dataset resolve
```

To verify the lock file is up to date in CI (exits non-zero if stale):

```bash
sunstone dataset resolve --check
```

---

## What the lock file looks like

`datasets.lock.yaml` is a flat list of inputs and outputs keyed by `slug`. Example:

```yaml
outputs:
  - slug: processed-feed
    content_hash: 3a4ddda929a907888d69182b9ce36d29e3eb5214b4c6b8533cca57e025386e8e
    created_at: '2026-03-25T19:52:56.782962'
    sources:
      - slug: feed-consumption-raw
    context:
      script_path: /path/to/project/.venv/bin/project
inputs:
  - slug: feed-consumption-raw
    content_hash: sha256:abc123...
```

You do not need to edit this file manually — sunstone-py maintains it automatically when you write datasets.

---

## Deprecation notice

Inline `lineage:` blocks in `datasets.yaml` are deprecated as of v1.7 and will be removed in a future major version. sunstone-py will warn at load time if it detects inline lineage — run `sunstone dataset migrate` to resolve the warning.
