"""
Pytest configuration and fixtures for Sunstone library tests.
"""
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_path() -> Path:
    """Path to project for testing."""
    return Path(__file__).parent / "testdata/UNMembersProject"


@pytest.fixture(scope="session")
def datasets_yaml_path(project_path: Path) -> Path:
    """Path to datasets.yaml file."""
    return project_path / "datasets.yaml"
