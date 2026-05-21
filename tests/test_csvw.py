"""Unit tests for src/sunstone/_csvw.py — CSVW sidecar logic."""

from __future__ import annotations

import json
import logging

import pytest


class TestCsvwToMetadata:
    def test_minimal_table_yields_minimal_metadata(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "tableSchema": {
                "columns": [
                    {"name": "x"},
                    {"name": "y"},
                ]
            },
        }
        meta = csvw_to_metadata(table)
        assert meta.description is None
        assert set(meta.field_metadata.keys()) == {"x", "y"}
        assert meta.field_metadata["x"].name == "x"

    def test_table_description_maps_to_metadata_description(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "dc:description": "monthly summary",
            "tableSchema": {"columns": [{"name": "x"}]},
        }
        meta = csvw_to_metadata(table)
        assert meta.description == "monthly summary"

    def test_column_description_and_datatype(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "tableSchema": {
                "columns": [
                    {
                        "name": "temp",
                        "datatype": "decimal",
                        "dc:description": "Mean temperature",
                    },
                ]
            },
        }
        meta = csvw_to_metadata(table)
        fs = meta.field_metadata["temp"]
        assert fs.description == "Mean temperature"
        assert fs.type == "decimal"

    def test_unknown_csvw_props_become_custom_properties(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "ex:custom": "something",
            "tableSchema": {"columns": [{"name": "x"}]},
        }
        meta = csvw_to_metadata(table)
        assert meta.custom_properties is not None
        assert meta.custom_properties.get("ex:custom") == "something"

    def test_empty_columns_list_is_safe(self):
        from sunstone._csvw import csvw_to_metadata

        meta = csvw_to_metadata({"url": "foo.csv", "tableSchema": {"columns": []}})
        assert meta.field_metadata == {}

    def test_dct_description_wins_over_dc(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "dc:description": "old",
            "dct:description": "new",
            "tableSchema": {"columns": []},
        }
        meta = csvw_to_metadata(table)
        assert meta.description == "new"

    def test_description_does_not_leak_into_custom_properties(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "dc:description": "hi",
            "tableSchema": {"columns": []},
        }
        meta = csvw_to_metadata(table)
        # description goes to its dedicated field, not custom_properties
        assert meta.description == "hi"
        # custom_properties should be None (or at least not contain description keys)
        assert meta.custom_properties is None or "dc:description" not in meta.custom_properties
        assert meta.custom_properties is None or "dct:description" not in meta.custom_properties


