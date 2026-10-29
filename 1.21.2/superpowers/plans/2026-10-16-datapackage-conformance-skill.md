# Datapackage Conformance (claude-plugins, C10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The `sunstone-core:dataset` skill teaches agents the new `datasets.yaml` key form, points them at the generated key reference, `sunstone vocab search` and `sunstone lint --json --warnings-as-errors`, never shows an old key, and teaches how to restructure a free-text source into parts (DOI in `"@id"`, publisher and authors as agent objects, year, container, citation) with lint as the checklist.

**Architecture:** The hand-written `references/datasets-yaml-schema.md` is replaced by `references/datasets-yaml-reference.md`, a copy of sunstone-py's generated `docs/datasets-yaml-reference.md` kept current by a sync script. `SKILL.md` and the other references are rewritten to the new key form with a fixed "find a key, write it, lint" loop, plus a "Restructuring sources" procedure (spec "Source references": `sunstone migrate` makes only the mechanical changes; splitting citations into parts is this skill's job, project by project, during the 1.x grace period).

**Tech Stack:** Markdown skill files, Python 3 sync script under `scripts/`, repo validation scripts.

**Spec:** `sunstone-py` repo, `docs/superpowers/specs/2026-10-15-datapackage-conformance-design.md`, section C10 (spec names the skill `sunstone-core:dataset`; it lives in `plugins/sunstone-core/skills/dataset/`, see sunstone-py plan conflict SC1).

**Prerequisite:** sunstone-py plan `2026-10-16-datapackage-conformance-sunstone-py.md` is merged and released as 1.20.0 (the reference doc, `sunstone migrate` and `sunstone vocab search` must exist). The sync script reads the reference from a local sunstone-py checkout, so execution needs `~/git/sunstone/sunstone-py` at a commit that contains `docs/datasets-yaml-reference.md`.

## Global Constraints

- Repo: `/Users/stig/git/sunstone/claude-plugins`, `git fetch origin`, then work on a feature branch off `origin/main`; all paths below are relative to the repo root.
- Do not edit `version` in `plugins/sunstone-core/.claude-plugin/plugin.json` or `marketplace.json`; the PR gets the `bump-minor` label (new content).
- Skill prose follows `CLAUDE.md` "Naming Conventions" and the writing rules already used in `SKILL.md` (plain language, no emoji, no decorative headings).
- Every `datasets.yaml` example in the skill uses the new key form: `title`, `name`, `path`, `schema.fields`, `licenses`; source `"@id"`/`title`/`dct:publisher` (agent object)/`dct:creator`/`dct:issued`/`dct:isPartOf`/`dct:bibliographicCitation`/`dcat:downloadURL`/`dcat:landingPage`/`dct:license`/`dct:modified`; dataset `prov:generatedAtTime`/`prov:wasGeneratedBy`; field `si:unit`/`si:sourceField`/`title`.
- Source MUST keys (spec "Provenance"): `title`; `dct:publisher` object with `rdfs:label`; a link (`"@id"`, `dcat:downloadURL` or `dcat:landingPage`); `dct:license`. `prov:wasAttributedTo` is MAY (legacy free text). A `doi.org` URL never goes in `dcat:downloadURL`/`dcat:landingPage` (R315); it goes in `"@id"`.
- Agent object: `rdfs:label` (full name), `skos:altLabel` (short name, SHOULD), `"@id"` (IRI, optional). The same agent is repeated within one file with a YAML anchor (`&fao` on first use, `*fao` after); anchors do not cross include files. There is no lookup table.
- `"@id"` is always quoted in YAML (`"@id":`), `@type` likewise (`'@type':`).
- Acquisition method literal lives in `prov:wasGeneratedBy.dct:type` (sunstone-py plan conflict SC11).
- Validation before the PR: `uv run python scripts/validate-claude-metadata.py`, `scripts/check-plugin-structure.sh`, `claude plugin validate .`, `uv run pytest scripts/tests`.
- Commit messages: conventional prefix, no Co-authored-by lines.

## File map

