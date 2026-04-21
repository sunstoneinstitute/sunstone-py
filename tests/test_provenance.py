"""
Tests for PROV-O aligned provenance types.

Tests the new Agent, Activity, FieldDerivation, UsageRecord, EntityRef types
and their integration with session flush, datasets.yaml serialization, and
DataFrame operations.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from ruamel.yaml import YAML

import sunstone
from sunstone.lineage import (
    Activity,
    Agent,
    AgentType,
    EntityRef,
    FieldDerivation,
    LineageMetadata,
    Metadata,
    UsageRecord,
)
from sunstone.session import DatasetRead, LineageSession, close_session


# ---------------------------------------------------------------------------
# Unit tests for PROV-O types
# ---------------------------------------------------------------------------


class TestAgent:
    def test_default_type_is_person(self) -> None:
        agent = Agent(id="alice")
        assert agent.type == AgentType.PERSON

    def test_software_agent(self) -> None:
        agent = Agent(id="sunstone-py", type=AgentType.SOFTWARE, version="1.0.0")
        assert agent.type == AgentType.SOFTWARE
        assert agent.version == "1.0.0"

    def test_organization_agent(self) -> None:
        agent = Agent(id="UN", type=AgentType.ORGANIZATION, label="United Nations")
        assert agent.type == AgentType.ORGANIZATION
        assert agent.label == "United Nations"

    def test_agent_type_values(self) -> None:
        assert AgentType.PERSON.value == "prov:Person"
        assert AgentType.SOFTWARE.value == "prov:SoftwareAgent"
        assert AgentType.ORGANIZATION.value == "prov:Organization"


class TestEntityRef:
    def test_basic_ref(self) -> None:
        ref = EntityRef(slug="my-dataset")
        assert ref.slug == "my-dataset"
        assert ref.namespace is None

    def test_ref_with_namespace(self) -> None:
        ref = EntityRef(slug="data", namespace="https://example.org/")
        assert ref.namespace == "https://example.org/"

    def test_frozen(self) -> None:
        ref = EntityRef(slug="test")
        with pytest.raises(AttributeError):
            ref.slug = "changed"  # type: ignore[misc]


class TestFieldDerivation:
    def test_basic(self) -> None:
        fd = FieldDerivation(output_field="Country", source_entity="raw-data", source_field="Member State")
        assert fd.output_field == "Country"
        assert fd.source_entity == "raw-data"
        assert fd.source_field == "Member State"

    def test_no_source_field(self) -> None:
        fd = FieldDerivation(output_field="score", source_entity="input-data")
        assert fd.source_field is None


class TestUsageRecord:
    def test_basic(self) -> None:
        ur = UsageRecord(entity=EntityRef(slug="input-1"))
        assert ur.entity.slug == "input-1"
        assert ur.columns is None
        assert ur.filters is None

    def test_with_columns_and_filters(self) -> None:
        ur = UsageRecord(
            entity=EntityRef(slug="input-1"),
            columns=["a", "b"],
            filters={"year": 2024},
        )
        assert ur.columns == ["a", "b"]
        assert ur.filters == {"year": 2024}


class TestActivity:
    def test_basic(self) -> None:
        a = Activity(id="exec-abc123")
        assert a.id == "exec-abc123"
        assert a.used == []
        assert a.generated == []
        assert a.was_associated_with == []

    def test_full(self) -> None:
        a = Activity(
            id="exec-abc123",
            used=[UsageRecord(entity=EntityRef(slug="input-1"))],
            generated=[EntityRef(slug="output-1")],
            was_associated_with=[
                Agent(id="alice", type=AgentType.PERSON),
                Agent(id="sunstone-py", type=AgentType.SOFTWARE, version="1.0"),
            ],
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
            script_path="scripts/process.py",
            git_commit="abc123",
            git_dirty=False,
            transformation_params={"threshold": 100},
        )
        assert len(a.used) == 1
        assert len(a.was_associated_with) == 2
        assert a.transformation_params == {"threshold": 100}


# ---------------------------------------------------------------------------
# DatasetRead.to_usage_record
# ---------------------------------------------------------------------------


class TestDatasetReadConversion:
    def test_to_usage_record(self) -> None:
        dr = DatasetRead(slug="my-data", columns=["a", "b"], filters={"x": 1})
        ur = dr.to_usage_record()
        assert ur.entity.slug == "my-data"
        assert ur.columns == ["a", "b"]
        assert ur.filters == {"x": 1}

    def test_to_usage_record_minimal(self) -> None:
        dr = DatasetRead(slug="simple")
        ur = dr.to_usage_record()
        assert ur.entity.slug == "simple"
        assert ur.columns is None
        assert ur.filters is None


# ---------------------------------------------------------------------------
# Session flush_activity
# ---------------------------------------------------------------------------


def _mock_detect_context() -> Any:
    from sunstone.context import ExecutionContext

    return ExecutionContext(
        user="test-user",
        script_path="scripts/process.py",
        execution_timestamp="2026-01-15T10:00:00+00:00",
    )


class TestSessionFlushActivity:
    @pytest.fixture(autouse=True)
    def _fresh_session(self) -> Generator[None]:
        close_session()
        yield
        close_session()

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_flush_activity_basic(self, mock_ctx: Any) -> None:
        session = LineageSession()
        session.record_read(DatasetRead(slug="input-1"))
        session.record_read(DatasetRead(slug="input-2"))

        activity = session.flush_activity()

        assert activity.id.startswith("exec-")
        assert len(activity.used) == 2
        assert activity.used[0].entity.slug == "input-1"
        assert activity.used[1].entity.slug == "input-2"
        assert activity.script_path == "scripts/process.py"
        assert activity.started_at is not None
        assert activity.ended_at is not None

        # Agents: person + software
        assert len(activity.was_associated_with) == 2
        person = activity.was_associated_with[0]
        software = activity.was_associated_with[1]
        assert person.id == "test-user"
        assert person.type == AgentType.PERSON
        assert software.id == "sunstone-py"
        assert software.type == AgentType.SOFTWARE

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_flush_activity_clears_reads(self, mock_ctx: Any) -> None:
        session = LineageSession()
        session.record_read(DatasetRead(slug="input-1"))
        session.flush_activity()

        # Second flush should have no reads
        activity2 = session.flush_activity()
        assert len(activity2.used) == 0

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_flush_to_output_includes_activity(self, mock_ctx: Any) -> None:
        session = LineageSession()
        session.record_read(DatasetRead(slug="input-1"))

        result = session.flush_to_output(transformation_params={"k": "v"})

        assert "_activity" in result
        activity = result["_activity"]
        assert isinstance(activity, Activity)
        assert activity.used[0].entity.slug == "input-1"
        assert activity.transformation_params == {"k": "v"}

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_flush_activity_deterministic_id(self, mock_ctx: Any) -> None:
        """Same context produces the same activity ID."""
        s1 = LineageSession()
        s1.record_read(DatasetRead(slug="x"))
        a1 = s1.flush_activity()

        s2 = LineageSession()
        s2.record_read(DatasetRead(slug="y"))
        a2 = s2.flush_activity()

        assert a1.id == a2.id  # Same context → same ID


# ---------------------------------------------------------------------------
# ExecutionContext.to_agents
# ---------------------------------------------------------------------------


class TestContextToAgents:
    def test_to_agents_with_user(self) -> None:
        from sunstone.context import ExecutionContext

        ctx = ExecutionContext(user="stig")
        agents = ctx.to_agents()

        assert len(agents) == 2
        assert agents[0].id == "stig"
        assert agents[0].type == AgentType.PERSON
        assert agents[1].id == "sunstone-py"
        assert agents[1].type == AgentType.SOFTWARE

    def test_to_agents_without_user(self) -> None:
        from sunstone.context import ExecutionContext

        ctx = ExecutionContext()
        agents = ctx.to_agents()

        # Only software agent when no user
        assert len(agents) == 1
        assert agents[0].id == "sunstone-py"


# ---------------------------------------------------------------------------
# LineageMetadata.merge with field_derivations
# ---------------------------------------------------------------------------


class TestLineageMergeFieldDerivations:
    def test_merge_both_have_derivations(self) -> None:
        lm1 = LineageMetadata(
            field_derivations=[
                FieldDerivation(output_field="a", source_entity="ds1"),
            ]
        )
        lm2 = LineageMetadata(
            field_derivations=[
                FieldDerivation(output_field="b", source_entity="ds2"),
            ]
        )
        merged = lm1.merge(lm2)
        assert merged.field_derivations is not None
        assert len(merged.field_derivations) == 2
        fields = {d.output_field for d in merged.field_derivations}
        assert fields == {"a", "b"}

    def test_merge_one_has_derivations(self) -> None:
        lm1 = LineageMetadata(
            field_derivations=[
                FieldDerivation(output_field="a", source_entity="ds1"),
            ]
        )
        lm2 = LineageMetadata()
        merged = lm1.merge(lm2)
        assert merged.field_derivations is not None
        assert len(merged.field_derivations) == 1

    def test_merge_deduplicates(self) -> None:
        fd = FieldDerivation(output_field="a", source_entity="ds1")
        lm1 = LineageMetadata(field_derivations=[fd])
        lm2 = LineageMetadata(field_derivations=[fd])
        merged = lm1.merge(lm2)
        assert merged.field_derivations is not None
        assert len(merged.field_derivations) == 1

    def test_merge_neither_has_derivations(self) -> None:
        lm1 = LineageMetadata()
        lm2 = LineageMetadata()
        merged = lm1.merge(lm2)
        assert merged.field_derivations is None


# ---------------------------------------------------------------------------
# Source.agent property
# ---------------------------------------------------------------------------


class TestSourceAgent:
    def test_string_attributed_to_returns_org_agent(self) -> None:
        from sunstone.lineage import Source, SourceLocation

        s = Source(
            name="Test",
            location=SourceLocation(),
            attributed_to="United Nations",
            acquired_at="2026-01-01",
            acquisition_method="manual",
            license="CC-BY-4.0",
        )
        agent = s.agent
        assert agent.id == "United Nations"
        assert agent.type == AgentType.ORGANIZATION

    def test_agent_attributed_to_returns_same(self) -> None:
        from sunstone.lineage import Source, SourceLocation

        a = Agent(id="UN", type=AgentType.ORGANIZATION)
        s = Source(
            name="Test",
            location=SourceLocation(),
            attributed_to=a,
            acquired_at="2026-01-01",
            acquisition_method="manual",
            license="CC-BY-4.0",
        )
        assert s.agent is a


# ---------------------------------------------------------------------------
# datasets.yaml round-trip: Activity + FieldDerivations
# ---------------------------------------------------------------------------


class TestDatasetsYamlRoundTrip:
    @pytest.fixture
    def project_with_output(self, tmp_path: Path) -> Path:
        project = tmp_path / "proj"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "outputs").mkdir()
        (project / "inputs" / "data.csv").write_text("id,name\n1,Alice\n")

        yaml = YAML()
        yaml.default_flow_style = False
        data = {
            "inputs": [
                {
                    "name": "Input Data",
                    "slug": "input-data",
                    "location": "inputs/data.csv",
                    "fields": [
                        {"name": "id", "type": "integer"},
                        {"name": "name", "type": "string"},
                    ],
                    "source": {
                        "name": "Test Source",
                        "location": {"data": None},
                        "attributedTo": "Test Org",
                        "acquiredAt": "2026-01-01",
                        "acquisitionMethod": "manual",
                        "license": "CC-BY-4.0",
                    },
                },
            ],
            "outputs": [
                {
                    "name": "Output Data",
                    "slug": "output-data",
                    "location": "outputs/out.csv",
                    "fields": [
                        {"name": "id", "type": "integer"},
                        {"name": "name", "type": "string"},
                    ],
                },
            ],
        }
        with open(project / "datasets.yaml", "w") as f:
            yaml.dump(data, f)

        return project

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_activity_persisted_to_yaml(self, mock_ctx: Any, project_with_output: Path) -> None:
        """Writing an output should persist an activity section in lock file."""
        close_session()

        df = sunstone.DataFrame.read_dataset("input-data", project_path=project_with_output)
        df.to_csv("outputs/out.csv", index=False)

        yaml = YAML()
        with open(project_with_output / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "output-data")

        assert "activity" in lock_output
        activity = lock_output["activity"]
        assert activity["id"].startswith("exec-")
        assert "agents" in activity
        assert any(a["id"] == "test-user" for a in activity["agents"])
        assert any(a["type"] == "prov:SoftwareAgent" for a in activity["agents"])
        assert "used" in activity
        assert any(u["entity"] == "input-data" for u in activity["used"])

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_field_derivations_persisted_to_yaml(self, mock_ctx: Any, project_with_output: Path) -> None:
        """Setting field source metadata should persist field_derivations in lock file."""
        close_session()

        df = sunstone.DataFrame.read_dataset("input-data", project_path=project_with_output)
        df.set_field_metadata("name", source="input-data")
        df.to_csv("outputs/out.csv", index=False)

        yaml = YAML()
        with open(project_with_output / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "output-data")

        assert "field_derivations" in lock_output
        fd = lock_output["field_derivations"]
        fd_by_field = {d["output_field"]: d for d in fd}

        # Auto-populated derivation for 'id'
        assert fd_by_field["id"]["source_entity"] == "input-data"
        assert fd_by_field["id"]["source_field"] == "id"

        # Explicitly set derivation for 'name' (replaces auto-populated one)
        assert fd_by_field["name"]["source_entity"] == "input-data"

    def test_activity_parsed_from_yaml(self, tmp_path: Path) -> None:
        """Activity section in datasets.yaml should be parseable."""
        project = tmp_path / "parse_proj"
        project.mkdir()
        (project / "outputs").mkdir()

        yaml = YAML()
        data = {
            "inputs": [],
            "outputs": [
                {
                    "name": "Output",
                    "slug": "output-data",
                    "location": "outputs/out.csv",
                    "fields": [{"name": "id", "type": "integer"}],
                    "lineage": {
                        "content_hash": "abc123",
                        "created_at": "2026-01-15T10:00:00",
                        "sources": [{"slug": "input-data"}],
                        "activity": {
                            "id": "exec-abc123",
                            "started_at": "2026-01-15T10:00:00",
                            "ended_at": "2026-01-15T10:05:00",
                            "script_path": "scripts/process.py",
                            "git_commit": "abc123",
                            "agents": [
                                {"id": "alice", "type": "prov:Person"},
                                {"id": "sunstone-py", "type": "prov:SoftwareAgent", "version": "1.0"},
                            ],
                            "used": [
                                {"entity": "input-data", "columns": ["id"]},
                            ],
                        },
                        "field_derivations": [
                            {
                                "output_field": "id",
                                "source_entity": "input-data",
                                "source_field": "id",
                            },
                        ],
                    },
                },
            ],
        }
        with open(project / "datasets.yaml", "w") as f:
            yaml.dump(data, f)

        from sunstone.datasets import DatasetsManager

        mgr = DatasetsManager(project)
        ds = mgr.find_dataset_by_slug("output-data", dataset_type="output")
        assert ds is not None

        # PROV-O fields should be populated
        assert ds.was_derived_from is not None
        assert len(ds.was_derived_from) == 1
        assert ds.was_derived_from[0].slug == "input-data"

        assert ds.was_generated_by is not None
        assert ds.was_generated_by.id == "exec-abc123"

        assert ds.generated_at_time is not None

        assert ds.field_derivations is not None
        assert len(ds.field_derivations) == 1
        assert ds.field_derivations[0].source_field == "id"

    def test_old_format_without_activity_still_parses(self, tmp_path: Path) -> None:
        """datasets.yaml without activity section should still parse fine."""
        project = tmp_path / "old_proj"
        project.mkdir()
        (project / "outputs").mkdir()

        yaml = YAML()
        data = {
            "inputs": [],
            "outputs": [
                {
                    "name": "Output",
                    "slug": "output-data",
                    "location": "outputs/out.csv",
                    "fields": [{"name": "id", "type": "integer"}],
                    "lineage": {
                        "content_hash": "abc123",
                        "created_at": "2026-01-15T10:00:00",
                        "sources": [{"slug": "input-data"}],
                        "context": {"user": "alice"},
                    },
                },
            ],
        }
        with open(project / "datasets.yaml", "w") as f:
            yaml.dump(data, f)

        from sunstone.datasets import DatasetsManager

        mgr = DatasetsManager(project)
        ds = mgr.find_dataset_by_slug("output-data", dataset_type="output")
        assert ds is not None
        assert ds.was_derived_from is not None
        assert ds.was_generated_by is None  # No activity in old format
        assert ds.field_derivations is None


# ---------------------------------------------------------------------------
# DataFrame field_derivations propagation
# ---------------------------------------------------------------------------


class TestFieldDerivationPropagation:
    def test_wrap_result_filters_derivations(self) -> None:
        """_wrap_result should filter out field_derivations for dropped columns."""
        import pandas as pd

        meta = Metadata(
            lineage=LineageMetadata(
                field_derivations=[
                    FieldDerivation(output_field="a", source_entity="ds1"),
                    FieldDerivation(output_field="b", source_entity="ds1"),
                    FieldDerivation(output_field="c", source_entity="ds2"),
                ]
            )
        )
        df = sunstone.DataFrame(data=pd.DataFrame({"a": [1], "b": [2], "c": [3]}), metadata=meta)

        # Select only columns a and c
        result = df[["a", "c"]]
        assert result.metadata.lineage.field_derivations is not None
        assert len(result.metadata.lineage.field_derivations) == 2
        fields = {d.output_field for d in result.metadata.lineage.field_derivations}
        assert fields == {"a", "c"}

    def test_set_field_metadata_creates_derivation(self) -> None:
        """set_field_metadata with source should create a FieldDerivation."""
        import pandas as pd

        df = sunstone.DataFrame(data=pd.DataFrame({"x": [1]}))
        df.set_field_metadata("x", source="input-ds")

        assert df.metadata.lineage.field_derivations is not None
        assert len(df.metadata.lineage.field_derivations) == 1
        assert df.metadata.lineage.field_derivations[0].output_field == "x"
        assert df.metadata.lineage.field_derivations[0].source_entity == "input-ds"

    def test_set_field_metadata_replaces_derivation(self) -> None:
        """Setting source again replaces the derivation, not duplicates."""
        import pandas as pd

        df = sunstone.DataFrame(data=pd.DataFrame({"x": [1]}))
        df.set_field_metadata("x", source="ds1")
        df.set_field_metadata("x", source="ds2")

        assert df.metadata.lineage.field_derivations is not None
        assert len(df.metadata.lineage.field_derivations) == 1
        assert df.metadata.lineage.field_derivations[0].source_entity == "ds2"


# ---------------------------------------------------------------------------
# LineageNode with Activity
# ---------------------------------------------------------------------------


class TestLineageNodeActivity:
    def test_lineage_node_with_activity(self, tmp_path: Path) -> None:
        """get_upstream should populate activity on LineageNode."""
        project = tmp_path / "proj"
        project.mkdir()

        yaml = YAML()
        data = {
            "inputs": [
                {
                    "name": "Input",
                    "slug": "input-data",
                    "location": "inputs/data.csv",
                    "fields": [{"name": "id", "type": "integer"}],
                    "source": {
                        "name": "Test",
                        "location": {"data": None},
                        "attributedTo": "Test",
                        "acquiredAt": "2026-01-01",
                        "acquisitionMethod": "manual",
                        "license": "CC-BY-4.0",
                    },
                },
            ],
            "outputs": [
                {
                    "name": "Output",
                    "slug": "output-data",
                    "location": "outputs/out.csv",
                    "fields": [{"name": "id", "type": "integer"}],
                    "lineage": {
                        "content_hash": "abc",
                        "sources": [{"slug": "input-data"}],
                        "activity": {
                            "id": "exec-test",
                            "agents": [{"id": "alice", "type": "prov:Person"}],
                            "used": [{"entity": "input-data"}],
                        },
                    },
                },
            ],
        }
        with open(project / "datasets.yaml", "w") as f:
            yaml.dump(data, f)

        from sunstone.queries import get_upstream, lineage_to_dict

        node = get_upstream("output-data", project_path=project)
        assert node.activity is not None
        assert node.activity.id == "exec-test"
        assert node.activity.was_associated_with[0].id == "alice"

        # lineage_to_dict should include activity
        d = lineage_to_dict(node)
        assert "activity" in d
        assert d["activity"]["id"] == "exec-test"
