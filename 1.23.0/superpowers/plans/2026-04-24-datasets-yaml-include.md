# datasets.yaml Include Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `datasets.yaml` to include other YAML files via a top-level `include:` list, merging their `inputs`, `outputs`, and `packages` lists into the main file at load time.

**Architecture:** A new `_merge_includes()` method in `DatasetsManager` is called early in `_load()`. It pops the `include` key, loads each referenced file, validates it (no nested includes, no disallowed top-level keys), extends the main data lists, then checks for duplicate slugs/names across files. All downstream code operates on the merged `self._data` unchanged.

**Tech Stack:** Python, ruamel.yaml (already used), pytest

**Spec:** `docs/superpowers/specs/2026-04-24-datasets-yaml-include-design.md`

---

### Task 1: Test and implement `_merge_includes()` for basic input merging

**Files:**
- Create: `tests/test_datasets_include.py`
- Modify: `src/sunstone/datasets.py:120-143` (`_load` method)

- [ ] **Step 1: Write failing test for basic include merging**

In `tests/test_datasets_include.py`:

```python
"""Tests for datasets.yaml include feature."""

from pathlib import Path

import pytest
import sunstone
from sunstone.datasets import DatasetsManager
from sunstone.exceptions import DatasetValidationError


class TestDatasetsInclude:
    """Tests for include: directive in datasets.yaml."""

    def test_basic_include_inputs(self, tmp_path: Path) -> None:
        """Inputs from an included file appear in get_all_inputs()."""
        (tmp_path / "inputs").mkdir()
        (tmp_path / "inputs" / "a.csv").write_text("col\nval")
        (tmp_path / "inputs" / "b.csv").write_text("col\nval")

        # Main file with one input and an include
        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - extra-inputs.yaml\n"
            "inputs:\n"
            "  - name: Input A\n"
            "    slug: input-a\n"
            "    location: inputs/a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        # Included file with another input
        (tmp_path / "extra-inputs.yaml").write_text(
            "inputs:\n"
            "  - name: Input B\n"
            "    slug: input-b\n"
            "    location: inputs/b.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        inputs = manager.get_all_inputs()
        slugs = [d.slug for d in inputs]
        assert "input-a" in slugs
        assert "input-b" in slugs
        assert len(inputs) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_datasets_include.py::TestDatasetsInclude::test_basic_include_inputs -v`
Expected: FAIL — `include` is not recognized, so only `input-a` is found.

- [ ] **Step 3: Implement `_merge_includes()` and call it from `_load()`**

In `src/sunstone/datasets.py`, add a new method to `DatasetsManager` and call it from `_load()`.

Add this method before `_load()`:

```python
# Top-level keys that are not allowed in included files
_INCLUDE_DISALLOWED_KEYS = frozenset({
    "defaults",
    "rdfPrefixes",
    "package",
    "publish",
    "min_sunstone_version",
})

def _merge_includes(self) -> None:
    """Merge datasets from included files into self._data.

    Pops the ``include`` key, loads each referenced YAML file,
    validates it, and extends the inputs/outputs/packages lists.
    Raises on nested includes, disallowed keys, or duplicate slugs/names.
    """
    include_list = self._data.pop("include", None)
    if not include_list:
        return

    base_dir = self.datasets_file.parent

    # Track which file defines each slug/name for error messages
    slug_origins: dict[str, str] = {}
    main_label = self.datasets_file.name
    for section in ("inputs", "outputs"):
        for entry in self._data.get(section, []):
            slug = entry.get("slug", "")
            if slug:
                slug_origins[slug] = main_label

    pkg_name_origins: dict[str, str] = {}
    for entry in self._data.get("packages", []):
        name = entry.get("name", "")
        if name:
            pkg_name_origins[name] = main_label

    for rel_path in include_list:
        inc_file = (base_dir / rel_path).resolve()
        if not inc_file.exists():
            raise FileNotFoundError(
                f"Included file not found: {rel_path} "
                f"(resolved to {inc_file})"
            )

        with open(inc_file, "r") as f:
            inc_data = _yaml.load(f) or {}

        inc_label = str(rel_path)

        # Reject nested includes
        if "include" in inc_data:
            raise DatasetValidationError(
                f"Nested includes are not supported: "
                f"{inc_label} contains an 'include:' key"
            )

        # Reject disallowed top-level keys
        bad_keys = self._INCLUDE_DISALLOWED_KEYS & set(inc_data.keys())
        if bad_keys:
            raise DatasetValidationError(
                f"Included file {inc_label} contains disallowed "
                f"top-level keys: {', '.join(sorted(bad_keys))}"
            )

        # Merge list sections
        for section in ("inputs", "outputs"):
            for entry in inc_data.get(section, []):
                slug = entry.get("slug", "")
                if slug in slug_origins:
                    raise DatasetValidationError(
                        f"Duplicate dataset slug '{slug}' found in "
                        f"'{inc_label}' and '{slug_origins[slug]}'"
                    )
                slug_origins[slug] = inc_label
            self._data.setdefault(section, []).extend(
                inc_data.get(section, [])
            )

        # Merge packages
        for entry in inc_data.get("packages", []):
            name = entry.get("name", "")
            if name in pkg_name_origins:
                raise DatasetValidationError(
                    f"Duplicate package name '{name}' found in "
                    f"'{inc_label}' and '{pkg_name_origins[name]}'"
                )
            pkg_name_origins[name] = inc_label
        if "packages" in inc_data:
            self._data.setdefault("packages", []).extend(
                inc_data["packages"]
            )
```

