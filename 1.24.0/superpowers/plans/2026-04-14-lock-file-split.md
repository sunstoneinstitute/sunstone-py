# Lock File Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `datasets.yaml` into a human-authored file and an auto-generated `datasets.lock.yaml` for lineage and resolved metadata.

**Architecture:** `DatasetsManager` gains a `_lock_data` dict alongside `_data`, loaded from `datasets.lock.yaml`. Lineage writes go to the lock file. Reading merges both files into the in-memory model. A migration command extracts inline lineage into the lock file.

**Tech Stack:** Python, ruamel.yaml, typer, pytest

**Note:** The spec names the command `sunstone dataset lock`, but the existing `lock` command means "enable strict mode." This plan renames the old commands to `strict`/`unstrict` (Task 4) and names the new command `resolve` (Task 5). Once the old commands are removed in a future version, `resolve` can be aliased to `lock` if desired.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/sunstone/datasets.py` | Add lock file load/save/merge, redirect lineage writes |
| Modify | `src/sunstone/cli.py` | Rename lock/unlock → strict/unstrict, add resolve/check/migrate commands |
| Create | `tests/test_lock_file.py` | All lock file tests |
| Modify | `tests/testdata/UNMembersProject/datasets.yaml` | Remove inline lineage (after migration test) |
| Create | `tests/testdata/UNMembersProject/datasets.lock.yaml` | Test fixture for lock file |

---

### Task 1: Load lock file alongside datasets.yaml

**Files:**
- Modify: `src/sunstone/datasets.py:66-115`
- Create: `tests/test_lock_file.py`

- [ ] **Step 1: Write failing test for lock file loading**

```python
# tests/test_lock_file.py
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from sunstone.datasets import DatasetsManager

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)


def _write_yaml(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        _yaml.dump(data, f)


@pytest.fixture()
def lock_project(tmp_path: Path) -> Path:
    """Minimal project with datasets.yaml and datasets.lock.yaml."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "inputs").mkdir()
    (project / "outputs").mkdir()

    # Create a minimal CSV so location resolves
    (project / "inputs" / "data.csv").write_text("a,b\n1,2\n")

    _write_yaml(
        project / "datasets.yaml",
        {
            "inputs": [
                {
                    "name": "Input Data",
                    "slug": "input-data",
                    "location": "inputs/data.csv",
                    "fields": [
                        {"name": "a", "type": "integer"},
                        {"name": "b", "type": "integer"},
                    ],
                }
            ],
            "outputs": [
                {
                    "name": "Output Data",
                    "slug": "output-data",
                    "location": "outputs/output.csv",
                    "fields": [{"name": "a", "type": "integer"}],
                }
            ],
        },
    )

    _write_yaml(
        project / "datasets.lock.yaml",
        {
            "inputs": [
                {
                    "slug": "input-data",
                    "content_hash": "sha256:abc123",
                    "row_count": 1,
                }
            ],
            "outputs": [
                {
                    "slug": "output-data",
                    "content_hash": "sha256:def456",
                    "created_at": "2026-04-10T14:23:01.508497",
                    "sources": [{"slug": "input-data"}],
                }
            ],
        },
    )

    return project


class TestLockFileLoading:
    def test_load_lock_file(self, lock_project: Path) -> None:
        manager = DatasetsManager(lock_project)
        assert manager.lock_data is not None
        assert len(manager.lock_data.get("outputs", [])) == 1
        assert manager.lock_data["outputs"][0]["slug"] == "output-data"

    def test_load_without_lock_file(self, tmp_path: Path) -> None:
        """Lock file is optional — loading succeeds without it."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {"inputs": [], "outputs": []},
        )
        manager = DatasetsManager(project)
        assert manager.lock_data == {}

    def test_lock_file_path_property(self, lock_project: Path) -> None:
        manager = DatasetsManager(lock_project)
        expected = lock_project / "datasets.lock.yaml"
        assert manager.lock_file == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock_file.py::TestLockFileLoading -v`
Expected: FAIL — `DatasetsManager` has no `lock_data` attribute

- [ ] **Step 3: Implement lock file loading**

In `src/sunstone/datasets.py`, modify `__init__` and `_load`:

```python
# In __init__, after self.datasets_file assignment (around line 88):
self.lock_file = self.datasets_file.parent / "datasets.lock.yaml"

