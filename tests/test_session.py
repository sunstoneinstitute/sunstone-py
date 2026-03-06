"""
Unit tests for LineageSession, get_session, close_session.
"""

from unittest.mock import patch


from sunstone.session import DatasetRead, LineageSession, close_session, get_session


class TestDatasetRead:
    """Tests for DatasetRead dataclass."""

    def test_basic_creation(self):
        """Should create a DatasetRead with slug."""
        dr = DatasetRead(slug="my-dataset")
        assert dr.slug == "my-dataset"
        assert dr.version is None
        assert dr.columns is None
        assert dr.filters is None

    def test_with_all_fields(self):
        """Should create DatasetRead with all fields."""
        dr = DatasetRead(
            slug="my-dataset",
            version="v1",
            columns=["col1", "col2"],
            filters={"country": "US"},
        )
        assert dr.version == "v1"
        assert dr.columns == ["col1", "col2"]
        assert dr.filters == {"country": "US"}


class TestLineageSession:
    """Tests for LineageSession."""

    def test_record_read(self):
        """Should accumulate DatasetRead entries."""
        session = LineageSession()
        session.record_read(DatasetRead(slug="dataset-a"))
        session.record_read(DatasetRead(slug="dataset-b"))
        assert len(session._reads) == 2

    def test_record_read_deduplication(self):
        """Should deduplicate by slug:version key."""
        session = LineageSession()
        session.record_read(DatasetRead(slug="dataset-a", version="v1"))
        session.record_read(DatasetRead(slug="dataset-a", version="v1"))
        assert len(session._reads) == 1

    def test_record_read_different_versions_not_deduped(self):
        """Different versions of same slug should not be deduped."""
        session = LineageSession()
        session.record_read(DatasetRead(slug="dataset-a", version="v1"))
        session.record_read(DatasetRead(slug="dataset-a", version="v2"))
        assert len(session._reads) == 2

    @patch("sunstone.context.detect_execution_context")
    def test_flush_to_output_returns_sources_and_context(self, mock_ctx):
        """flush_to_output() should return dict with sources and context."""
        from sunstone.context import ExecutionContext

        mock_ctx.return_value = ExecutionContext(
            user="testuser",
            execution_timestamp="2026-01-01T00:00:00",
        )
        session = LineageSession()
        session.record_read(DatasetRead(slug="dataset-a"))
        result = session.flush_to_output()
        assert "sources" in result
        assert "context" in result
        assert len(result["sources"]) == 1
        assert result["sources"][0]["slug"] == "dataset-a"
        assert result["context"]["user"] == "testuser"

    @patch("sunstone.context.detect_execution_context")
    def test_flush_clears_reads(self, mock_ctx):
        """flush_to_output() should clear the accumulated reads."""
        from sunstone.context import ExecutionContext

        mock_ctx.return_value = ExecutionContext(user="testuser", execution_timestamp="now")
        session = LineageSession()
        session.record_read(DatasetRead(slug="dataset-a"))
        session.flush_to_output()
        assert len(session._reads) == 0

    @patch("sunstone.context.detect_execution_context")
    def test_flush_with_transformation_params(self, mock_ctx):
        """flush_to_output() should include transformation_params when provided."""
        from sunstone.context import ExecutionContext

        mock_ctx.return_value = ExecutionContext(user="testuser", execution_timestamp="now")
        session = LineageSession()
        session.record_read(DatasetRead(slug="dataset-a"))
        result = session.flush_to_output(transformation_params={"filter": "country == 'US'"})
        assert result["transformation_params"] == {"filter": "country == 'US'"}

    @patch("sunstone.context.detect_execution_context")
    def test_flush_lazy_initializes_context(self, mock_ctx):
        """flush_to_output() should call detect_execution_context only on first flush."""
        from sunstone.context import ExecutionContext

        mock_ctx.return_value = ExecutionContext(user="testuser", execution_timestamp="now")
        session = LineageSession()
        session.record_read(DatasetRead(slug="a"))
        session.flush_to_output()
        session.record_read(DatasetRead(slug="b"))
        session.flush_to_output()
        # Should only call detect once (lazy init on first flush)
        assert mock_ctx.call_count == 1


class TestSessionSingleton:
    """Tests for get_session/close_session thread-local singleton."""

    def teardown_method(self):
        """Clean up session after each test."""
        close_session()

    def test_get_session_returns_same_object(self):
        """get_session() should return the same object on repeated calls."""
        s1 = get_session()
        s2 = get_session()
        assert s1 is s2

    def test_close_session_clears_singleton(self):
        """close_session() should clear so next get_session() returns new object."""
        s1 = get_session()
        close_session()
        s2 = get_session()
        assert s1 is not s2

    def test_close_session_idempotent(self):
        """close_session() should be safe to call when no session exists."""
        close_session()
        close_session()  # Should not raise