Then in `_load()`, insert the call right after loading the main file (after line 123, before line 125):

```python
def _load(self, check_version: bool = False) -> None:
    """Load and parse the datasets.yaml file."""
    with open(self.datasets_file, "r") as f:
        self._data = _yaml.load(f) or {}

    # Merge included files before anything else
    self._merge_includes()

    # Check min_sunstone_version compatibility (only on initial load)
    # ... rest of _load unchanged ...
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_datasets_include.py::TestDatasetsInclude::test_basic_include_inputs -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest -x -q`
Expected: All tests pass (existing datasets.yaml files have no `include:` key, so `_merge_includes()` is a no-op for them).

- [ ] **Step 6: Commit**

```bash
git add tests/test_datasets_include.py src/sunstone/datasets.py
git commit -m "feat: add include support for datasets.yaml"
```

---

### Task 2: Test and implement output and package merging

**Files:**
- Modify: `tests/test_datasets_include.py`

- [ ] **Step 1: Write failing test for output merging**

```python
def test_include_outputs(self, tmp_path: Path) -> None:
    """Outputs from an included file appear in get_all_outputs()."""
    (tmp_path / "a.csv").write_text("col\nval")
    (tmp_path / "b.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra-outputs.yaml\n"
        "outputs:\n"
        "  - name: Output A\n"
        "    slug: output-a\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "extra-outputs.yaml").write_text(
        "outputs:\n"
        "  - name: Output B\n"
        "    slug: output-b\n"
        "    location: b.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    manager = DatasetsManager(tmp_path)
    outputs = manager.get_all_outputs()
    slugs = [d.slug for d in outputs]
    assert slugs == ["output-a", "output-b"]
```

- [ ] **Step 2: Run to verify it passes** (should already pass from Task 1 implementation)

Run: `uv run pytest tests/test_datasets_include.py::TestDatasetsInclude::test_include_outputs -v`
Expected: PASS

- [ ] **Step 3: Write test for package merging from included files**

```python
def test_include_packages(self, tmp_path: Path) -> None:
    """Packages from an included file are merged."""
    (tmp_path / "a.csv").write_text("col\nval")
    (tmp_path / "b.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra-packages.yaml\n"
        "packages:\n"
        "  - name: pkg-a\n"
        "    title: Package A\n"
        "    datasets:\n"
        "      - dataset-a\n"
        "outputs:\n"
        "  - name: Dataset A\n"
        "    slug: dataset-a\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
        "  - name: Dataset B\n"
        "    slug: dataset-b\n"
        "    location: b.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "extra-packages.yaml").write_text(
        "packages:\n"
        "  - name: pkg-b\n"
        "    title: Package B\n"
        "    datasets:\n"
        "      - dataset-b\n"
    )

    manager = DatasetsManager(tmp_path)
    packages = manager.get_packages()
    names = [p.name for p in packages]
    assert names == ["pkg-a", "pkg-b"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_datasets_include.py::TestDatasetsInclude::test_include_packages -v`
Expected: PASS

- [ ] **Step 5: Write test for multiple includes with all three list types**