# Add after self._data initialization in __init__:
self._lock_data: Dict[str, Any] = {}
```

```python
# In _load(), after the existing logic (after line 110):

# Load lock file if present
if self.lock_file.exists():
    with open(self.lock_file, "r") as f:
        self._lock_data = _yaml.load(f) or {}
else:
    self._lock_data = {}
```

Add a property for public access:

```python
@property
def lock_data(self) -> Dict[str, Any]:
    """Return the lock file data."""
    return self._lock_data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lock_file.py::TestLockFileLoading -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/datasets.py tests/test_lock_file.py
git commit -m "feat: load datasets.lock.yaml alongside datasets.yaml"
```

---

### Task 2: Merge lineage from lock file into parsed datasets

When a lock file exists, lineage for outputs should come from the lock file rather than inline `lineage:` blocks. The lock file takes precedence.

**Files:**
- Modify: `src/sunstone/datasets.py:407-479` (`_parse_dataset`)
- Modify: `tests/test_lock_file.py`

- [ ] **Step 1: Write failing test for lineage merge**

```python
# Add to tests/test_lock_file.py

class TestLockFileMerge:
    def test_output_lineage_from_lock_file(self, lock_project: Path) -> None:
        """Output lineage should come from lock file, not inline."""
        manager = DatasetsManager(lock_project)
        outputs = manager.get_all_outputs()
        output = next(o for o in outputs if o.slug == "output-data")
        assert output.was_derived_from is not None
        assert len(output.was_derived_from) == 1
        assert output.was_derived_from[0].slug == "input-data"

    def test_inline_lineage_fallback(self, tmp_path: Path) -> None:
        """Without lock file, inline lineage still works."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {"name": "In", "slug": "in", "location": "in.csv"}
                ],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:abc",
                            "created_at": "2026-01-01T00:00:00",
                            "sources": [{"slug": "in"}],
                        },
                    }
                ],
            },
        )
        manager = DatasetsManager(project)
        outputs = manager.get_all_outputs()
        output = next(o for o in outputs if o.slug == "out")
        assert output.was_derived_from is not None
        assert output.was_derived_from[0].slug == "in"

    def test_lock_file_lineage_overrides_inline(self, tmp_path: Path) -> None:
        """Lock file lineage takes precedence over inline."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {"name": "Old", "slug": "old-source", "location": "old.csv"},
                    {"name": "New", "slug": "new-source", "location": "new.csv"},
                ],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:stale",
                            "sources": [{"slug": "old-source"}],
                        },
                    }
                ],
            },
        )
        _write_yaml(
            project / "datasets.lock.yaml",
            {
                "outputs": [
                    {
                        "slug": "out",
                        "content_hash": "sha256:fresh",
                        "sources": [{"slug": "new-source"}],
                    }
                ],
            },
        )
        manager = DatasetsManager(project)
        outputs = manager.get_all_outputs()
        output = next(o for o in outputs if o.slug == "out")
        assert output.was_derived_from[0].slug == "new-source"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock_file.py::TestLockFileMerge -v`
Expected: `test_output_lineage_from_lock_file` FAILS (no lineage in datasets.yaml, lock file not merged yet). The inline fallback test should already pass.

- [ ] **Step 3: Implement lineage merge in _parse_dataset**

In `src/sunstone/datasets.py`, modify `_parse_dataset` to check the lock file for lineage data:

```python
# Add a helper method to DatasetsManager (before _parse_dataset):
def _get_lock_entry(self, slug: str, dataset_type: str) -> Dict[str, Any]:
    """Get the lock file entry for a dataset by slug."""
    section = "inputs" if dataset_type == "input" else "outputs"
    for entry in self._lock_data.get(section, []):
        if entry.get("slug") == slug:
            return dict(entry)
    return {}
```

In `_parse_dataset`, after extracting the slug (around line 415) and before the lineage parsing block (around line 430), add lock file merge logic:

```python
# Get lock file entry for this dataset
slug = dataset_data.get("slug", "")
lock_entry = self._get_lock_entry(slug, dataset_type)

