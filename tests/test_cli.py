"""
Tests for Sunstone CLI.
"""

import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sunstone.cli import expand_env_vars, main


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project with datasets.yaml."""
    # Copy the test project
    src = Path(__file__).parent / "testdata" / "UNMembersProject"
    dst = tmp_path / "project"
    shutil.copytree(src, dst)
    return dst


class TestEnvVarExpansion:
    """Tests for environment variable expansion."""

    def test_simple_var(self) -> None:
        """Test simple ${VAR} expansion."""
        with patch.dict(os.environ, {"MY_VAR": "hello"}):
            assert expand_env_vars("${MY_VAR}") == "hello"
            assert expand_env_vars("prefix-${MY_VAR}-suffix") == "prefix-hello-suffix"

    def test_var_with_default(self) -> None:
        """Test ${VAR:-default} expansion."""
        # With env var set
        with patch.dict(os.environ, {"MY_VAR": "hello"}, clear=False):
            assert expand_env_vars("${MY_VAR:-world}") == "hello"

        # Without env var set (use default)
        env = os.environ.copy()
        env.pop("UNSET_VAR", None)
        with patch.dict(os.environ, env, clear=True):
            assert expand_env_vars("${UNSET_VAR:-world}") == "world"

    def test_empty_default(self) -> None:
        """Test ${VAR:-} with empty default."""
        env = os.environ.copy()
        env.pop("UNSET_VAR", None)
        with patch.dict(os.environ, env, clear=True):
            assert expand_env_vars("${UNSET_VAR:-}") == ""

    def test_no_substitution_without_match(self) -> None:
        """Test that non-matching text is unchanged."""
        assert expand_env_vars("hello world") == "hello world"
        assert expand_env_vars("$VAR") == "$VAR"  # Only ${VAR} syntax

    def test_unset_var_no_default_unchanged(self) -> None:
        """Test that unset vars without defaults are unchanged."""
        env = os.environ.copy()
        env.pop("TRULY_UNSET", None)
        with patch.dict(os.environ, env, clear=True):
            assert expand_env_vars("${TRULY_UNSET}") == "${TRULY_UNSET}"

    def test_multiple_vars(self) -> None:
        """Test multiple variable substitutions."""
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            assert expand_env_vars("${A}-${B}") == "1-2"


class TestDatasetValidateCommand:
    """Tests for the dataset validate command."""

    def test_validate_valid_file(self, runner: CliRunner, project_path: Path) -> None:
        """Test validating a valid datasets.yaml."""
        result = runner.invoke(main, ["dataset", "validate", "-f", str(project_path / "datasets.yaml")])
        assert result.exit_code == 0
        assert "is valid" in result.output

    def test_validate_specific_dataset(self, runner: CliRunner, project_path: Path) -> None:
        """Test validating a specific dataset."""
        result = runner.invoke(
            main, ["dataset", "validate", "-f", str(project_path / "datasets.yaml"), "official-un-member-states"]
        )
        assert result.exit_code == 0
        assert "1 dataset(s) valid" in result.output

    def test_validate_missing_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validating a non-existent file."""
        result = runner.invoke(main, ["dataset", "validate", "-f", str(tmp_path / "missing.yaml")])
        assert result.exit_code != 0

    def test_validate_invalid_yaml(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validating invalid YAML structure."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("not: valid: yaml: {{}")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_validate_missing_required_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation catches missing required fields."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    # missing slug, location, fields
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "missing required field" in result.output

    def test_validate_invalid_field_type(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation catches invalid field types."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    location: data.csv
    fields:
      - name: col1
        type: invalid_type
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "invalid type" in result.output

    def test_validate_duplicate_slugs(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation catches duplicate slugs."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Dataset 1
    slug: same-slug
    location: data1.csv
    fields:
      - name: col1
        type: string
  - name: Dataset 2
    slug: same-slug
    location: data2.csv
    fields:
      - name: col1
        type: string
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "duplicate slug" in result.output

    def test_validate_nonexistent_dataset(self, runner: CliRunner, project_path: Path) -> None:
        """Test validating a non-existent dataset slug."""
        result = runner.invoke(main, ["dataset", "validate", "-f", str(project_path / "datasets.yaml"), "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestDatasetListCommand:
    """Tests for the dataset list command."""

    def test_list_datasets(self, runner: CliRunner, project_path: Path) -> None:
        """Test listing datasets."""
        result = runner.invoke(main, ["dataset", "list", "-f", str(project_path / "datasets.yaml")])
        assert result.exit_code == 0
        assert "Inputs:" in result.output
        assert "official-un-member-states" in result.output
        assert "Outputs:" in result.output
        assert "current-un-member-states" in result.output
        assert "[publish]" in result.output

    def test_list_empty_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test listing empty datasets.yaml."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("inputs: []\noutputs: []")
        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_file)])
        assert result.exit_code == 0
        assert "No datasets found" in result.output


class TestDatasetLockUnlockCommands:
    """Tests for dataset lock and unlock commands."""

    def test_lock_single_dataset(self, runner: CliRunner, temp_project: Path) -> None:
        """Test locking a single dataset."""
        result = runner.invoke(
            main, ["dataset", "lock", "-f", str(temp_project / "datasets.yaml"), "current-un-member-states"]
        )
        assert result.exit_code == 0
        assert "Locked 1 dataset(s)" in result.output

        # Verify the file was updated
        content = (temp_project / "datasets.yaml").read_text()
        assert "strict: true" in content

    def test_lock_all_datasets(self, runner: CliRunner, temp_project: Path) -> None:
        """Test locking all datasets."""
        result = runner.invoke(main, ["dataset", "lock", "-f", str(temp_project / "datasets.yaml")])
        assert result.exit_code == 0
        assert "Locked 2 dataset(s)" in result.output

    def test_unlock_dataset(self, runner: CliRunner, temp_project: Path) -> None:
        """Test unlocking a dataset."""
        # First lock it
        runner.invoke(main, ["dataset", "lock", "-f", str(temp_project / "datasets.yaml"), "current-un-member-states"])

        # Then unlock
        result = runner.invoke(
            main, ["dataset", "unlock", "-f", str(temp_project / "datasets.yaml"), "current-un-member-states"]
        )
        assert result.exit_code == 0
        assert "Unlocked 1 dataset(s)" in result.output

    def test_lock_nonexistent_dataset(self, runner: CliRunner, temp_project: Path) -> None:
        """Test locking a non-existent dataset."""
        result = runner.invoke(main, ["dataset", "lock", "-f", str(temp_project / "datasets.yaml"), "nonexistent"])
        assert "not found" in result.output


class TestPackageBuildCommand:
    """Tests for the package build command."""

    def test_build_package(self, runner: CliRunner, temp_project: Path) -> None:
        """Test building a datapackage.json."""
        # Create the output file
        output_dir = temp_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        result = runner.invoke(
            main,
            [
                "package",
                "build",
                "-f",
                str(temp_project / "datasets.yaml"),
                "-o",
                str(temp_project / "datapackage.json"),
            ],
        )
        assert result.exit_code == 0
        assert "Created" in result.output
        assert (temp_project / "datapackage.json").exists()

    def test_build_no_outputs(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test building with no output datasets."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("inputs: []\noutputs: []")
        result = runner.invoke(main, ["package", "build", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "No output datasets found" in result.output


class TestPackagePushCommand:
    """Tests for the package push command."""

    def test_push_non_publishable(self, runner: CliRunner, temp_project: Path) -> None:
        """Test pushing without publishable datasets."""
        # Modify datasets.yaml to remove publish flag
        yaml_path = temp_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace("publish: true", "publish: false")
        yaml_path.write_text(content)

        result = runner.invoke(main, ["package", "push", "-f", str(yaml_path)])
        assert result.exit_code != 0
        assert "No publishable datasets found" in result.output

    def test_push_success(self, runner: CliRunner, temp_project: Path) -> None:
        """Test successful push."""
        # Create the output file
        output_dir = temp_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        # Mock GCS client
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(temp_project / "datasets.yaml")])
            assert result.exit_code == 0
            assert "Uploaded datapackage.json" in result.output

    def test_push_with_custom_destination(self, runner: CliRunner, temp_project: Path) -> None:
        """Test push with custom destination."""
        # Create the output file
        output_dir = temp_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        # Mock GCS client
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(
                main, ["package", "push", "-f", str(temp_project / "datasets.yaml"), "-d", "gs://my-bucket/custom/"]
            )
            assert result.exit_code == 0
            mock_client.bucket.assert_called_with("my-bucket")

    def test_push_invalid_destination_scheme(self, runner: CliRunner, temp_project: Path) -> None:
        """Test push with non-gs:// destination fails."""
        # Create the output file
        output_dir = temp_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        result = runner.invoke(
            main, ["package", "push", "-f", str(temp_project / "datasets.yaml"), "-d", "https://example.com/"]
        )
        assert result.exit_code != 0
        assert "gs://" in result.output


class TestPublishConfigParsing:
    """Tests for publish config parsing (boolean vs object format)."""

    def test_publish_boolean_true(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that publish: true is parsed correctly."""
        result = runner.invoke(main, ["dataset", "list", "-f", str(temp_project / "datasets.yaml")])
        assert result.exit_code == 0
        assert "[publish]" in result.output

    def test_publish_boolean_false(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that publish: false is parsed correctly."""
        yaml_path = temp_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace("publish: true", "publish: false")
        yaml_path.write_text(content)

        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_path)])
        assert result.exit_code == 0
        assert "[publish]" not in result.output

    def test_publish_object_enabled(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that publish: {enabled: true} is parsed correctly."""
        yaml_path = temp_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace("publish: true", "publish:\n      enabled: true")
        yaml_path.write_text(content)

        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_path)])
        assert result.exit_code == 0
        assert "[publish]" in result.output

    def test_publish_object_disabled(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that publish: {enabled: false} is parsed correctly."""
        yaml_path = temp_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace("publish: true", "publish:\n      enabled: false")
        yaml_path.write_text(content)

        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_path)])
        assert result.exit_code == 0
        assert "[publish]" not in result.output


class TestCLIHelp:
    """Tests for CLI help output."""

    def test_main_help(self, runner: CliRunner) -> None:
        """Test main help shows subcommands."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "dataset" in result.output
        assert "package" in result.output

    def test_dataset_help(self, runner: CliRunner) -> None:
        """Test dataset subcommand help."""
        result = runner.invoke(main, ["dataset", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "validate" in result.output
        assert "lock" in result.output
        assert "unlock" in result.output

    def test_package_help(self, runner: CliRunner) -> None:
        """Test package subcommand help."""
        result = runner.invoke(main, ["package", "--help"])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "push" in result.output