| File | Responsibility |
|---|---|
| `scripts/sync-dataset-reference.py` | Copies sunstone-py `docs/datasets-yaml-reference.md` into the skill with a provenance header |
| `scripts/tests/test_sync_dataset_reference.py` | Tests the sync script on a temp tree |
| `plugins/sunstone-core/skills/dataset/references/datasets-yaml-reference.md` | Synced key reference (generated; replaces `datasets-yaml-schema.md`) |
| `plugins/sunstone-core/skills/dataset/SKILL.md` | Capture rule, key loop, examples |
| `plugins/sunstone-core/skills/dataset/references/registry-patterns.md`, `api-reference.md`, `troubleshooting.md` | Examples in new key form |

---

### Task 1: Sync script and the generated reference

**Files:**
- Create: `scripts/sync-dataset-reference.py`, `scripts/tests/test_sync_dataset_reference.py`
- Create (by running the script): `plugins/sunstone-core/skills/dataset/references/datasets-yaml-reference.md`
- Delete: `plugins/sunstone-core/skills/dataset/references/datasets-yaml-schema.md`

**Interfaces:**
- Produces: `scripts/sync-dataset-reference.py [--sunstone-py PATH] [--check]`; exit 0 when the file was written (or, with `--check`, already current), exit 1 with `--check` when stale, exit 2 when the source file is missing.

- [ ] **Step 1: Write the failing test `scripts/tests/test_sync_dataset_reference.py`**

```python
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sync-dataset-reference.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def _fake_sunstone_py(tmp_path: Path, body: str = "# datasets.yaml key reference\n\nbody\n") -> Path:
    src = tmp_path / "sunstone-py"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "datasets-yaml-reference.md").write_text(body)
    (src / "pyproject.toml").write_text('[project]\nname = "sunstone-py"\nversion = "1.20.0"\n')
    return src


def test_writes_reference_with_header(tmp_path: Path) -> None:
    src = _fake_sunstone_py(tmp_path)
    dest = tmp_path / "dest.md"
    r = _run("--sunstone-py", str(src), "--dest", str(dest))
    assert r.returncode == 0, r.stderr
    text = dest.read_text()
    assert text.startswith("<!-- Synced from sunstone-py 1.20.0 docs/datasets-yaml-reference.md by scripts/sync-dataset-reference.py. Do not edit. -->\n")
    assert text.endswith("body\n")


def test_check_mode(tmp_path: Path) -> None:
    src = _fake_sunstone_py(tmp_path)
    dest = tmp_path / "dest.md"
    assert _run("--sunstone-py", str(src), "--dest", str(dest)).returncode == 0
    assert _run("--sunstone-py", str(src), "--dest", str(dest), "--check").returncode == 0
    (src / "docs" / "datasets-yaml-reference.md").write_text("# changed\n")
    assert _run("--sunstone-py", str(src), "--dest", str(dest), "--check").returncode == 1


def test_missing_source(tmp_path: Path) -> None:
    r = _run("--sunstone-py", str(tmp_path / "nope"), "--dest", str(tmp_path / "d.md"))
    assert r.returncode == 2 and "docs/datasets-yaml-reference.md" in r.stderr
```

Run: `uv run pytest scripts/tests/test_sync_dataset_reference.py -q`
Expected: FAIL (script missing).

- [ ] **Step 2: Write `scripts/sync-dataset-reference.py`**

