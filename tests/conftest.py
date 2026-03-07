"""
Pytest configuration and fixtures for Sunstone library tests.
"""

import shutil
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


@pytest.fixture
def project_copy(project_path: Path, tmp_path: Path) -> Path:
    """Lightweight copy of the test project, excluding .venv and caches."""
    dst = tmp_path / "project"
    shutil.copytree(project_path, dst, ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
    return dst