class TestMetadataToCsvwTable:
    def test_minimal_metadata_yields_minimal_table(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import Metadata

        table = metadata_to_csvw_table(Path("foo.csv"), Metadata())
        assert table["url"] == "foo.csv"
        assert table["tableSchema"]["columns"] == []
        assert "dct:description" not in table

    def test_field_metadata_maps_to_columns(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import FieldSchema, Metadata

        meta = Metadata(
            description="weekly aggregates",
            field_metadata={
                "x": FieldSchema(name="x", type="integer", description="count"),
                "y": FieldSchema(name="y", type="decimal"),
            },
        )
        table = metadata_to_csvw_table(Path("data/foo.csv"), meta)
        assert table["url"] == "data/foo.csv"
        assert table["dct:description"] == "weekly aggregates"
        cols = {c["name"]: c for c in table["tableSchema"]["columns"]}
        assert cols["x"]["datatype"] == "integer"
        assert cols["x"]["dct:description"] == "count"
        assert cols["y"]["datatype"] == "decimal"
        assert "dct:description" not in cols["y"]

    def test_custom_properties_pass_through(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import Metadata

        meta = Metadata(custom_properties={"ex:thing": "value"})
        table = metadata_to_csvw_table(Path("foo.csv"), meta)
        assert table["ex:thing"] == "value"

    def test_round_trip_recovers_field_descriptions_and_types(self):
        from pathlib import Path

        from sunstone._csvw import csvw_to_metadata, metadata_to_csvw_table
        from sunstone.lineage import FieldSchema, Metadata

        original = Metadata(
            description="round trip",
            field_metadata={
                "a": FieldSchema(name="a", type="integer", description="alpha"),
                "b": FieldSchema(name="b", type="string"),
            },
        )
        recovered = csvw_to_metadata(metadata_to_csvw_table(Path("rt.csv"), original))
        assert recovered.description == "round trip"
        assert recovered.field_metadata["a"].type == "integer"
        assert recovered.field_metadata["a"].description == "alpha"
        assert recovered.field_metadata["b"].type == "string"

    def test_uses_posix_url(self):
        """URL in csvw is forward-slash even on Windows."""
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import Metadata

        table = metadata_to_csvw_table(Path("a") / "b" / "c.csv", Metadata())
        assert table["url"] == "a/b/c.csv"

    def test_writes_dct_description_not_dc(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import FieldSchema, Metadata

        meta = Metadata(
            description="dataset desc",
            field_metadata={"x": FieldSchema(name="x", description="col desc")},
        )
        table = metadata_to_csvw_table(Path("foo.csv"), meta)
        assert table.get("dct:description") == "dataset desc"
        assert "dc:description" not in table
        col = table["tableSchema"]["columns"][0]
        assert col.get("dct:description") == "col desc"
        assert "dc:description" not in col


def _make_handler():
    """Return a LocalFileHandler instance for tests."""
    from sunstone.handlers import LocalFileHandler

    return LocalFileHandler()


def _write_sidecar_json(path, table_url):
    path.write_text(
        json.dumps(
            {
                "@context": "http://www.w3.org/ns/csvw",
                "url": table_url,
                "tableSchema": {"columns": [{"name": "x"}]},
            }
        )
    )


def _write_table_group_json(path, table_urls):
    path.write_text(
        json.dumps(
            {
                "@context": "http://www.w3.org/ns/csvw",
                "tables": [{"url": u, "tableSchema": {"columns": [{"name": "x"}]}} for u in table_urls],
            }
        )
    )


def test_table_for_data_path_matches_sidecar_relative(tmp_path):
    """_table_for_data_path matches a relative-from-sidecar-dir URL
    when sidecar_dir is provided."""
    from sunstone._csvw import _table_for_data_path

    sidecar_dir = tmp_path
    data = tmp_path / "inputs" / "a.csv"

    doc = {
        "@context": "http://www.w3.org/ns/csvw",
        "tables": [
            {"url": "inputs/a.csv", "tableSchema": {"columns": [{"name": "x"}]}},
        ],
    }
    # Without sidecar_dir, it shouldn't match (only basename / abs POSIX checked)
    assert _table_for_data_path(doc, data) is None
    # With sidecar_dir, it should match
    result = _table_for_data_path(doc, data, sidecar_dir=sidecar_dir)
    assert result is not None
    assert result["url"] == "inputs/a.csv"


class TestFindSidecarTier1:
    def test_no_sidecar_returns_none(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        assert find_sidecar(csv, _make_handler()) is None

    def test_canonical_csv_metadata_json_wins(self, tmp_path):
        """data.csv -> data.csv-metadata.json (W3C convention)."""
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        _write_sidecar_json(sidecar, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        path, table_dict = result
        assert path == sidecar
        assert table_dict["url"] == "data.csv"

    def test_dash_metadata_json_secondary(self, tmp_path):
        """data.csv -> data-metadata.json (alternate W3C form)."""
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data-metadata.json"
        _write_sidecar_json(sidecar, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == sidecar

    def test_csvm_json_tier1_tertiary(self, tmp_path):
        """data.csv -> data.csvm.json (sunstone-specific)."""
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csvm.json"
        _write_sidecar_json(sidecar, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == sidecar

    def test_first_tier1_match_wins(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        # Create both #1 and #2; #1 should win
        first = tmp_path / "data.csv-metadata.json"
        second = tmp_path / "data-metadata.json"
        _write_sidecar_json(first, "data.csv")
        _write_sidecar_json(second, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == first

    def test_tier1_strict_malformed_json_raises(self, tmp_path):
        from sunstone._csvw import find_sidecar
        from sunstone.exceptions import CSVWSidecarError

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        sidecar.write_text("{ this is not json")

        with pytest.raises(CSVWSidecarError):
            find_sidecar(csv, _make_handler())

    def test_tier1_strict_non_csvw_raises(self, tmp_path):
        from sunstone._csvw import find_sidecar
        from sunstone.exceptions import CSVWSidecarError

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        sidecar.write_text(json.dumps({"unrelated": "content"}))

        with pytest.raises(CSVWSidecarError):
            find_sidecar(csv, _make_handler())

    def test_tier1_strict_table_mismatch_raises(self, tmp_path):
        """Tier-1 sidecar parses as valid CSVW but its url doesn't match
        the target CSV → CSVWSidecarError."""
        from sunstone._csvw import find_sidecar
        from sunstone.exceptions import CSVWSidecarError

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        # Valid CSVW shape but url points to a different CSV
        _write_sidecar_json(sidecar, "different.csv")

        with pytest.raises(CSVWSidecarError):
            find_sidecar(csv, _make_handler())


class TestFindSidecarTier2:
    def test_csvm_json_multi_table_match(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "csvm.json"
        _write_table_group_json(sidecar, ["data.csv", "other.csv"])

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        path, table = result
        assert path == sidecar
        assert table["url"] == "data.csv"

    def test_metadata_json_multi_table_match(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "metadata.json"
        _write_table_group_json(sidecar, ["data.csv"])

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == sidecar

    def test_csvm_json_no_table_for_this_csv_returns_none(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "csvm.json"
        _write_table_group_json(sidecar, ["other.csv"])

        # Authoritative for this directory; do not fall through.
        assert find_sidecar(csv, _make_handler()) is None

    def test_lenient_metadata_json_invalid_is_skipped(self, tmp_path, caplog):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        bad = tmp_path / "metadata.json"
        bad.write_text("{ this is not json")
        # csvm.json with a real match should still be found
        good = tmp_path / "csvm.json"
        _write_table_group_json(good, ["data.csv"])

        with caplog.at_level(logging.INFO, logger="sunstone._csvw"):
            result = find_sidecar(csv, _make_handler())
        assert result is not None
        # The lenient skip is not asserted to log specifically (depends
        # on lookup order: csvm.json comes BEFORE metadata.json).
        assert result[0] == good

    def test_lenient_csvm_json_invalid_falls_through_to_metadata_json(self, tmp_path, caplog):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        bad = tmp_path / "csvm.json"
        bad.write_text("{ broken")
        good = tmp_path / "metadata.json"
        _write_table_group_json(good, ["data.csv"])

        with caplog.at_level(logging.INFO, logger="sunstone._csvw"):
            result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == good
        # The bad csvm.json should have produced an INFO log
        assert any("csvm.json" in r.message for r in caplog.records)

    def test_tier1_short_circuits_tier2(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        # Tier-1 sidecar exists; tier-2 csvm also exists
        tier1 = tmp_path / "data.csv-metadata.json"
        _write_sidecar_json(tier1, "data.csv")
        tier2 = tmp_path / "csvm.json"
        _write_table_group_json(tier2, ["data.csv"])

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == tier1


class TestUpsertTableInSidecar:
    def test_creates_new_sidecar_when_missing(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csv = tmp_path / "a.csv"
        sidecar = tmp_path / "a.csv-metadata.json"
        table = metadata_to_csvw_table(csv, Metadata(description="hello"))

        upsert_table_in_sidecar(sidecar, csv, table, _make_handler())

        assert sidecar.exists()
        doc = json.loads(sidecar.read_text())
        assert doc["@context"] == "http://www.w3.org/ns/csvw"
        # Single-csv sibling sidecar style: stored as a TableGroup with
        # one table to keep one consistent on-disk shape.
        assert "tables" in doc
        assert len(doc["tables"]) == 1
        assert doc["tables"][0]["url"] == "a.csv"
        assert doc["tables"][0]["dct:description"] == "hello"

    def test_appends_table_to_existing_csvm(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "shared.csvm.json"
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"

        upsert_table_in_sidecar(
            csvm,
            a,
            metadata_to_csvw_table(a, Metadata(description="A")),
            _make_handler(),
        )
        upsert_table_in_sidecar(
            csvm,
            b,
            metadata_to_csvw_table(b, Metadata(description="B")),
            _make_handler(),
        )

        doc = json.loads(csvm.read_text())
        urls = sorted(t["url"] for t in doc["tables"])
        assert urls == ["a.csv", "b.csv"]

    def test_replaces_existing_entry_for_same_csv(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "csvm.json"
        a = tmp_path / "a.csv"

        upsert_table_in_sidecar(
            csvm,
            a,
            metadata_to_csvw_table(a, Metadata(description="first")),
            _make_handler(),
        )
        upsert_table_in_sidecar(
            csvm,
            a,
            metadata_to_csvw_table(a, Metadata(description="second")),
            _make_handler(),
        )

        doc = json.loads(csvm.read_text())
        assert len(doc["tables"]) == 1
        assert doc["tables"][0]["dct:description"] == "second"

    def test_refuses_to_clobber_non_csvw_file(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.exceptions import CSVWSidecarError
        from sunstone.lineage import Metadata

        csvm = tmp_path / "important.json"
        csvm.write_text(json.dumps({"unrelated": "config"}))
        a = tmp_path / "a.csv"

        with pytest.raises(CSVWSidecarError):
            upsert_table_in_sidecar(csvm, a, metadata_to_csvw_table(a, Metadata()), _make_handler())
        # Original file untouched
        assert json.loads(csvm.read_text()) == {"unrelated": "config"}

    def test_no_temp_files_left_on_success(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        sidecar = tmp_path / "a.csv-metadata.json"
        a = tmp_path / "a.csv"
        upsert_table_in_sidecar(sidecar, a, metadata_to_csvw_table(a, Metadata()), _make_handler())
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_preserves_original_on_write_failure(self, tmp_path, monkeypatch):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "csvm.json"
        a = tmp_path / "a.csv"

        # First write succeeds
        upsert_table_in_sidecar(
            csvm,
            a,
            metadata_to_csvw_table(a, Metadata(description="original")),
            _make_handler(),
        )
        original = csvm.read_text()

        # Force the JSON dump to fail
        import sunstone._csvw as csvw_mod

        def boom(*args, **kwargs):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(csvw_mod.json, "dumps", boom)

        with pytest.raises(RuntimeError):
            upsert_table_in_sidecar(
                csvm,
                a,
                metadata_to_csvw_table(a, Metadata(description="new")),
                _make_handler(),
            )

        # Original file untouched
        assert csvm.read_text() == original
        # No leftover temp files
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_replaces_entry_with_absolute_url(self, tmp_path):
        """An existing entry written with an absolute URL is replaced
        (not duplicated) when upserting the same data_path."""
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "csvm.json"
        a = tmp_path / "a.csv"

        # Hand-author a csvm with an ABSOLUTE url for a.csv
        csvm.write_text(
            json.dumps(
                {
                    "@context": "http://www.w3.org/ns/csvw",
                    "tables": [
                        {
                            "url": str(a),  # absolute path, what someone might hand-write
                            "tableSchema": {"columns": [{"name": "x"}]},
                            "dct:description": "old",
                        },
                    ],
                }
            )
        )

        upsert_table_in_sidecar(
            csvm,
            a,
            metadata_to_csvw_table(a, Metadata(description="new")),
            _make_handler(),
        )

        doc = json.loads(csvm.read_text())
        assert len(doc["tables"]) == 1, f"expected 1 table after upsert, got {len(doc['tables'])}: {doc['tables']}"
        assert doc["tables"][0].get("dct:description") == "new"


class TestEnumerateSidecarsFor:
    def test_no_sidecars_yields_empty_list(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        result = enumerate_sidecars_for([a])
        assert result == []

    def test_per_csv_sidecar_becomes_resource(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        sidecar = tmp_path / "a.csv-metadata.json"
        _write_sidecar_json(sidecar, "a.csv")

        result = enumerate_sidecars_for([a])
        assert len(result) == 1
        sr = result[0]
        assert sr.path == sidecar
        assert sr.covers == [a]
        assert "csvwMetadata" in sr.cross_ref_property

    def test_shared_csvm_covering_all_csvs_passes(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        for c in (a, b):
            c.write_text("x\n1\n")
        csvm = tmp_path / "shared.csvm.json"
        _write_table_group_json(csvm, ["a.csv", "b.csv"])

        # Note: shared.csvm.json is NOT one of the auto-discoverable
        # tier-1/tier-2 names. enumerate_sidecars_for must accept an
        # additional list of explicit sidecar paths from the registry of
        # writes. For now the auto-discovery test below covers the
        # tier-2 csvm.json path; explicit-path coverage is added in a
        # later task once the BuiltinFormatHandler can pass tracked
        # writes through.
        # Skip until then by writing tier-2 csvm.json:
        csvm2 = tmp_path / "csvm.json"
        _write_table_group_json(csvm2, ["a.csv", "b.csv"])

        result = enumerate_sidecars_for([a, b])
        # Should find csvm.json covering both
        assert any(sr.path == csvm2 for sr in result)
        sr = next(r for r in result if r.path == csvm2)
        assert set(sr.covers) == {a, b}

    def test_csvm_referencing_extra_csv_raises(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for
        from sunstone.exceptions import PackageValidationError

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        # csvm references a.csv AND a phantom outsider.csv
        csvm = tmp_path / "csvm.json"
        _write_table_group_json(csvm, ["a.csv", "outsider.csv"])

        with pytest.raises(PackageValidationError) as exc_info:
            enumerate_sidecars_for([a])
        assert "outsider.csv" in str(exc_info.value)
        assert str(csvm.name) in str(exc_info.value) or "csvm.json" in str(exc_info.value)

    def test_per_csv_sidecar_only_covers_one_csv(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        for c in (a, b):
            c.write_text("x\n1\n")
        sidecar_a = tmp_path / "a.csv-metadata.json"
        _write_sidecar_json(sidecar_a, "a.csv")

        result = enumerate_sidecars_for([a, b])
        assert len(result) == 1
        assert result[0].covers == [a]

    def test_extra_sidecar_path_nonexistent_raises(self, tmp_path):
        """A caller-supplied extra sidecar path that doesn't exist on disk
        is treated as a structural failure (not silently skipped)."""
        from sunstone._csvw import enumerate_sidecars_for
        from sunstone.exceptions import PackageValidationError

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        missing = tmp_path / "i-do-not-exist.csvm.json"

        with pytest.raises(PackageValidationError):
            enumerate_sidecars_for([a], extra_sidecar_paths=[missing])

    def test_returns_caller_passed_paths_not_resolved(self, tmp_path):
        """SidecarResource.path and covers preserve the caller's path
        forms (no .resolve() leakage on macOS /var/folders -> /private/var/folders)."""
        from sunstone._csvw import enumerate_sidecars_for

        # Use an explicit non-resolved path constructed from a Path object
        # (tmp_path is already resolved on most platforms but build a path
        # via .. to force unresolved-ness)
        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        sidecar = tmp_path / "a.csv-metadata.json"
        _write_sidecar_json(sidecar, "a.csv")

        # Pass an unresolved path (relative-form via parent + name)
        unresolved = tmp_path.parent / tmp_path.name / "a.csv"

        result = enumerate_sidecars_for([unresolved])
        assert len(result) == 1
        # covers should contain the path the caller passed (not its .resolve() form)
        assert result[0].covers == [unresolved]