```python
#!/usr/bin/env python3
"""Copy sunstone-py's generated datasets.yaml key reference into the dataset skill.

Usage:
    scripts/sync-dataset-reference.py [--sunstone-py ~/git/sunstone/sunstone-py] [--dest PATH] [--check]

Exit codes: 0 written or current, 1 stale (--check), 2 source missing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = Path.home() / "git" / "sunstone" / "sunstone-py"
DEFAULT_DEST = REPO / "plugins" / "sunstone-core" / "skills" / "dataset" / "references" / "datasets-yaml-reference.md"
REL = Path("docs") / "datasets-yaml-reference.md"


def _version(sunstone_py: Path) -> str:
    text = (sunstone_py / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def render(sunstone_py: Path) -> str:
    body = (sunstone_py / REL).read_text(encoding="utf-8")
    header = (
        f"<!-- Synced from sunstone-py {_version(sunstone_py)} {REL.as_posix()} "
        "by scripts/sync-dataset-reference.py. Do not edit. -->\n"
    )
    return header + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sunstone-py", default=str(DEFAULT_SRC))
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    src = Path(args.sunstone_py)
    if not (src / REL).exists():
        print(f"error: {src / REL} not found", file=sys.stderr)
        return 2
    dest = Path(args.dest)
    text = render(src)
    if args.check:
        current = dest.read_text(encoding="utf-8") if dest.exists() else ""
        if current == text:
            print(f"{dest} is current")
            return 0
        print(f"{dest} is stale; run scripts/sync-dataset-reference.py", file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`chmod +x scripts/sync-dataset-reference.py`.

Run: `uv run pytest scripts/tests/test_sync_dataset_reference.py -q`
Expected: PASS.

- [ ] **Step 3: Generate the reference and remove the old schema file**

```bash
scripts/sync-dataset-reference.py
git rm plugins/sunstone-core/skills/dataset/references/datasets-yaml-schema.md
grep -rn "datasets-yaml-schema" plugins/sunstone-core --include=*.md
```

Expected: the grep lists only `SKILL.md` (two links: the "References" list and the `## The datasets.yaml registry` section). Both are rewritten in Task 2; for now replace the path text `references/datasets-yaml-schema.md` with `references/datasets-yaml-reference.md` in those two places so no link dangles.

Add a line to `CLAUDE.md` under "Testing Changes": "`scripts/sync-dataset-reference.py` refreshes the dataset skill's key reference from a sunstone-py checkout; run it after each sunstone-py release that changes `docs/datasets-yaml-reference.md`."

- [ ] **Step 4: Commit**

```bash
git add scripts/sync-dataset-reference.py scripts/tests/test_sync_dataset_reference.py plugins/sunstone-core/skills/dataset CLAUDE.md
git commit -m "feat(dataset): sync generated datasets.yaml key reference from sunstone-py"
```

---

### Task 2: Rewrite `SKILL.md` for the new key form

**Files:**
- Modify: `plugins/sunstone-core/skills/dataset/SKILL.md`

The sections below name the current heading or sentence to replace and give the replacement text in full. Everything else in the file stays.

- [ ] **Step 1: Step 2 of the capture rule**

Replace the YAML block under `### Step 2: Register the source in datasets.yaml before downloading` and the paragraph starting "All six `source` keys are required by this rule" with:

````markdown
```yaml
inputs:
  - title: Air Quality Measurements 2024
    name: air-quality-2024
    path: inputs/air-quality-2024.csv
    description: Hourly PM2.5 and NO2 readings for 2024.
    source:
      title: Example Agency Air Quality Database
      dct:publisher:
        rdfs:label: Example Environment Agency
        skos:altLabel: EEA
      dcat:downloadURL: https://data.example.org/air-quality/2024.csv
      dcat:landingPage: https://data.example.org/air-quality
      dct:issued: '2024'
      dct:modified: '2026-09-01'
      dct:license: CC-BY-4.0                 # SPDX identifier
    prov:generatedAtTime: '2026-09-24'       # when this copy was fetched
    prov:wasGeneratedBy:
      '@type': prov:Activity
      dct:type: api                           # manual-download, api, scraping
```

```python
from sunstone import pandas as pd
df = pd.read_dataset('air-quality-2024')   # downloads to inputs/ on first call
```

The capture rule requires, on the source: `title`; `dct:publisher` as an object with `rdfs:label`; a link (`dcat:downloadURL` for a file, `dcat:landingPage` for a page, or `"@id"` for a DOI); `dct:license`. On the dataset: `prov:generatedAtTime` and `prov:wasGeneratedBy` with `dct:type`. Add `skos:altLabel` on the publisher, `dct:issued` and `dct:modified` when the publisher's page shows them. A publication (paper, report) is written as in "Restructuring sources" below. Check with:

```bash
sunstone lint --json --warnings-as-errors
```

The capture is done only when that command prints no violations.
````

- [ ] **Step 2: Add the key loop**

Insert a new section immediately after the "## Platform quick reference" section (before "## The capture rule"):

````markdown
## Writing keys in datasets.yaml