# For lineage: lock file takes precedence over inline
lineage_data = lock_entry if lock_entry else dataset_data.get("lineage", {})
```

Then update the lineage parsing block (lines 430-460) to use `lineage_data` instead of `dataset_data.get("lineage", {})`:

```python
# Replace the existing lineage parsing that reads from dataset_data["lineage"]
# with reading from lineage_data instead:
was_derived_from = None
generated_at_time = None
was_generated_by = None
field_derivations_parsed = None

if lineage_data:
    sources = lineage_data.get("sources", [])
    if sources:
        was_derived_from = [
            EntityRef(slug=s["slug"], namespace=s.get("namespace"))
            for s in sources
        ]
    created_at = lineage_data.get("created_at")
    if created_at:
        generated_at_time = datetime.fromisoformat(created_at)
    activity_data = lineage_data.get("activity")
    if activity_data:
        was_generated_by = ActivityRef(id=activity_data["id"])
    raw_derivations = lineage_data.get("field_derivations")
    if raw_derivations:
        field_derivations_parsed = self._parse_field_derivations(raw_derivations)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lock_file.py::TestLockFileMerge -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest`
Expected: All tests pass (existing inline lineage tests still work via fallback)

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/datasets.py tests/test_lock_file.py
git commit -m "feat: merge output lineage from lock file with inline fallback"
```

---

### Task 3: Write lineage to lock file instead of datasets.yaml

Redirect `update_output_lineage()` to write to `datasets.lock.yaml` instead of modifying `datasets.yaml`.

**Files:**
- Modify: `src/sunstone/datasets.py:757-894` (`update_output_lineage`)
- Modify: `tests/test_lock_file.py`

- [ ] **Step 1: Write failing test for lineage written to lock file**

```python
# Add to tests/test_lock_file.py
from sunstone.lineage import LineageMetadata, DatasetMetadata, EntityRef


class TestLockFileWriting:
    def test_update_lineage_writes_to_lock_file(self, lock_project: Path) -> None:
        """Lineage updates should write to datasets.lock.yaml, not datasets.yaml."""
        manager = DatasetsManager(lock_project)

        # Create a source dataset for lineage
        source = DatasetMetadata(
            name="Input Data",
            slug="input-data",
            location="inputs/data.csv",
        )
        lineage = LineageMetadata(sources=[source])

        manager.update_output_lineage(
            slug="output-data",
            lineage=lineage,
            content_hash="sha256:newvalue",
        )

        # Lock file should have the lineage
        with open(lock_project / "datasets.lock.yaml") as f:
            lock_data = _yaml.load(f)
        lock_output = next(
            o for o in lock_data["outputs"] if o["slug"] == "output-data"
        )
        assert lock_output["content_hash"] == "sha256:newvalue"

        # datasets.yaml should NOT have lineage
        with open(lock_project / "datasets.yaml") as f:
            yaml_data = _yaml.load(f)
        yaml_output = next(
            o for o in yaml_data["outputs"] if o["slug"] == "output-data"
        )
        assert "lineage" not in yaml_output

    def test_update_lineage_creates_lock_file(self, tmp_path: Path) -> None:
        """If no lock file exists, one should be created."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "outputs").mkdir()
        (project / "inputs" / "data.csv").write_text("a\n1\n")

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {"name": "In", "slug": "in", "location": "inputs/data.csv"}
                ],
                "outputs": [
                    {"name": "Out", "slug": "out", "location": "outputs/out.csv"}
                ],
            },
        )

        assert not (project / "datasets.lock.yaml").exists()

        manager = DatasetsManager(project)
        source = DatasetMetadata(name="In", slug="in", location="inputs/data.csv")
        lineage = LineageMetadata(sources=[source])
        manager.update_output_lineage(
            slug="out", lineage=lineage, content_hash="sha256:first"
        )

        assert (project / "datasets.lock.yaml").exists()
        with open(project / "datasets.lock.yaml") as f:
            lock_data = _yaml.load(f)
        assert lock_data["outputs"][0]["content_hash"] == "sha256:first"

    def test_update_lineage_preserves_other_lock_entries(
        self, lock_project: Path
    ) -> None:
        """Updating one output shouldn't clobber other lock entries."""
        # Add a second output
        with open(lock_project / "datasets.yaml") as f:
            data = _yaml.load(f)
        data["outputs"].append(
            {"name": "Second", "slug": "second-output", "location": "outputs/second.csv"}
        )
        _write_yaml(lock_project / "datasets.yaml", data)

        # Add second output to lock file
        with open(lock_project / "datasets.lock.yaml") as f:
            lock = _yaml.load(f)
        lock["outputs"].append(
            {"slug": "second-output", "content_hash": "sha256:keep-this"}
        )
        _write_yaml(lock_project / "datasets.lock.yaml", lock)

        manager = DatasetsManager(lock_project)
        source = DatasetMetadata(
            name="Input Data", slug="input-data", location="inputs/data.csv"
        )
        lineage = LineageMetadata(sources=[source])
        manager.update_output_lineage(
            slug="output-data", lineage=lineage, content_hash="sha256:updated"
        )

        with open(lock_project / "datasets.lock.yaml") as f:
            result = _yaml.load(f)
        second = next(o for o in result["outputs"] if o["slug"] == "second-output")
        assert second["content_hash"] == "sha256:keep-this"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock_file.py::TestLockFileWriting -v`
