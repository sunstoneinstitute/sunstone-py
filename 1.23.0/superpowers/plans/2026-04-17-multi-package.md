# Multi-Package Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support `packages:` (list) in datasets.yaml so each datapackage gets its own title, publish config, and explicit dataset list.

**Architecture:** Add `PackageEntry` dataclass combining metadata + publish config + dataset slugs. `DatasetsManager.get_packages()` parses either `package:` (singular, backward compat) or `packages:` (plural, new). CLI commands (`package build`, `package push`) iterate over `PackageEntry` list instead of grouping by publish destination.

**Tech Stack:** Python dataclasses, ruamel.yaml, typer CLI, pytest

**Spec:** `docs/superpowers/specs/2026-04-17-multi-package-design.md`

---

### Task 1: Revert `package` field from PublishConfig

The previous commit added `package: Optional[PackageMetadata]` to `PublishConfig` and `_merge_package_metadata()` to `cli.py`. This is superseded by the `PackageEntry` approach. Remove it before building on top.

**Files:**
- Modify: `src/sunstone/lineage.py:310-311`
- Modify: `src/sunstone/datasets.py:197` (remove `package=` kwarg from `_parse_publish`)
- Modify: `src/sunstone/cli.py:282-310` (revert `get_effective_publish` package merge)
- Modify: `src/sunstone/cli.py:1021-1035` (remove `_merge_package_metadata`)
- Modify: `src/sunstone/cli.py:1091-1096` (revert `build_datapackage` merge logic)
- Modify: `tests/test_cli.py` (remove `TestMergePackageMetadata`, `TestPerPublishPackageMetadata`, revert imports)

- [ ] **Step 1: Remove `package` field from `PublishConfig`**

In `src/sunstone/lineage.py`, remove lines 310-311:

```python
    package: Optional[PackageMetadata] = None
    """Per-publish package metadata. Overrides global package: fields for this destination's datapackage."""
```

- [ ] **Step 2: Remove `package=` kwarg from `_parse_publish`**

In `src/sunstone/datasets.py`, revert the `_parse_publish` method's dict branch back to:

```python
        if isinstance(publish_data, dict):
            enabled = publish_data.get("enabled", False)
            return PublishConfig(
                enabled=enabled,
                to=publish_data.get("to"),
                flatten=publish_data.get("flatten", False),
                as_url=publish_data.get("as"),
            )
```

- [ ] **Step 3: Revert `get_effective_publish` in cli.py**

Remove the `package=` line from the `PublishConfig(...)` construction in `get_effective_publish`:

```python
        if top_level and top_level.enabled:
            return PublishConfig(
                enabled=True,
                to=ds.publish.to or top_level.to,
                flatten=ds.publish.flatten if ds.publish.flatten else top_level.flatten,
                as_url=ds.publish.as_url or top_level.as_url,
            )
```

- [ ] **Step 4: Remove `_merge_package_metadata` from cli.py**

Delete the entire `_merge_package_metadata` function (lines ~1021-1035).

- [ ] **Step 5: Revert `build_datapackage` metadata logic in cli.py**

Replace the merge logic back to the original:

```python
    # Add standard package metadata (title, description, etc.)
    pkg_meta = manager.get_package_metadata()
    if pkg_meta:
        datapackage.update(_package_metadata_to_dict(pkg_meta))
```

- [ ] **Step 6: Remove new test classes and revert imports in test_cli.py**

Remove `TestMergePackageMetadata` and `TestPerPublishPackageMetadata` classes entirely.

Revert the imports back to:

```python
from sunstone.cli import _contributor_to_dict, _package_metadata_to_dict, app, expand_env_vars, is_lfs_pointer
from sunstone.lineage import Contributor, PackageMetadata
```

- [ ] **Step 7: Run tests to verify clean revert**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All existing tests pass (the ones that existed before the previous commit).

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py src/sunstone/cli.py tests/test_cli.py
git commit -m "revert: remove package field from PublishConfig

Superseded by PackageEntry approach in multi-package design."
```

---

### Task 2: Add `PackageEntry` dataclass

**Files:**
- Modify: `src/sunstone/lineage.py:292` (after `PackageMetadata`)
- Test: `tests/test_lineage_persistence.py` (or inline verification)

- [ ] **Step 1: Write test for PackageEntry**

Add to `tests/test_cli.py` (we'll import it there since that's where packaging tests live):

```python
from sunstone.lineage import Contributor, PackageEntry, PackageMetadata, PublishConfig