```python
def test_multiple_includes_all_types(self, tmp_path: Path) -> None:
    """Multiple includes contribute inputs, outputs, and packages."""
    (tmp_path / "a.csv").write_text("col\nval")
    (tmp_path / "b.csv").write_text("col\nval")
    (tmp_path / "c.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - file1.yaml\n"
        "  - file2.yaml\n"
        "inputs:\n"
        "  - name: Main Input\n"
        "    slug: main-input\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
        "outputs: []\n"
    )

    (tmp_path / "file1.yaml").write_text(
        "inputs:\n"
        "  - name: File1 Input\n"
        "    slug: file1-input\n"
        "    location: b.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "file2.yaml").write_text(
        "outputs:\n"
        "  - name: File2 Output\n"
        "    slug: file2-output\n"
        "    location: c.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    manager = DatasetsManager(tmp_path)
    input_slugs = [d.slug for d in manager.get_all_inputs()]
    output_slugs = [d.slug for d in manager.get_all_outputs()]
    assert input_slugs == ["main-input", "file1-input"]
    assert output_slugs == ["file2-output"]
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_datasets_include.py::TestDatasetsInclude::test_multiple_includes_all_types -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_datasets_include.py
git commit -m "test: add output and package merging tests for include feature"
```

---

### Task 3: Test and implement find operations across included datasets

**Files:**
- Modify: `tests/test_datasets_include.py`

- [ ] **Step 1: Write test for find_dataset_by_slug across includes**

```python
def test_find_by_slug_across_includes(self, tmp_path: Path) -> None:
    """find_dataset_by_slug finds datasets from included files."""
    (tmp_path / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    (tmp_path / "extra.yaml").write_text(
        "inputs:\n"
        "  - name: Included Input\n"
        "    slug: included-input\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    manager = DatasetsManager(tmp_path)
    dataset = manager.find_dataset_by_slug("included-input")
    assert dataset is not None
    assert dataset.name == "Included Input"
```

- [ ] **Step 2: Write test for find_dataset_by_location across includes**

```python
def test_find_by_location_across_includes(self, tmp_path: Path) -> None:
    """find_dataset_by_location finds datasets from included files."""
    (tmp_path / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    (tmp_path / "extra.yaml").write_text(
        "inputs:\n"
        "  - name: Included Input\n"
        "    slug: included-input\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    manager = DatasetsManager(tmp_path)
    dataset = manager.find_dataset_by_location("a.csv")
    assert dataset is not None
    assert dataset.slug == "included-input"
```

- [ ] **Step 3: Run both tests**

Run: `uv run pytest tests/test_datasets_include.py -k "find_by" -v`
Expected: PASS (these work because the merge happens at load time, before find methods run)

- [ ] **Step 4: Commit**

```bash
git add tests/test_datasets_include.py
git commit -m "test: add find operations tests for included datasets"
```

---

### Task 4: Test and implement error cases

**Files:**
- Modify: `tests/test_datasets_include.py`

- [ ] **Step 1: Write test for duplicate slug detection**

```python
def test_duplicate_slug_across_files_raises(self, tmp_path: Path) -> None:
    """Duplicate slug across main and included file raises error."""
    (tmp_path / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra.yaml\n"
        "inputs:\n"
        "  - name: Input A\n"
        "    slug: same-slug\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "extra.yaml").write_text(
        "inputs:\n"
        "  - name: Input B\n"
        "    slug: same-slug\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    with pytest.raises(DatasetValidationError, match="Duplicate dataset slug 'same-slug'"):
        DatasetsManager(tmp_path)
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/test_datasets_include.py::TestDatasetsInclude::test_duplicate_slug_across_files_raises -v`
Expected: PASS

- [ ] **Step 3: Write test for duplicate package name detection**

```python
def test_duplicate_package_name_across_files_raises(self, tmp_path: Path) -> None:
    """Duplicate package name across main and included file raises error."""
    (tmp_path / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra.yaml\n"
        "packages:\n"
        "  - name: my-pkg\n"
        "    title: Package\n"
        "    datasets:\n"
        "      - ds-a\n"
        "outputs:\n"
        "  - name: DS A\n"
        "    slug: ds-a\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "extra.yaml").write_text(
        "packages:\n"
        "  - name: my-pkg\n"
        "    title: Package Dupe\n"
        "    datasets:\n"
        "      - ds-a\n"
    )

    with pytest.raises(DatasetValidationError, match="Duplicate package name 'my-pkg'"):
        DatasetsManager(tmp_path)
```