Expected: FAIL — lineage still written to datasets.yaml

- [ ] **Step 3: Add lock file save method**

In `src/sunstone/datasets.py`, add `_save_lock`:

```python
def _save_lock(self) -> None:
    """Save the current lock data to datasets.lock.yaml."""
    with open(self.lock_file, "w") as f:
        # Write a comment header
        f.write("# Auto-generated by sunstone. Do not edit manually.\n")
        _yaml.dump(self._lock_data, f)
```

- [ ] **Step 4: Refactor update_output_lineage to write to lock file**

Modify `update_output_lineage` (lines 757-894). The key changes:

1. Find the dataset in `self._data["outputs"]` by slug (unchanged)
2. Build the lineage dict (unchanged)
3. Instead of writing to `self._data` and doing the atomic temp-file dance on `datasets.yaml`, write to `self._lock_data` and save via `_save_lock()`

```python
def update_output_lineage(
    self,
    slug: str,
    lineage: LineageMetadata,
    content_hash: str,
    strict: bool = False,
    context: Optional[dict] = None,
    transformation_params: Optional[dict] = None,
    activity: Optional[Activity] = None,
) -> None:
    # ... existing validation and hash checking logic stays the same ...
    # ... existing lineage_data dict building stays the same ...

    # Ensure lock data has outputs list
    if "outputs" not in self._lock_data:
        self._lock_data["outputs"] = []

    # Find or create lock entry for this slug
    lock_entry = None
    for entry in self._lock_data["outputs"]:
        if entry.get("slug") == slug:
            lock_entry = entry
            break

    if lock_entry is None:
        lock_entry = {"slug": slug}
        self._lock_data["outputs"].append(lock_entry)

    # Update lock entry with lineage data
    lock_entry.update(lineage_data)

    if strict:
        # In strict mode, check if content hash changed
        # (the existing strict check compared files; now we compare hashes)
        existing_hash = None
        for entry in self._lock_data.get("outputs", []):
            if entry.get("slug") == slug:
                existing_hash = entry.get("content_hash")
                break
        if existing_hash and existing_hash != content_hash:
            raise DatasetValidationError(
                f"In strict mode, lineage metadata for '{slug}' would be updated. "
                f"Expected hash {existing_hash}, got {content_hash}."
            )

    # Save lock file
    self._save_lock()
    # Reload to pick up changes
    self._load()
```

Note: The exact refactoring will need to preserve the hash-unchanged early return and the lineage_data building logic from the existing method. Only the write target changes.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_lock_file.py::TestLockFileWriting -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest`
Expected: Some existing lineage tests may need updates since they assert lineage is in datasets.yaml. Fix any that fail by updating assertions to check datasets.lock.yaml instead.

- [ ] **Step 7: Fix any broken existing tests**

Tests in `test_lineage_flow.py` and `test_lineage_persistence.py` that check `datasets.yaml` for lineage blocks need to be updated to check `datasets.lock.yaml`. The pattern:

```python
# Old pattern:
with open(project / "datasets.yaml") as f:
    data = yaml.load(f)
output = next(d for d in data["outputs"] if d["slug"] == "merged-output")
lineage = output["lineage"]