Every key in `datasets.yaml` is one of three things: a Data Package 2.0 property for its level (`title`, `name`, `path`, `schema`, `licenses`, ...), a sunstone config key (`inputs`, `source`, `publish`, `rdfPrefixes`, ...), or an RDF property written as `prefix:local` (`dct:publisher`, `prov:wasAttributedTo`, `si:unit`). Nothing else is allowed, and `sunstone lint` reports any other key as R301.

Never invent a key. To record a concept that has no key in [datasets-yaml-reference.md](references/datasets-yaml-reference.md):

```bash
sunstone vocab search "<concept>" --at <path> --json   # e.g. --at inputs.source, --at outputs.schema.fields
sunstone vocab search --at inputs.source                # every allowed key at that level, with its rule level
```

Pick a result from the output (the first hit is usually right; prefer `dct`, `dcat`, `prov` over `schema`, and `si` only for sunstone-specific concepts). Use its `curie` as the key. If no result fits, leave the concept out and tell the user; do not write a key the search did not return.

A key may take an object value when the property points at a thing with its own properties:

```yaml
prov:wasGeneratedBy:
  '@type': prov:Activity
  dct:type: manual-download
```

Keys inside the object follow the same rules (`@id` and `@type` are also allowed).

Projects created before sunstone-py 1.20 use older keys (`slug`, `location`, `fields`, `attributedTo`, `acquiredAt`, ...). They still load, with one `FutureWarning` per file. Run `sunstone migrate` once to rewrite `datasets.yaml`, its include files and `datasets.lock.yaml`; it keeps comments, moves a DOI from `location.*` to `"@id"`, keeps the old `attributedTo` text as `prov:wasAttributedTo`, and reports keys it cannot map, each with suggestions from `sunstone vocab search`. It never splits free text: that is the next section.

## Restructuring sources

Most existing sources are free text: `title` holds a whole citation and `prov:wasAttributedTo` mixes authors, affiliation and publisher. sunstone-py 2.0 requires every source to carry its parts, and `sunstone lint` reports what is missing (R102 is an error, R311 a warning, R315 an error). Do this once per project, source by source:

1. Run `sunstone lint --json` and collect every violation whose `path` starts with `inputs[...].source`.
2. For each source, read `title` and `prov:wasAttributedTo` and split them into parts. Put each part under its key; never leave a part in two places.

| Part | Key | Example |
|---|---|---|
| DOI or persistent IRI | `"@id"` | `"@id": https://doi.org/10.1016/j.aqrep.2022.101316` |
| Work title only | `title` | `title: Utilization of feed resources in the production of Atlantic salmon (Salmo salar) in Norway` |
| Publisher | `dct:publisher` | `{rdfs:label: Elsevier}`; `{rdfs:label: Food and Agriculture Organization of the United Nations, skos:altLabel: FAO}` |
| Authors | `dct:creator` | `[{rdfs:label: 'Aas, T. S.'}, {rdfs:label: 'Asgard, T. E.'}]` |
| Year | `dct:issued` | `'2022'` |
| Journal, volume, pages | `dct:isPartOf` | `{rdfs:label: 'Aquaculture Reports 26, 101316'}` |
| Full citation as published | `dct:bibliographicCitation` | the citation string, when the publisher gives one |
| Links | `dcat:downloadURL`, `dcat:landingPage` | the file, the page; never a `doi.org` URL |
| License | `dct:license` | SPDX id |

3. Keep the original `prov:wasAttributedTo` text until every part is placed, then delete it (it is MAY, so keeping it is not an error; deleting it keeps the file short).
4. Define each agent once per file. On the first use write `dct:publisher: &fao` followed by the object; on every later use in the same file write `dct:publisher: *fao`. Include files anchor their own agents.
5. Rerun `sunstone lint --json --warnings-as-errors`. Done when no violation has a `path` under `source`.

A statistics release has a publisher and no authors; a paper has authors and a publisher (the journal's publisher, not the authors' institution). When a part is not known, leave the key out; do not guess a year or an author.

Before, from a real project:

```yaml
    source:
      title: Mottet, de Haan, Falcucci, Tempio, Opio & Gerber (2017), Livestock: On our plates or eating at our table? A new analysis of the feed/food debate, Global Food Security 14, 1-8
      dcat:landingPage: https://doi.org/10.1016/j.gfs.2017.01.001
      prov:wasAttributedTo: Mottet, A.; de Haan, C.; Falcucci, A.; Tempio, G.; Opio, C.; Gerber, P. (FAO); published by Elsevier in Global Food Security
      dct:license: CC-BY-NC-ND-4.0
```

After:

```yaml
    source:
      "@id": https://doi.org/10.1016/j.gfs.2017.01.001
      title: "Livestock: On our plates or eating at our table? A new analysis of the feed/food debate"
      dct:publisher: &elsevier
        rdfs:label: Elsevier
      dct:creator:
        - rdfs:label: Mottet, A.
        - rdfs:label: de Haan, C.
        - rdfs:label: Falcucci, A.
        - rdfs:label: Tempio, G.
        - rdfs:label: Opio, C.
        - rdfs:label: Gerber, P.
      dct:issued: '2017'
      dct:isPartOf:
        rdfs:label: Global Food Security 14, 1-8
      dct:license: CC-BY-NC-ND-4.0
```

The next Elsevier paper in the same file writes `dct:publisher: *elsevier`.
````

- [ ] **Step 3: Version floor**

Replace "This guide requires **sunstone-py >= 1.13**. The data-platform plugin requires >= 1.15." and the following code block with:

````markdown
This guide requires **sunstone-py >= 1.20** (new key names, `sunstone migrate`, `sunstone vocab search`). The data-platform plugin requires >= 1.15.

```bash
uv add 'sunstone-py>=1.20'
```
````

- [ ] **Step 4: File structure example**

Replace the `# datasets.yaml — human-authored` YAML block under "### File structure and fields" with:

```yaml
# datasets.yaml — human-authored
min_sunstone_version: "1.20.0"

inputs:
  - title: User Data
    name: users
    path: inputs/users.csv
    description: One row per registered user.
    source:
      title: User Database Export
      dct:publisher:
        rdfs:label: Data Engineering Team
      dcat:downloadURL: https://example.com/exports/users.csv
      dct:license: CC-BY-4.0
    prov:generatedAtTime: '2025-01-15'
    prov:wasGeneratedBy:
      '@type': prov:Activity
      dct:type: manual-download
    schema:
      fields:
        - name: user_id
          type: integer
          title: User ID
        - name: email
          type: string
          title: Email Address
        - name: created_at
          type: datetime
          title: Account Created At

outputs:
  - title: User Analysis Results
    name: user-analysis
    path: outputs/user_analysis.csv
    description: Users per category with average value.
    schema:
      fields:
        - name: category
          type: string
          title: Category
        - name: user_count
          type: integer
          title: User Count
          si:unit: count
        - name: avg_value
          type: number
          title: Average Value
          si:unit: USD
```

In the lock-file example that follows, change `sources:\n      - slug: users` to:

```yaml
    sources:
      - slug: users
        dct:license: CC-BY-4.0
```

- [ ] **Step 5: Key Fields section**

Replace the whole "### Key Fields" section with:

```markdown
### Key fields

The full list, per level and with rule levels, is [datasets-yaml-reference.md](references/datasets-yaml-reference.md). The ones you write most:

**Every dataset (MUST):** `title` (human-readable), `name` (kebab-case identifier used in code), `path` (relative to the project root). `description` is SHOULD.

**Inputs (MUST, by the capture rule):** `source` with `title`, `dct:publisher` (object with `rdfs:label`), a link (`"@id"`, `dcat:downloadURL` or `dcat:landingPage`), `dct:license`; plus `prov:generatedAtTime` and `prov:wasGeneratedBy.dct:type` on the dataset. SHOULD: `skos:altLabel` on the publisher, `dct:issued`, `dct:modified`; for a publication also `dct:creator` and `"@id"`. MAY: `dct:isPartOf`, `dct:bibliographicCitation`, `prov:wasAttributedTo` (legacy free text). See "Restructuring sources".

**Fields (`schema.fields`):** `name` and `type` (MUST; types: string, integer, number, boolean, date, datetime, time, year, yearmonth, duration, array, object, any, plus plugin types such as geometry). SHOULD: `description`, and `si:unit` on integer/number fields (a Pint string like `kg`, `USD`, `km**2`, or a QUDT IRI). `title` is the chart label.

**Outputs:** `licenses: [{name: <SPDX>}]` on the dataset or on the package.
```