- [ ] **Step 4: Write test for nested include rejection**

```python
def test_nested_include_raises(self, tmp_path: Path) -> None:
    """An included file with its own include: raises error."""
    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - level1.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    (tmp_path / "level1.yaml").write_text(
        "include:\n"
        "  - level2.yaml\n"
        "inputs: []\n"
    )

    (tmp_path / "level2.yaml").write_text("inputs: []\n")

    with pytest.raises(DatasetValidationError, match="Nested includes are not supported"):
        DatasetsManager(tmp_path)
```

- [ ] **Step 5: Write test for disallowed keys rejection**

```python
def test_disallowed_keys_in_included_file_raises(self, tmp_path: Path) -> None:
    """Included files with disallowed top-level keys raise error."""
    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - extra.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    (tmp_path / "extra.yaml").write_text(
        "defaults:\n"
        "  rdfPrefixes:\n"
        "    ex: http://example.org/\n"
        "inputs: []\n"
    )

    with pytest.raises(DatasetValidationError, match="disallowed top-level keys.*defaults"):
        DatasetsManager(tmp_path)
```

- [ ] **Step 6: Write test for missing included file**

```python
def test_missing_included_file_raises(self, tmp_path: Path) -> None:
    """A missing included file raises FileNotFoundError."""
    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - nonexistent.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    with pytest.raises(FileNotFoundError, match="nonexistent.yaml"):
        DatasetsManager(tmp_path)
```

- [ ] **Step 7: Write test for empty included file**

```python
def test_empty_included_file_is_noop(self, tmp_path: Path) -> None:
    """An empty included file is a valid no-op."""
    (tmp_path / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - empty.yaml\n"
        "inputs:\n"
        "  - name: Input A\n"
        "    slug: input-a\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "empty.yaml").write_text("")

    manager = DatasetsManager(tmp_path)
    inputs = manager.get_all_inputs()
    assert len(inputs) == 1
    assert inputs[0].slug == "input-a"
```

- [ ] **Step 8: Run all error case tests**

Run: `uv run pytest tests/test_datasets_include.py -v`
Expected: All PASS

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 10: Commit**

```bash
git add tests/test_datasets_include.py
git commit -m "test: add error case tests for include feature"
```

---

### Task 5: Test include with subdirectory paths

**Files:**
- Modify: `tests/test_datasets_include.py`

- [ ] **Step 1: Write test for subdirectory include path**

```python
def test_include_from_subdirectory(self, tmp_path: Path) -> None:
    """Include paths resolve relative to the main datasets.yaml."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - data/sources.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    (tmp_path / "data" / "sources.yaml").write_text(
        "inputs:\n"
        "  - name: Sub Input\n"
        "    slug: sub-input\n"
        "    location: data/a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    manager = DatasetsManager(tmp_path)
    inputs = manager.get_all_inputs()
    assert len(inputs) == 1
    assert inputs[0].slug == "sub-input"
```

- [ ] **Step 2: Write test for duplicate slug across two included files**

```python
def test_duplicate_slug_across_two_includes_raises(self, tmp_path: Path) -> None:
    """Duplicate slug across two included files (not main) raises error."""
    (tmp_path / "a.csv").write_text("col\nval")

    (tmp_path / "datasets.yaml").write_text(
        "include:\n"
        "  - file1.yaml\n"
        "  - file2.yaml\n"
        "inputs: []\n"
        "outputs: []\n"
    )

    (tmp_path / "file1.yaml").write_text(
        "inputs:\n"
        "  - name: Input X\n"
        "    slug: dupe\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    (tmp_path / "file2.yaml").write_text(
        "outputs:\n"
        "  - name: Output X\n"
        "    slug: dupe\n"
        "    location: a.csv\n"
        "    fields:\n"
        "      - name: col\n"
        "        type: string\n"
    )

    with pytest.raises(DatasetValidationError, match="Duplicate dataset slug 'dupe'.*file2.yaml.*file1.yaml"):
        DatasetsManager(tmp_path)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_datasets_include.py -v`
Expected: All PASS

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_datasets_include.py
git commit -m "test: add subdirectory and cross-include duplicate tests"
```

---

### Task 6: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

Add to the `[Unreleased]` section of `CHANGELOG.md`:

```
- Added: `include:` directive in datasets.yaml to organize datasets across multiple files
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add changelog entry for include feature"
```