# New pattern:
with open(project / "datasets.lock.yaml") as f:
    lock_data = yaml.load(f)
lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "merged-output")
# lineage fields are now at lock entry top level, not nested under "lineage"
assert "content_hash" in lock_output
assert "sources" in lock_output
```

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/datasets.py tests/test_lock_file.py tests/test_lineage_flow.py tests/test_lineage_persistence.py
git commit -m "feat: write lineage to datasets.lock.yaml instead of datasets.yaml"
```

---

### Task 4: Rename CLI commands — lock/unlock → strict/unstrict

The existing `sunstone dataset lock` and `sunstone dataset unlock` commands toggle strict mode. These need to be renamed to free up `lock` for the lock file command.

**Files:**
- Modify: `src/sunstone/cli.py:761-833`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for renamed commands**

```python
# Add to tests/test_cli.py — find the existing test class/pattern and add:

def test_dataset_strict_command(self, project_copy: Path) -> None:
    """The 'strict' command should enable strict mode."""
    from typer.testing import CliRunner
    from sunstone.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["dataset", "strict", "-f", str(project_copy / "datasets.yaml")],
    )
    assert result.exit_code == 0
    assert "Locked" in result.output or "strict" in result.output.lower()

def test_dataset_unstrict_command(self, project_copy: Path) -> None:
    """The 'unstrict' command should disable strict mode."""
    from typer.testing import CliRunner
    from sunstone.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["dataset", "unstrict", "-f", str(project_copy / "datasets.yaml")],
    )
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "strict" -v`
Expected: FAIL — no "strict" subcommand exists

- [ ] **Step 3: Rename commands in cli.py**

In `src/sunstone/cli.py`, rename the commands at lines 761-833:

```python
@dataset_app.command("strict")
def dataset_strict(
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
    datasets: Optional[list[str]] = typer.Argument(None, autocompletion=complete_dataset_slugs),
) -> None:
    """Enable strict mode for datasets.

    If no datasets are specified, locks all datasets.
    """
    # ... same body as current dataset_lock ...


@dataset_app.command("unstrict")
def dataset_unstrict(
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
    datasets: Optional[list[str]] = typer.Argument(None, autocompletion=complete_dataset_slugs),
) -> None:
    """Disable strict mode for datasets.

    If no datasets are specified, unlocks all datasets.
    """
    # ... same body as current dataset_unlock ...
```

Update the output messages to say "Enabled strict mode" / "Disabled strict mode" instead of "Locked" / "Unlocked".

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k "strict" -v`
Expected: PASS

- [ ] **Step 5: Fix any existing tests that reference old command names**

Run: `uv run pytest tests/test_cli.py -v`
Expected: Fix any tests that invoke the old `lock`/`unlock` commands.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py
git commit -m "refactor: rename dataset lock/unlock CLI commands to strict/unstrict"
```

---

### Task 5: Add `sunstone dataset resolve` command

The new command resolves metadata and writes `datasets.lock.yaml`. Named `resolve` rather than reusing `lock` to clearly distinguish from the old strict-mode command during the transition.

**Files:**
- Modify: `src/sunstone/cli.py`
- Modify: `tests/test_lock_file.py`

- [ ] **Step 1: Write failing test for resolve command**