class TestPackageEntry:
    """Tests for PackageEntry dataclass."""

    def test_minimal(self) -> None:
        entry = PackageEntry(name="my-pkg", metadata=PackageMetadata())
        assert entry.name == "my-pkg"
        assert entry.datasets is None
        assert entry.publish is None

    def test_with_all_fields(self) -> None:
        entry = PackageEntry(
            name="my-pkg",
            metadata=PackageMetadata(title="My Package", version="1.0.0"),
            publish=PublishConfig(enabled=True, to="gs://bucket/"),
            datasets=["slug-a", "slug-b"],
        )
        assert entry.metadata.title == "My Package"
        assert entry.publish.enabled is True
        assert entry.datasets == ["slug-a", "slug-b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestPackageEntry -v`
Expected: FAIL with ImportError (PackageEntry not defined yet)

- [ ] **Step 3: Add PackageEntry dataclass to lineage.py**

Insert after the `PackageMetadata` class (after line 292), before `PublishConfig`:

```python
@dataclass
class PackageEntry:
    """A package definition combining metadata, publish config, and dataset membership.

    Used by ``DatasetsManager.get_packages()`` to represent either a single
    ``package:`` or one entry in a ``packages:`` list from datasets.yaml.
    """

    name: str
    """Datapackage name/slug (kebab-case identifier)."""

    metadata: PackageMetadata
    """Title, description, version, and other package-level metadata."""

    publish: Optional[PublishConfig] = None
    """Where and how to publish this package."""

    datasets: Optional[List[str]] = None
    """Dataset slugs included in this package. None means all outputs (single-package mode)."""
```

Note: `PackageEntry` references `PublishConfig` which is defined after it. Move `PublishConfig` before `PackageEntry`, or use a forward reference string `"PublishConfig"`. The simplest fix: reorder so `PublishConfig` comes before `PackageEntry`. The current order is `PackageMetadata` → `PublishConfig` → `DatasetMetadata`. Insert `PackageEntry` between `PublishConfig` and `DatasetMetadata`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestPackageEntry -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/lineage.py tests/test_cli.py
git commit -m "feat: add PackageEntry dataclass

Combines package metadata, publish config, and dataset list
for multi-package support in datasets.yaml."
```

---

### Task 3: Add `get_packages()` to DatasetsManager

This is the core parsing logic. Handles both `package:` (singular) and `packages:` (plural), validates mutual exclusion, validates dataset slugs, and synthesizes `PackageEntry` objects.

**Files:**
- Modify: `src/sunstone/datasets.py` (add methods after `get_package_metadata`)
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write tests for `get_packages()` — singular form**

Add to `tests/test_datasets.py`:

```python
class TestGetPackages:
    """Tests for DatasetsManager.get_packages()."""

    def _make_manager(self, yaml_content: str, tmp_path: Path) -> "DatasetsManager":
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(yaml_content)
        from sunstone.datasets import DatasetsManager
        return DatasetsManager(tmp_path, yaml_file)

    def test_singular_package(self, tmp_path: Path) -> None:
        """package: (singular) produces one PackageEntry with datasets=None."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: My Package\n"
            "  version: '1.0.0'\n"
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/test/\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 1
        assert packages[0].metadata.title == "My Package"
        assert packages[0].metadata.version == "1.0.0"
        assert packages[0].datasets is None
        assert packages[0].publish is not None
        assert packages[0].publish.enabled is True
        assert packages[0].publish.to == "gs://bucket/test/"

    def test_singular_package_no_publish(self, tmp_path: Path) -> None:
        """package: without top-level publish: still works."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: My Package\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 1
        assert packages[0].publish is None

    def test_no_package_or_packages(self, tmp_path: Path) -> None:
        """No package: or packages: returns empty list."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_datasets.py::TestGetPackages -v`
Expected: FAIL (get_packages not defined)

- [ ] **Step 3: Write tests for `get_packages()` — plural form and validation**

Add more test methods to the same class:

```python
    def test_plural_packages(self, tmp_path: Path) -> None:
        """packages: (plural) produces multiple PackageEntry objects."""
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg-a\n"
            "    title: Package A\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/a/\n"
            "    datasets:\n"
            "      - dataset-a\n"
            "  - name: pkg-b\n"
            "    title: Package B\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/b/\n"
            "    datasets:\n"
            "      - dataset-b\n"
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
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 2
        assert packages[0].name == "pkg-a"
        assert packages[0].metadata.title == "Package A"
        assert packages[0].datasets == ["dataset-a"]
        assert packages[1].name == "pkg-b"
        assert packages[1].datasets == ["dataset-b"]

    def test_both_package_and_packages_is_error(self, tmp_path: Path) -> None:
        """Having both package: and packages: raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: Singular\n"
            "packages:\n"
            "  - name: pkg\n"
            "    datasets:\n"
            "      - test\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="Cannot use both.*package.*and.*packages"):
            mgr.get_packages()

    def test_packages_with_top_level_publish_is_error(self, tmp_path: Path) -> None:
        """packages: with top-level publish: raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/\n"
            "packages:\n"
            "  - name: pkg\n"
            "    datasets:\n"
            "      - test\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="top-level.*publish.*not allowed.*packages"):
            mgr.get_packages()

    def test_packages_invalid_slug_is_error(self, tmp_path: Path) -> None:
        """A datasets: slug that doesn't exist raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg\n"
            "    datasets:\n"
            "      - nonexistent-slug\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="nonexistent-slug.*not found"):
            mgr.get_packages()

    def test_packages_missing_name_is_error(self, tmp_path: Path) -> None:
        """A packages: entry without name raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - title: No Name\n"
            "    datasets:\n"
            "      - test\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="name.*required"):
            mgr.get_packages()

    def test_packages_missing_datasets_is_error(self, tmp_path: Path) -> None:
        """A packages: entry without datasets raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg\n"
            "    title: No Datasets\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="datasets.*required"):
            mgr.get_packages()

    def test_packages_dataset_from_inputs(self, tmp_path: Path) -> None:
        """packages: can reference input dataset slugs."""
        (tmp_path / "input.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg\n"
            "    title: With Input\n"
            "    datasets:\n"
            "      - my-input\n"
            "inputs:\n"
            "  - name: My Input\n"
            "    slug: my-input\n"
            "    location: input.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 1
        assert packages[0].datasets == ["my-input"]

    def test_singular_package_name_is_none(self, tmp_path: Path) -> None:
        """package: (singular) gets name=None (auto-derived later from project slug)."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: My Package\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert packages[0].name is None
```

- [ ] **Step 4: Implement `get_packages()` and `_parse_package_entry()`**

Add to `src/sunstone/datasets.py` after `get_package_metadata()`:

```python
    def get_packages(self) -> list[PackageEntry]:
        """Get package definitions from datasets.yaml.

        Supports two mutually exclusive forms:
        - ``package:`` (singular): backward-compatible single package.
          Top-level ``publish:`` is copied into the package entry.
          Returns a single PackageEntry with ``datasets=None`` (all outputs).
        - ``packages:`` (plural): list of explicit package definitions,
          each with ``name``, ``datasets``, optional metadata and ``publish``.

        Returns:
            List of PackageEntry objects. Empty if neither form is present.

        Raises:
            ValueError: If both ``package:`` and ``packages:`` are present,
                if ``packages:`` is used with top-level ``publish:``,
                if a packages entry is missing ``name`` or ``datasets``,
                or if a dataset slug doesn't exist.
        """
        has_singular = "package" in self._data
        has_plural = "packages" in self._data

        if has_singular and has_plural:
            raise ValueError(
                "Cannot use both 'package:' and 'packages:' in datasets.yaml. "
                "Use 'package:' for a single package or 'packages:' for multiple."
            )

        if has_plural:
            if "publish" in self._data:
                raise ValueError(
                    "A top-level 'publish:' is not allowed with 'packages:'. "
                    "Move publish config into each package entry."
                )
            return [
                self._parse_package_entry(entry)
                for entry in self._data["packages"]
            ]

        if has_singular:
            metadata = self._parse_package(self._data["package"]) or PackageMetadata()
            publish = self.get_publish_config()
            return [PackageEntry(name=None, metadata=metadata, publish=publish, datasets=None)]

        return []

    def _parse_package_entry(self, entry_data: dict[str, Any]) -> "PackageEntry":
        """Parse a single entry from the packages: list.

        Args:
            entry_data: Raw dict from YAML.

        Returns:
            A PackageEntry with validated dataset slugs.

        Raises:
            ValueError: If name or datasets is missing, or a slug doesn't exist.
        """
        name = entry_data.get("name")
        if not name:
            raise ValueError(
                "Each 'packages:' entry requires a 'name' field."
            )

        datasets = entry_data.get("datasets")
        if datasets is None:
            raise ValueError(
                f"Package '{name}': 'datasets' list is required in each packages: entry."
            )

        # Validate all slugs exist
        all_slugs = {
            ds.get("slug")
            for ds in self._data.get("inputs", []) + self._data.get("outputs", [])
        }
        for slug in datasets:
            if slug not in all_slugs:
                raise ValueError(
                    f"Package '{name}': dataset slug '{slug}' not found in inputs or outputs."
                )

        # Parse package metadata from remaining fields
        metadata_keys = {
            "title", "description", "version", "keywords",
            "license", "contributors", "homepage", "id", "image",
        }
        metadata_data = {k: v for k, v in entry_data.items() if k in metadata_keys}
        metadata = self._parse_package(metadata_data) if metadata_data else PackageMetadata()

        publish = self._parse_publish(entry_data.get("publish"))

        return PackageEntry(
            name=name,
            metadata=metadata,
            publish=publish,
            datasets=datasets,
        )
```

Also add the import for `PackageEntry` at the top of `datasets.py`. Find the existing import line from `lineage` and add `PackageEntry`:

```python
from .lineage import PackageEntry
```

And update the `PackageEntry` dataclass `name` field to be `Optional[str]` since singular packages get `name=None`:

```python
    name: Optional[str] = None
    """Datapackage name/slug. None for singular package: (auto-derived from project slug)."""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_datasets.py::TestGetPackages -v`
Expected: All 10 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py tests/test_datasets.py
git commit -m "feat: add get_packages() to DatasetsManager

Parses package: (singular) and packages: (plural) forms from
datasets.yaml with validation for mutual exclusion, required
fields, and dataset slug existence."
```

---

### Task 4: Add deprecation warning for per-dataset `publish:`

**Files:**
- Modify: `src/sunstone/datasets.py` (in `_parse_dataset`)
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write test for deprecation warning**

Add to `tests/test_datasets.py`:

```python
class TestPerDatasetPublishDeprecation:
    """Test that per-dataset publish: emits a deprecation warning."""

    def test_warns_on_per_dataset_publish(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/test/\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "test.csv").write_text("col\nval")
        from sunstone.datasets import DatasetsManager
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            mgr = DatasetsManager(tmp_path, yaml_file)
            mgr.get_all_outputs()
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 1
            assert "publish" in str(deprecation_warnings[0].message).lower()
            assert "packages:" in str(deprecation_warnings[0].message)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_datasets.py::TestPerDatasetPublishDeprecation -v`
Expected: FAIL (no warning emitted)

- [ ] **Step 3: Add deprecation warning to `_parse_dataset`**

In `src/sunstone/datasets.py`, in the `_parse_dataset` method, after parsing the `publish` field, add:

```python
        if publish is not None:
            import warnings
            warnings.warn(
                f"Per-dataset 'publish:' on '{slug}' is deprecated. "
                "Use 'packages:' with a 'datasets:' list instead.",
                DeprecationWarning,
                stacklevel=2,
            )
```

Find the exact location by looking for where `publish` is parsed in `_parse_dataset` (around line 428-429).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_datasets.py::TestPerDatasetPublishDeprecation -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for unintended breakage**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -40`
Expected: Some tests may now emit warnings. If any tests fail because they use per-dataset `publish:` and the warning causes issues, add `warnings.filterwarnings("ignore", category=DeprecationWarning)` to those specific tests.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/datasets.py tests/test_datasets.py
git commit -m "deprecate: warn on per-dataset publish: config

Per-dataset publish: is deprecated in favor of packages:
with explicit datasets: lists."
```

---

### Task 5: Update `build_datapackage` to accept `PackageEntry`

Refactor `build_datapackage` to take a `PackageEntry` and resolve datasets from it, instead of receiving a pre-grouped dataset list.

**Files:**
- Modify: `src/sunstone/cli.py` (`build_datapackage` function)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write test for build_datapackage with PackageEntry**

Add to `tests/test_cli.py`:

```python
from sunstone.lineage import Contributor, PackageEntry, PackageMetadata, PublishConfig


class TestBuildDatapackageWithPackageEntry:
    """Tests that build_datapackage works with PackageEntry."""

    def test_build_with_package_entry_explicit_datasets(self, runner: CliRunner, tmp_path: Path) -> None:
        """PackageEntry with explicit datasets list builds only those resources."""
        import json

        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "packages:\n"
            "  - name: my-pkg\n"
            "    title: My Package\n"
            "    version: '2.0.0'\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/test/\n"
            "    datasets:\n"
            "      - included\n"
            "outputs:\n"
            "  - name: Included\n"
            "    slug: included\n"
            "    location: included.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Excluded\n"
            "    slug: excluded\n"
            "    location: excluded.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "included.csv").write_text("col\nval")
        (tmp_path / "excluded.csv").write_text("col\nval")

        result = runner.invoke(
            app,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "dp.json")],
        )
        assert result.exit_code == 0

        dp = json.loads((tmp_path / "dp.json").read_text())
        assert dp["name"] == "my-pkg"
        assert dp["title"] == "My Package"
        assert dp["version"] == "2.0.0"
        assert len(dp["resources"]) == 1
        assert dp["resources"][0]["name"] == "included"

    def test_build_with_multiple_packages(self, runner: CliRunner, tmp_path: Path) -> None:
        """Multiple packages: entries produce multiple datapackage files."""
        import json

        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "packages:\n"
            "  - name: pkg-a\n"
            "    title: Package A\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/a/\n"
            "    datasets:\n"
            "      - dataset-a\n"
            "  - name: pkg-b\n"
            "    title: Package B\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/b/\n"
            "    datasets:\n"
            "      - dataset-b\n"
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
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")

        result = runner.invoke(
            app,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "dp.json")],
        )
        assert result.exit_code == 0

        dp0 = json.loads((tmp_path / "dp.json").read_text())
        assert dp0["name"] == "pkg-a"
        assert dp0["title"] == "Package A"

        dp1 = json.loads((tmp_path / "dp.1.json").read_text())
        assert dp1["name"] == "pkg-b"
        assert dp1["title"] == "Package B"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestBuildDatapackageWithPackageEntry -v`
Expected: FAIL

- [ ] **Step 3: Update `build_datapackage` signature and logic**

In `src/sunstone/cli.py`, update `build_datapackage`:

```python
def build_datapackage(
    project_slug: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    publish_config: Optional[PublishConfig],
    package_entry: Optional["PackageEntry"] = None,
) -> Optional[dict[str, Any]]:
    """
    Build a datapackage dict for a group of datasets.

    Args:
        project_slug: Fallback name if package_entry has no name.
        datasets: The datasets to include as resources.
        manager: DatasetsManager for metadata lookups.
        publish_config: Publish config for resource path building.
        package_entry: Optional PackageEntry with name and metadata.

    Returns None if no resources could be built.
    """
    resources = []
    for ds in datasets:
        resource_dict = build_resource_dict(ds, manager, publish_config)
        if resource_dict:
            resources.append(resource_dict)
            typer.echo(f"  + {ds.slug}")

    if not resources:
        return None

    pkg_name = (package_entry.name if package_entry and package_entry.name else project_slug)

    datapackage: dict[str, Any] = {
        "name": pkg_name,
        f"{STANDARD_RDF_PREFIXES['rdf']}type": f"{STANDARD_RDF_PREFIXES['dcat']}Dataset",
        "resources": resources,
    }

    # Add standard package metadata (title, description, etc.)
    # PackageEntry metadata takes precedence over global
    if package_entry and package_entry.metadata:
        pkg_meta = package_entry.metadata
    else:
        pkg_meta = manager.get_package_metadata()
    if pkg_meta:
        datapackage.update(_package_metadata_to_dict(pkg_meta))

    # Add top-level custom properties with RDF prefix expansion
    top_level_props = manager.get_top_level_custom_properties()
    rdf_prefixes = {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()}
    as_url = publish_config.as_url if publish_config else None
    should_flatten = publish_config.flatten if publish_config else False
    if top_level_props:
        top_level_props = expand_custom_properties(
            top_level_props, rdf_prefixes, base_url=as_url, flatten=should_flatten
        )
    datapackage.update(top_level_props)

    return datapackage
```

Add the import at the top of cli.py:

```python
from .lineage import PackageEntry
```

- [ ] **Step 4: Update `package_build` command to use `get_packages()`**

Replace the body of `package_build` in `src/sunstone/cli.py`:

```python
@package_app.command("build")
def package_build(
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
    output_file: str = typer.Option("datapackage.json", "-o", "--output", help="Output file path"),
) -> None:
    """Build a datapackage.json from datasets.yaml.

    Creates a Data Package (https://datapackage.org/) with publishable datasets as resources.
    Supports both single package: and multiple packages: configurations.
    """
    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        from frictionless import describe  # noqa: F401
    except ImportError:
        typer.echo("Error: frictionless is required for package build", err=True)
        sys.exit(1)

    project_slug = get_project_slug(project_path)
    packages = manager.get_packages()

    if not packages:
        # Fall back to legacy destination-based grouping
        top_level_publish = manager.get_publish_config()
        all_datasets = manager.get_all_inputs() + manager.get_all_outputs()
        groups = group_datasets_by_destination(all_datasets, top_level_publish)

        if not groups:
            typer.echo("No publishable datasets found.", err=True)
            sys.exit(1)

        _build_from_groups(groups, project_slug, manager, output_file)
        return

    _build_from_packages(packages, project_slug, manager, output_file)


def _resolve_package_datasets(
    pkg: "PackageEntry", manager: DatasetsManager
) -> list[DatasetMetadata]:
    """Resolve a PackageEntry's dataset slugs to DatasetMetadata objects.

    If pkg.datasets is None (singular package: mode), returns all publishable
    outputs using the legacy effective-publish logic.
    """
    if pkg.datasets is None:
        # Singular package: mode — all publishable outputs
        all_datasets = manager.get_all_inputs() + manager.get_all_outputs()
        publishable = []
        for ds in all_datasets:
            effective = get_effective_publish(ds, pkg.publish)
            if effective and effective.enabled:
                publishable.append(ds)
        return publishable

    # Explicit dataset list — look up each slug
    resolved = []
    for slug in pkg.datasets:
        ds = manager.find_dataset_by_slug(slug)
        if ds is None:
            raise ValueError(f"Dataset slug '{slug}' not found")
        resolved.append(ds)
    return resolved


def _build_from_packages(
    packages: list["PackageEntry"],
    project_slug: str,
    manager: DatasetsManager,
    output_file: str,
) -> None:
    """Build datapackage files from PackageEntry list."""
    output_base = Path(output_file)

    if len(packages) == 1:
        pkg = packages[0]
        datasets = _resolve_package_datasets(pkg, manager)
        datapackage = build_datapackage(
            project_slug, datasets, manager, pkg.publish, package_entry=pkg
        )
        if not datapackage:
            typer.echo("Error: No resources could be added to the package", err=True)
            sys.exit(1)

        with open(output_base, "w") as f:
            json.dump(datapackage, f, indent=2)
        typer.echo(f"\n✓ Created {output_file} with {len(datapackage['resources'])} resource(s)")
    else:
        total_resources = 0
        files_created = 0
        for i, pkg in enumerate(packages):
            datasets = _resolve_package_datasets(pkg, manager)
            datapackage = build_datapackage(
                project_slug, datasets, manager, pkg.publish, package_entry=pkg
            )
            if not datapackage:
                typer.echo(f"Warning: No resources for package: {pkg.name}", err=True)
                continue

            if i == 0:
                out_path = output_base
            else:
                out_path = output_base.parent / f"{output_base.stem}.{i}{output_base.suffix}"

            with open(out_path, "w") as f:
                json.dump(datapackage, f, indent=2)

            n = len(datapackage["resources"])
            total_resources += n
            files_created += 1
            dest = pkg.publish.to if pkg.publish else "local"
            typer.echo(f"\n✓ Created {out_path} with {n} resource(s) -> {dest}")

        typer.echo(f"\n✓ Created {files_created} datapackage file(s) with {total_resources} total resource(s)")


def _build_from_groups(
    groups: dict[str, tuple[PublishConfig, list[DatasetMetadata]]],
    project_slug: str,
    manager: DatasetsManager,
    output_file: str,
) -> None:
    """Build datapackage files from legacy destination-based groups."""
    output_base = Path(output_file)

    if len(groups) == 1:
        dest, (pub_config, datasets) = next(iter(groups.items()))
        datapackage = build_datapackage(project_slug, datasets, manager, pub_config)
        if not datapackage:
            typer.echo("Error: No resources could be added to the package", err=True)
            sys.exit(1)

        with open(output_base, "w") as f:
            json.dump(datapackage, f, indent=2)
        typer.echo(f"\n✓ Created {output_file} with {len(datapackage['resources'])} resource(s)")
    else:
        total_resources = 0
        files_created = 0
        for i, (dest, (pub_config, datasets)) in enumerate(groups.items()):
            datapackage = build_datapackage(project_slug, datasets, manager, pub_config)
            if not datapackage:
                typer.echo(f"Warning: No resources for destination: {dest}", err=True)
                continue

            if i == 0:
                out_path = output_base
            else:
                out_path = output_base.parent / f"{output_base.stem}.{i}{output_base.suffix}"

            with open(out_path, "w") as f:
                json.dump(datapackage, f, indent=2)

            n = len(datapackage["resources"])
            total_resources += n
            files_created += 1
            typer.echo(f"\n✓ Created {out_path} with {n} resource(s) -> {dest}")

        typer.echo(f"\n✓ Created {files_created} datapackage file(s) with {total_resources} total resource(s)")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestBuildDatapackageWithPackageEntry tests/test_cli.py::TestBuildDatapackageWithPackageMetadata -v`
Expected: All PASS (both new and existing tests)

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py
git commit -m "feat: update package build to use PackageEntry

build_datapackage accepts optional PackageEntry for name and
metadata. package_build command uses get_packages() with
fallback to legacy destination-based grouping."
```

---

### Task 6: Update `package_push` to use `PackageEntry`

**Files:**
- Modify: `src/sunstone/cli.py` (`package_push` and `push_group_to_gcs`)

- [ ] **Step 1: Update `push_group_to_gcs` to accept `PackageEntry`**

In `src/sunstone/cli.py`, update `push_group_to_gcs`:

```python
def push_group_to_gcs(
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
    *,
    allow_outside_project: bool = False,
    package_entry: Optional["PackageEntry"] = None,
) -> None:
    """
    Push a group of datasets to a remote destination.

    Args:
        dest_url: The destination URL (gs://, s3://, r2://, etc.).
        datasets: The datasets to include in this datapackage.
        manager: The DatasetsManager instance.
        project_slug: The project slug for the datapackage name.
        publish_config: The effective publish config for this group.
        allow_outside_project: Allow files outside the project root.
        package_entry: Optional PackageEntry with name and metadata.
    """
    from .packaging import push_group

    # Prepare package metadata callback
    def package_metadata_fn() -> Optional[dict[str, Any]]:
        if package_entry and package_entry.metadata:
            return _package_metadata_to_dict(package_entry.metadata)
        pkg_meta = manager.get_package_metadata()
        if pkg_meta:
            return _package_metadata_to_dict(pkg_meta)
        return None

    # Use package entry name if available
    effective_slug = (package_entry.name if package_entry and package_entry.name else project_slug)

    # Prepare top-level properties with RDF prefix expansion
    top_level_props = manager.get_top_level_custom_properties()
    rdf_prefixes = {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()}
    as_url = publish_config.as_url
    if top_level_props:
        top_level_props = expand_custom_properties(
            top_level_props, rdf_prefixes, base_url=as_url, flatten=publish_config.flatten
        )

    # Collect methodology files for upload
    methodology_files = collect_methodology_files(
        datasets, manager.get_top_level_custom_properties(), rdf_prefixes, manager, as_url
    )

    try:
        uploaded = push_group(
            dest_url=dest_url,
            datasets=datasets,
            manager=manager,
            project_slug=effective_slug,
            publish_config=publish_config,
            build_resource_dict_fn=build_resource_dict,
            package_metadata_fn=package_metadata_fn,
            rdf_prefixes=rdf_prefixes,
            top_level_props=top_level_props or {},
            methodology_files=methodology_files,
            allow_outside_project=allow_outside_project,
        )
    except (ValueError, PathTraversalError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not uploaded:
        typer.echo(f"Warning: No resources for destination: {dest_url}", err=True)
        return

    for path in uploaded:
        typer.echo(f"✓ Uploaded {path}")

    parsed = urlparse(dest_url)
    typer.echo(
        f"✓ Package pushed to: {parsed.scheme}://{parsed.netloc}/{uploaded[0].rsplit('/', 1)[0] + '/' if '/' in uploaded[0] else ''}"
    )
```

- [ ] **Step 2: Update `package_push` command to use `get_packages()`**

Replace the non-override path in `package_push`:

```python
    else:
        packages = manager.get_packages()

        if packages:
            # New packages:-based path
            has_publishable = False
            try:
                for pkg in packages:
                    if not pkg.publish or not pkg.publish.enabled:
                        continue
                    has_publishable = True
                    datasets = _resolve_package_datasets(pkg, manager)
                    dest_url = expand_env_vars(pkg.publish.to or "")
                    push_group_to_gcs(
                        dest_url,
                        datasets,
                        manager,
                        project_slug,
                        pkg.publish,
                        allow_outside_project=allow_outside_project,
                        package_entry=pkg,
                    )
                    typer.echo()

                if not has_publishable:
                    typer.echo("Error: No packages with publish enabled", err=True)
                    sys.exit(1)

                typer.echo(f"✓ Pushed {sum(1 for p in packages if p.publish and p.publish.enabled)} package(s)")
            except ImportError:
                typer.echo("Error: google-cloud-storage is required for push", err=True)
                typer.echo("Install with: pip install google-cloud-storage", err=True)
                sys.exit(1)
            except Exception as e:
                typer.echo(f"Error uploading: {e}", err=True)
                sys.exit(1)
        else:
            # Legacy destination-based grouping
            groups = group_datasets_by_destination(all_datasets, top_level_publish)

            if not groups:
                typer.echo("Error: No publishable datasets found (need publish.enabled: true)", err=True)
                sys.exit(1)

            try:
                for dest_url, (pub_config, datasets) in groups.items():
                    push_group_to_gcs(
                        dest_url, datasets, manager, project_slug, pub_config,
                        allow_outside_project=allow_outside_project,
                    )
                    typer.echo()

                typer.echo(f"✓ Pushed to {len(groups)} destination(s)")
            except ImportError:
                typer.echo("Error: google-cloud-storage is required for push", err=True)
                typer.echo("Install with: pip install google-cloud-storage", err=True)
                sys.exit(1)
            except Exception as e:
                typer.echo(f"Error uploading to GCS: {e}", err=True)
                sys.exit(1)
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -40`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/sunstone/cli.py
git commit -m "feat: update package push to use PackageEntry

push command uses get_packages() when available, with fallback
to legacy destination-based grouping."
```

---

### Task 7: Update existing test data and run full verification

**Files:**
- Test: `tests/testdata/UNMembersProject/datasets.yaml` (verify still works)
- All test files

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v 2>&1 | tail -60`
Expected: All tests PASS. The UN Members test project uses `package:` (singular) which should work unchanged.

- [ ] **Step 2: Verify the UN Members test project builds correctly**

Run: `cd /Users/stig/git/sunstone/sunstone-py && uv run sunstone package build -f tests/testdata/UNMembersProject/datasets.yaml -o /tmp/test-dp.json && cat /tmp/test-dp.json | python -m json.tool | head -20`
Expected: datapackage.json with title "UN Member States Dataset" and the correct resources.

- [ ] **Step 3: Update CHANGELOG.md**

Add to the `[Unreleased]` section:

```
- Added: `packages:` list support in datasets.yaml for multi-package projects
- Deprecated: per-dataset `publish:` config (use `packages:` with `datasets:` instead)
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update changelog for multi-package support"
```