- [ ] **Step 6: "What goes where" table and the legacy note**

In the table under "### What goes where" replace the first three rows with:

```markdown
| `title`, `name`, `path` | ✅ | — |
| `source:` block (URLs, attribution, license), `prov:generatedAtTime`, `prov:wasGeneratedBy` | ✅ | — |
| `schema.fields:` (incl. `title`, `description`, `si:unit`) | ✅ | — |
```

Replace the sentence "This includes overriding an inferred field type, adding a `description` or `dct:title`, attaching custom RDF properties, or pre-registering an output before strict-mode runs." with "This includes overriding an inferred field type, adding a `description` or `title`, attaching RDF properties, or pre-registering an output before strict-mode runs."

Replace the "> **Legacy projects:**" paragraph with:

```markdown
> **Legacy projects:** a project last touched under sunstone-py < 1.20 uses the old key names, and one under < 1.7 may keep lineage inline in `datasets.yaml`. Run `sunstone migrate` (key names, comments kept) and, if lineage is inline, `sunstone dataset migrate`; then commit both files. Both commands are no-ops on a current project.
```

- [ ] **Step 7: Validation section**

Replace the "## Validation" section with:

````markdown
## Validation

Run the linter before committing. It checks every key against the allowed set (R301–R307), provenance (R102, R311–R315), lineage (R321–R323), field types (R331), units (R341), naming (R001–R008, R104, R351) and methodology (R361, R362):

```bash
sunstone lint --json --warnings-as-errors   # the done criterion: no violations
sunstone lint                               # human-readable
sunstone dataset resolve --check            # lock file is current
```

Every JSON violation carries `rule_id`, `path` (the key, e.g. `inputs[3].source.attributedTo`) and `fix`. Fix the key named by `path`; when the fix says to search, run the `sunstone vocab search` command it gives and use one of its results. When the fix says to run `sunstone migrate`, run it once for the whole project. R102, R311 and R315 under a `source` path mean the source still needs restructuring (see "Restructuring sources").
````

- [ ] **Step 8: References list and the non-tabular section**

In "## References", replace the `datasets-yaml-schema.md` bullet with:

```markdown
- [datasets-yaml-reference.md](references/datasets-yaml-reference.md): every allowed `datasets.yaml` key per level with its class (dp, config, rdf, jsonld), rule level and an example; the agent object and YAML anchor rule; the alias table (old key to new key); the lint rule list. Generated by sunstone-py, synced with `scripts/sync-dataset-reference.py`.
```

In "## Non-tabular assets", the sentence "Register them in `datasets.yaml` with a full `source:` block." stays; no other change.

- [ ] **Step 9: Check and commit**

```bash
grep -n "attributedTo\|acquiredAt\|acquisitionMethod\|slug:\|location:\|dct:title\|  unit:" plugins/sunstone-core/skills/dataset/SKILL.md
grep -n "dct:publisher: [A-Za-z]" plugins/sunstone-core/skills/dataset/SKILL.md
```

Expected for the first grep: the sentence in "## Writing keys in datasets.yaml" that lists the old keys, the lock-file `slug:` line (lock entries keep `slug`), and the "Before" example and steps 2 and 3 in "## Restructuring sources" (they name `prov:wasAttributedTo` on purpose). Expected for the second grep: no match (a publisher is never a bare string; `&name` anchors and `*name` aliases are fine). Then:

```bash
uv run python scripts/validate-claude-metadata.py && scripts/check-plugin-structure.sh
git add plugins/sunstone-core/skills/dataset/SKILL.md
git commit -m "docs(dataset): teach the DP 2.0 key form, vocab search and the lint done-criterion"
```

---

### Task 3: References in new key form

**Files:**
- Modify: `plugins/sunstone-core/skills/dataset/references/registry-patterns.md`, `references/api-reference.md`, `references/troubleshooting.md`