```python
# Add to tests/test_lock_file.py
from typer.testing import CliRunner
from sunstone.cli import app


class TestResolveCommand:
    def test_resolve_creates_lock_file(self, tmp_path: Path) -> None:
        """sunstone dataset resolve should create datasets.lock.yaml."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "outputs").mkdir()
        (project / "inputs" / "data.csv").write_text("name,age\nalice,30\nbob,25\n")
        (project / "outputs" / "out.csv").write_text("name\nalice\n")

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {
                        "name": "People",
                        "slug": "people",
                        "location": "inputs/data.csv",
                        "fields": [
                            {"name": "name", "type": "string"},
                            {"name": "age", "type": "integer"},
                        ],
                    }
                ],
                "outputs": [
                    {
                        "name": "Names",
                        "slug": "names",
                        "location": "outputs/out.csv",
                        "fields": [{"name": "name", "type": "string"}],
                    }
                ],
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dataset", "resolve", "-f", str(project / "datasets.yaml")],
        )
        assert result.exit_code == 0

        lock_path = project / "datasets.lock.yaml"
        assert lock_path.exists()

        with open(lock_path) as f:
            lock = _yaml.load(f)
        # Input should have content_hash resolved from local file
        input_entry = next(i for i in lock["inputs"] if i["slug"] == "people")
        assert "content_hash" in input_entry

    def test_resolve_check_mode(self, lock_project: Path) -> None:
        """--check should exit 0 when lock file is up to date."""
        # First resolve to create a fresh lock
        runner = CliRunner()
        runner.invoke(
            app,
            ["dataset", "resolve", "-f", str(lock_project / "datasets.yaml")],
        )

        # Now check — should be up to date
        result = runner.invoke(
            app,
            [
                "dataset", "resolve", "--check",
                "-f", str(lock_project / "datasets.yaml"),
            ],
        )
        assert result.exit_code == 0

    def test_resolve_check_fails_when_stale(self, lock_project: Path) -> None:
        """--check should exit 1 when lock file is stale."""
        # Modify the input file to make the lock stale
        (lock_project / "inputs" / "data.csv").write_text("a,b\n99,99\n")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "dataset", "resolve", "--check",
                "-f", str(lock_project / "datasets.yaml"),
            ],
        )
        assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock_file.py::TestResolveCommand -v`
Expected: FAIL — no "resolve" subcommand

- [ ] **Step 3: Implement resolve command**

In `src/sunstone/cli.py`, add the resolve command to `dataset_app`:

```python
@dataset_app.command("resolve")
def dataset_resolve(
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
    check: bool = typer.Option(False, "--check", help="Exit non-zero if lock file is out of date"),
    offline: bool = typer.Option(False, "--offline", help="Skip network calls, only resolve local files"),
) -> None:
    """Resolve dataset metadata and write datasets.lock.yaml.

    Iterates all inputs and outputs, resolves metadata from URL handlers
    (content hashes, field inference), and writes the lock file.

    Use --check in CI to verify the lock file is up to date.
    """
    import hashlib

    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)

    lock_data: dict = {"inputs": [], "outputs": []}

    # Resolve inputs
    for ds in manager.get_all_inputs():
        entry: dict = {"slug": ds.slug}
        location = ds.location
        abs_path = manager.get_absolute_path(location)

        # For local files: compute content hash
        if abs_path.exists():
            with open(abs_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            entry["content_hash"] = f"sha256:{file_hash}"

        lock_data["inputs"].append(entry)

    # Resolve outputs
    for ds in manager.get_all_outputs():
        entry = {"slug": ds.slug}
        abs_path = manager.get_absolute_path(ds.location)

        # Compute content hash if output exists
        if abs_path.exists():
            with open(abs_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            entry["content_hash"] = f"sha256:{file_hash}"

        # Preserve existing lineage from lock file
        existing = manager._get_lock_entry(ds.slug, "output")
        for key in ("created_at", "sources", "activity", "field_derivations"):
            if key in existing:
                entry[key] = existing[key]

        lock_data["outputs"].append(entry)

    if check:
        # Compare with existing lock file
        existing_lock = manager.lock_data
        if lock_data != existing_lock:
            typer.echo("Lock file is out of date. Run 'sunstone dataset resolve' to update.", err=True)
            sys.exit(1)
        else:
            typer.echo("Lock file is up to date.")
            return

    # Write lock file
    manager._lock_data = lock_data
    manager._save_lock()

    input_count = len(lock_data["inputs"])
    output_count = len(lock_data["outputs"])
    typer.echo(f"Resolved {input_count} input(s) and {output_count} output(s) to datasets.lock.yaml")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lock_file.py::TestResolveCommand -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_lock_file.py
git commit -m "feat: add 'sunstone dataset resolve' command for lock file generation"
```

---

### Task 6: Add `sunstone dataset migrate` command

Extracts inline lineage from `datasets.yaml` into `datasets.lock.yaml` and updates `.gitattributes`.

**Files:**
- Modify: `src/sunstone/cli.py`
- Modify: `tests/test_lock_file.py`

- [ ] **Step 1: Write failing test for migrate command**

