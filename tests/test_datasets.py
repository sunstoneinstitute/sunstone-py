"""
Tests for Sunstone DatasetsManager functionality.
"""
from pathlib import Path

import pytest

import sunstone


class TestDatasetsManager:
    """Tests for DatasetsManager class."""

    def test_load_datasets_manager(self, project_path: Path):
        """Test loading datasets manager from project path."""
        manager = sunstone.DatasetsManager(project_path)
        assert manager is not None

    def test_find_dataset_by_slug(self, project_path: Path):
        """Test finding a dataset by its slug."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        assert dataset is not None
        assert dataset.name == "Official UN Member States"
        assert dataset.slug == "official-un-member-states"
        assert dataset.location is not None
        assert len(dataset.fields) > 0
        if dataset.source:
            assert dataset.source.license is not None

    def test_find_nonexistent_dataset(self, project_path: Path):
        """Test that finding a non-existent dataset returns None."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("does-not-exist")
        assert dataset is None