- [ ] **Step 1: `registry-patterns.md`**

Replace the YAML inside the "### Cross-Project Lineage Tracking" docstring with:

```yaml
inputs:
  - title: Aggregated Data from Project A
    name: project-a-aggregated
    path: inputs/project_a_aggregated.csv
    source:
      title: Project A Analysis Pipeline
      dct:publisher:
        rdfs:label: Data Science Team
      dcat:downloadURL: file:///path/to/project_a/outputs/aggregated.csv
      dct:license: CC-BY-4.0
    prov:generatedAtTime: '2025-01-16'
    prov:wasGeneratedBy:
      '@type': prov:Activity
      dct:type: import
```

Replace the "### Basic URL Fetching" YAML with:

```yaml
# In datasets.yaml
inputs:
  - title: Remote Dataset
    name: remote-data
    path: inputs/remote_data.csv
    source:
      title: Data Provider Export
      dct:publisher:
        rdfs:label: Data Provider
      dcat:downloadURL: https://example.com/data.csv
      dct:license: CC-BY-4.0
```

and change the sentence above it to "When `source.dcat:downloadURL` contains a URL, sunstone downloads the file on first read if the local copy does not exist:". Around line 124, the Python dict with `'attributedTo': 'Sales Team'` is a batch-registration helper: rename the keys in that dict to `'title'`, `'dcat:downloadURL'`, `'dct:publisher': {'rdfs:label': 'Sales Team'}`, `'dct:license'` and the dataset keys to `'title'`, `'name'`, `'path'`, so the generated YAML is in new form (read the surrounding function and keep its behavior).

- [ ] **Step 2: `api-reference.md`**

Replace the "### Source" attribute list with:

```markdown
**Attributes (Python names; the YAML keys differ):**
- `name` (str): Source title (YAML `title`)
- `location` (SourceLocation): `.data` (`dcat:downloadURL`), `.about` (`dcat:landingPage`), `.metadata` (`rdfs:seeAlso`), `.access` (`dcat:accessURL`)
- `id` (str | None): YAML `"@id"` (DOI as `https://doi.org/<doi>`, or another IRI)
- `attributed_to` (str | Agent): YAML `prov:wasAttributedTo` (legacy free text; empty string when absent)
- `acquired_at` (str | None): dataset `prov:generatedAtTime`
- `acquisition_method` (str | None): dataset `prov:wasGeneratedBy.dct:type`
- `license` (str | None): `dct:license`
- `publisher` (SourceAgent | None): `dct:publisher`; `SourceAgent(label, alt_label=None, id=None)` maps `rdfs:label`, `skos:altLabel`, `"@id"`
- `creator` (list[SourceAgent] | None): `dct:creator`
- `issued`, `updated`, `bibliographic_citation` (str | None): `dct:issued`, `dct:modified`, `dct:bibliographicCitation`
- `is_part_of` (dict | None): `dct:isPartOf` node as written, e.g. `{"rdfs:label": "Aquaculture Reports 26"}`
```

Function signatures (`slug: str`, `location: str`, `license: Optional[str]`) are Python parameter names and stay unchanged. Add one sentence under `add_output_dataset`: "Writes the entry in the new key form (`title`, `name`, `path`, `schema.fields`, `licenses`)."

- [ ] **Step 3: `troubleshooting.md`**

Rewrite every `datasets.yaml` snippet to the new form: `slug:` → `name:`, `location:` → `path:`, `name:` (human-readable) → `title:`; update the prose next to them ("Typo in slug" → "Typo in name", `grep "slug:" datasets.yaml` → `grep "name:" datasets.yaml`, "Verify the slug matches exactly" → "Verify the name matches exactly"). The indentation example near line 415 becomes `name: dataset-name     # 4 spaces (item properties)`. Lines 472–488 (duplicate-slug examples) use `name:`. Lines 528–537 (absolute vs relative) use `path:`. Keep the minimum-version lines at 1.13 only in the "Verify installation" step if they refer to the data-platform plugin; otherwise raise them to 1.20 to match `SKILL.md`.

Add a troubleshooting entry at the end of the file:

````markdown
## Lint reports R301 "unknown key"

The key is not a Data Package property, a config key or an RDF property. Either it is an old sunstone key (run `sunstone migrate`), or it is invented. Find the right key:

```bash
sunstone vocab search "<what the key means>" --at <path from the violation, without [n]>
```

Use a returned `curie` as the key. R302 means the prefix is not declared: add it under `rdfPrefixes:` or use a standard prefix (`dct`, `dcat`, `prov`, `schema`, `skos`, `rdfs`, `qudt`, `si`, `dcat-si`). R303 means the term does not exist in that vocabulary: search again and pick a listed term.

## Lint reports R102, R311 or R315 on a source

The source is still free text or has a DOI in the wrong key. R102 (error): `dct:publisher` must be an object with `rdfs:label`, and the source needs a link (`"@id"`, `dcat:downloadURL` or `dcat:landingPage`) and `dct:license`; a bare `dct:publisher: Name` from before 1.20 is rewritten to `{rdfs:label: Name}` by `sunstone migrate`. R315 (error): move the `doi.org` URL from `dcat:landingPage`/`dcat:downloadURL` to `"@id"`. R311 (warning): add `skos:altLabel` on the publisher, `dct:issued`, `dct:modified`, and for a paper `dct:creator` and `"@id"`. Follow "Restructuring sources" in SKILL.md; the source is done when `sunstone lint --json --warnings-as-errors` reports nothing under its path.

## The same publisher appears many times

Write the object once with an anchor and reuse it with an alias in the same file:

```yaml
      dct:publisher: &ssb
        rdfs:label: Statistics Norway
        skos:altLabel: SSB
# later, in the same file
      dct:publisher: *ssb
```

Anchors do not cross include files; each include file anchors its own. Saving through sunstone keeps anchors and aliases as written.
````

- [ ] **Step 4: Check and commit**

```bash
grep -rn "attributedTo\|acquiredAt\|acquisitionMethod\|slug:\|location:\|dct:title" plugins/sunstone-core/skills/dataset/references/*.md | grep -v datasets-yaml-reference.md
```

Expected: no matches except Python parameter names in `api-reference.md` (`slug: str`, `location: str`) and the lock-file `slug:` lines. Then:

```bash
uv run python scripts/validate-claude-metadata.py && scripts/check-plugin-structure.sh && claude plugin validate . && uv run pytest scripts/tests -q
git add plugins/sunstone-core/skills/dataset/references
git commit -m "docs(dataset): references use the DP 2.0 key form"
```

---

### Task 4: Pull request

- [ ] **Step 1:** Push the branch and open a PR titled "dataset skill: DP 2.0 key form, structured sources, vocab search, lint done-criterion" with label `bump-minor` (do not edit `version`). The body lists: reference now generated and synced from sunstone-py 1.20; old keys removed from all examples; the three new instructions (never invent a key, `sunstone vocab search --at`, `sunstone lint --json --warnings-as-errors` is the done criterion); the "Restructuring sources" procedure (DOI in `"@id"`, publisher and authors as agent objects, anchors for repeats, lint as the checklist), which is how the org repos get ready for sunstone-py 2.0 (spec "Releases").
- [ ] **Step 2:** Note in the PR that `plugins/sunstone-core/skills/data-package/references/package-rules.md` still shows `attributedTo` and is out of this plan's scope (C10 covers the dataset skill only); file a follow-up issue.

## Self-review notes

- Spec C10 coverage: reference replaced by the generated doc with a sync script (Task 1); "never write a key absent from the reference", `vocab search --at --json`, done-criterion (Task 2 Steps 2 and 7); examples in new form (Tasks 2 and 3).
- Spec "Source references" coverage: the skill teaches the parts table, the split procedure with a real before/after, agent objects with YAML anchors (no lookup table), DOI in `"@id"` (R315), and lint as the checklist (Task 2 Step 2 "Restructuring sources", Step 1 capture rule, Step 5 key fields, Step 7 validation; Task 3 troubleshooting entries and `api-reference.md` `SourceAgent` attributes).
- Nothing in this plan needs Opus; every step is a text replacement with the replacement given, plus one small script with tests.