```python
# Add to tests/test_lock_file.py

class TestMigrateCommand:
    def test_migrate_extracts_lineage(self, tmp_path: Path) -> None:
        """migrate should move inline lineage to lock file."""
        project = tmp_path / "project"
        project.mkdir()

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {"name": "In", "slug": "in", "location": "in.csv"}
                ],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:abc123",
                            "created_at": "2026-01-01T00:00:00",
                            "sources": [{"slug": "in", "name": "In", "location": "in.csv"}],
                        },
                    }
                ],
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )
        assert result.exit_code == 0

        # datasets.yaml should no longer have lineage
        with open(project / "datasets.yaml") as f:
            yaml_data = _yaml.load(f)
        yaml_output = next(o for o in yaml_data["outputs"] if o["slug"] == "out")
        assert "lineage" not in yaml_output

        # datasets.lock.yaml should have the lineage
        with open(project / "datasets.lock.yaml") as f:
            lock_data = _yaml.load(f)
        lock_output = next(o for o in lock_data["outputs"] if o["slug"] == "out")
        assert lock_output["content_hash"] == "sha256:abc123"
        assert lock_output["sources"][0]["slug"] == "in"

    def test_migrate_adds_gitattributes_in_git_repo(self, tmp_path: Path) -> None:
        """migrate should add .gitattributes only inside a git repo."""
        import subprocess

        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True)

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {"content_hash": "sha256:abc"},
                    }
                ],
            },
        )

        runner = CliRunner()
        runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )

        gitattributes = project / ".gitattributes"
        assert gitattributes.exists()
        assert "datasets.lock.yaml" in gitattributes.read_text()
        assert "linguist-generated=true" in gitattributes.read_text()

    def test_migrate_skips_gitattributes_outside_git(self, tmp_path: Path) -> None:
        """migrate should not create .gitattributes outside a git repo."""
        project = tmp_path / "project"
        project.mkdir()

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {"content_hash": "sha256:abc"},
                    }
                ],
            },
        )

        runner = CliRunner()
        runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )

        assert not (project / ".gitattributes").exists()

    def test_migrate_noop_without_inline_lineage(self, tmp_path: Path) -> None:
        """migrate with no inline lineage should report nothing to migrate."""
        project = tmp_path / "project"
        project.mkdir()

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {"name": "Out", "slug": "out", "location": "out.csv"}
                ],
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )
        assert result.exit_code == 0
        assert "nothing to migrate" in result.output.lower() or "no inline" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock_file.py::TestMigrateCommand -v`
Expected: FAIL — no "migrate" subcommand

- [ ] **Step 3: Implement migrate command**

```python
@dataset_app.command("migrate")
def dataset_migrate(
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
) -> None:
    """Migrate inline lineage from datasets.yaml to datasets.lock.yaml.

    Extracts lineage blocks from output datasets and writes them to the lock file.
    Adds .gitattributes entry if inside a git repo.
    """
    import subprocess

    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Find outputs with inline lineage
    migrated = []
    lock_outputs: list[dict] = []

    for output in manager._data.get("outputs", []):
        lineage = output.get("lineage")
        if lineage:
            slug = output["slug"]
            lock_entry = {"slug": slug}
            lock_entry.update(lineage)
            lock_outputs.append(lock_entry)
            del output["lineage"]
            migrated.append(slug)

    if not migrated:
        typer.echo("No inline lineage found — nothing to migrate.")
        return

    # Write lock file (preserve existing entries if any)
    lock_data = dict(manager._lock_data) if manager._lock_data else {}
    if "outputs" not in lock_data:
        lock_data["outputs"] = []

    # Merge: don't duplicate slugs
    existing_slugs = {e["slug"] for e in lock_data["outputs"]}
    for entry in lock_outputs:
        if entry["slug"] not in existing_slugs:
            lock_data["outputs"].append(entry)
        else:
            # Update existing
            for existing in lock_data["outputs"]:
                if existing["slug"] == entry["slug"]:
                    existing.update(entry)
                    break

    manager._lock_data = lock_data
    manager._save_lock()

    # Save datasets.yaml without lineage
    manager._save()

    typer.echo(f"Migrated lineage for {len(migrated)} output(s): {', '.join(migrated)}")

    # Add .gitattributes if in a git repo
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            gitattributes = project_path / ".gitattributes"
            line = "datasets.lock.yaml linguist-generated=true\n"
            if gitattributes.exists():
                content = gitattributes.read_text()
                if "datasets.lock.yaml" not in content:
                    gitattributes.write_text(content.rstrip("\n") + "\n" + line)
                    typer.echo("Updated .gitattributes")
            else:
                gitattributes.write_text(line)
                typer.echo("Created .gitattributes")
    except FileNotFoundError:
        # git not installed — skip
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lock_file.py::TestMigrateCommand -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_lock_file.py
git commit -m "feat: add 'sunstone dataset migrate' command for lock file migration"
```

---

### Task 7: Migrate test data and add deprecation warning

Migrate the UNMembersProject test data to the lock file format, and add a deprecation warning when inline lineage is detected.

**Files:**
- Modify: `tests/testdata/UNMembersProject/datasets.yaml`
- Create: `tests/testdata/UNMembersProject/datasets.lock.yaml`
- Modify: `src/sunstone/datasets.py`
- Modify: `tests/test_lock_file.py`

- [ ] **Step 1: Write failing test for deprecation warning**

```python
# Add to tests/test_lock_file.py
import warnings


class TestDeprecationWarning:
    def test_inline_lineage_emits_deprecation_warning(self, tmp_path: Path) -> None:
        """Loading inline lineage should emit a DeprecationWarning."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:abc",
                            "sources": [{"slug": "in"}],
                        },
                    }
                ],
            },
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DatasetsManager(project)
            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecations) >= 1
            assert "datasets.lock.yaml" in str(deprecations[0].message)

    def test_no_warning_when_lock_file_present(self, lock_project: Path) -> None:
        """No deprecation warning when lineage is in lock file."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DatasetsManager(lock_project)
            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecations) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock_file.py::TestDeprecationWarning -v`
Expected: FAIL — no deprecation warning emitted

- [ ] **Step 3: Add deprecation warning to _load**

In `src/sunstone/datasets.py`, in `_load()`, after loading both files, check for inline lineage:

```python
# At the end of _load(), after loading lock file:
if not self.lock_file.exists():
    # Check if any output has inline lineage
    for output in self._data.get("outputs", []):
        if "lineage" in output:
            import warnings
            warnings.warn(
                "Inline lineage in datasets.yaml is deprecated. "
                "Run 'sunstone dataset migrate' to move lineage to datasets.lock.yaml.",
                DeprecationWarning,
                stacklevel=2,
            )
            break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lock_file.py::TestDeprecationWarning -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Migrate test data**

Create `tests/testdata/UNMembersProject/datasets.lock.yaml`:

```yaml
# Auto-generated by sunstone. Do not edit manually.
outputs:
  - slug: current-un-member-states
    content_hash: a4fed3f8938014e3365584eb805fd0e3fa27ab535202b80be109538300473334
    created_at: '2025-12-04T03:04:16.508497'
    sources:
      - slug: official-un-member-states
        name: Official UN Member States
        location: inputs/official_un_member_states_raw.csv
```

Remove the `lineage:` block from `tests/testdata/UNMembersProject/datasets.yaml` (lines 122-129).

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest`
Expected: All tests pass. Some tests that previously read lineage from datasets.yaml will now read it from the lock file via the merge logic in Task 2.

- [ ] **Step 7: Fix any remaining test failures**

If existing tests assert on the structure of datasets.yaml and expect a `lineage:` key, update them to read from `datasets.lock.yaml` instead.

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/datasets.py tests/testdata/UNMembersProject/datasets.yaml tests/testdata/UNMembersProject/datasets.lock.yaml tests/test_lock_file.py
git commit -m "feat: migrate test data to lock file, add deprecation warning for inline lineage"
```

---

### Task 8: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add entries to Unreleased section**

Add to the `[Unreleased]` section:

```markdown
- Added: `datasets.lock.yaml` for separating auto-generated lineage from human-authored `datasets.yaml`
- Added: `sunstone dataset resolve` command to generate lock file
- Added: `sunstone dataset migrate` command to extract inline lineage into lock file
- Changed: `sunstone dataset lock`/`unlock` renamed to `sunstone dataset strict`/`unstrict`
- Deprecated: inline `lineage:` blocks in `datasets.yaml` (use `sunstone dataset migrate`)
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update changelog for lock file split"
```
