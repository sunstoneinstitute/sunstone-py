"""
Tests for Sunstone CLI.
"""

import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sunstone.cli import _contributor_to_dict, _package_metadata_to_dict, expand_env_vars, is_lfs_pointer, main
from sunstone.lineage import Contributor, PackageMetadata


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def test_project(tmp_path: Path) -> Path:
    """Create a temporary project with datasets.yaml."""
    src = Path(__file__).parent / "testdata" / "UNMembersProject"
    dst = tmp_path / "project"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
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
    # missing slug, location
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "missing required field" in result.output

    def test_validate_table_without_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation requires fields when type is explicitly 'table'."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    type: table
    location: data.csv
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "required for table resources" in result.output

    def test_validate_no_type_without_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation passes when type is not set and fields are omitted."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    location: data.csv
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

    def test_validate_non_table_without_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation allows non-table resources without fields."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Image
    slug: test-image
    type: file
    location: image.png
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

    def test_validate_table_with_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation passes for table resources with fields."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    type: table
    location: data.csv
    fields:
      - name: col1
        type: string
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

    def test_validate_no_type_with_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation passes when type is not set but fields are present."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    location: data.csv
    fields:
      - name: col1
        type: string
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

    def test_validate_non_table_with_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation passes for non-table resources with fields."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Geojson
    slug: test-geojson
    type: geojson
    location: data.geojson
    fields:
      - name: geometry
        type: string
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

    def test_validate_table_with_empty_fields(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation passes for table resources with empty fields list."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    type: table
    location: data.csv
    fields: []
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

    def test_validate_array_and_object_field_types(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test validation accepts array and object field types."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("""
inputs:
  - name: Test Dataset
    slug: test-dataset
    location: data.json
    fields:
      - name: items
        type: array
      - name: metadata
        type: object
""")
        result = runner.invoke(main, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0

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
        assert "Publishing:" in result.output
        assert "to: gs://example-bucket/datasets/un-members/" in result.output
        assert "Inputs:" in result.output
        assert "official-un-member-states" in result.output
        assert "Outputs:" in result.output
        assert "current-un-member-states" in result.output

    def test_list_empty_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test listing empty datasets.yaml."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("inputs: []\noutputs: []")
        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_file)])
        assert result.exit_code == 0
        assert "No datasets found" in result.output


class TestDatasetLockUnlockCommands:
    """Tests for dataset lock and unlock commands."""

    def test_lock_single_dataset(self, runner: CliRunner, test_project: Path) -> None:
        """Test locking a single dataset."""
        result = runner.invoke(
            main, ["dataset", "lock", "-f", str(test_project / "datasets.yaml"), "current-un-member-states"]
        )
        assert result.exit_code == 0
        assert "Locked 1 dataset(s)" in result.output

        # Verify the file was updated
        content = (test_project / "datasets.yaml").read_text()
        assert "strict: true" in content

    def test_lock_all_datasets(self, runner: CliRunner, test_project: Path) -> None:
        """Test locking all datasets."""
        result = runner.invoke(main, ["dataset", "lock", "-f", str(test_project / "datasets.yaml")])
        assert result.exit_code == 0
        assert "Locked 3 dataset(s)" in result.output

    def test_unlock_dataset(self, runner: CliRunner, test_project: Path) -> None:
        """Test unlocking a dataset."""
        # First lock it
        runner.invoke(main, ["dataset", "lock", "-f", str(test_project / "datasets.yaml"), "current-un-member-states"])

        # Then unlock
        result = runner.invoke(
            main, ["dataset", "unlock", "-f", str(test_project / "datasets.yaml"), "current-un-member-states"]
        )
        assert result.exit_code == 0
        assert "Unlocked 1 dataset(s)" in result.output

    def test_lock_nonexistent_dataset(self, runner: CliRunner, test_project: Path) -> None:
        """Test locking a non-existent dataset."""
        result = runner.invoke(main, ["dataset", "lock", "-f", str(test_project / "datasets.yaml"), "nonexistent"])
        assert "not found" in result.output


class TestPackageBuildCommand:
    """Tests for the package build command."""

    def test_build_package(self, runner: CliRunner, test_project: Path) -> None:
        """Test building a datapackage.json."""
        # Create the output file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        result = runner.invoke(
            main,
            [
                "package",
                "build",
                "-f",
                str(test_project / "datasets.yaml"),
                "-o",
                str(test_project / "datapackage.json"),
            ],
        )
        assert result.exit_code == 0
        assert "Created" in result.output
        assert (test_project / "datapackage.json").exists()

    def test_build_no_outputs(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test building with no output datasets."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text("inputs: []\noutputs: []")
        result = runner.invoke(main, ["package", "build", "-f", str(yaml_file)])
        assert result.exit_code != 0
        assert "No publishable datasets found" in result.output

    def test_build_with_as_url(self, runner: CliRunner, test_project: Path) -> None:
        """Test that as_url produces full public URLs in resource paths."""
        # Create the output file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        # Add as: to publish config
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "to: gs://example-bucket/datasets/un-members/",
            "to: gs://example-bucket/datasets/un-members/\n  as: https://data.example.com/un-members/",
        )
        yaml_path.write_text(content)

        result = runner.invoke(
            main,
            [
                "package",
                "build",
                "-f",
                str(yaml_path),
                "-o",
                str(test_project / "datapackage.json"),
            ],
        )
        assert result.exit_code == 0

        import json

        datapackage = json.loads((test_project / "datapackage.json").read_text())
        assert len(datapackage["resources"]) == 1
        resource_path = datapackage["resources"][0]["path"]
        assert resource_path == "https://data.example.com/un-members/outputs/current_un_member_states.csv"

    def test_build_expands_top_level_methodology(self, runner: CliRunner, test_project: Path) -> None:
        """Test that top-level si:methodology is expanded in datapackage.json."""
        # Create the output file and methodology file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        report_dir = test_project / "report"
        report_dir.mkdir(exist_ok=True)
        (report_dir / "DATA_METHODOLOGY.md").write_text("# Methodology\n")

        # Add defaults with rdfPrefixes and top-level si:methodology
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = (
            'defaults:\n  rdfPrefixes:\n    si: "https://sunstone.institute/rdf/vocab#"\n\n'
            "si:methodology: report/DATA_METHODOLOGY.md\n\n" + content
        )
        yaml_path.write_text(content)

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_path), "-o", str(test_project / "datapackage.json")],
        )
        assert result.exit_code == 0

        import json

        datapackage = json.loads((test_project / "datapackage.json").read_text())
        methodology_key = "https://sunstone.institute/rdf/vocab#methodology"
        assert methodology_key in datapackage
        assert datapackage[methodology_key] == "report/DATA_METHODOLOGY.md"

    def test_build_expands_top_level_methodology_with_as_url(self, runner: CliRunner, test_project: Path) -> None:
        """Test that top-level si:methodology becomes full URL when publish.as is set."""
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        report_dir = test_project / "report"
        report_dir.mkdir(exist_ok=True)
        (report_dir / "DATA_METHODOLOGY.md").write_text("# Methodology\n")

        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "to: gs://example-bucket/datasets/un-members/",
            "to: gs://example-bucket/datasets/un-members/\n  as: https://data.example.com/un-members/",
        )
        content = (
            'defaults:\n  rdfPrefixes:\n    si: "https://sunstone.institute/rdf/vocab#"\n\n'
            "si:methodology: report/DATA_METHODOLOGY.md\n\n" + content
        )
        yaml_path.write_text(content)

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_path), "-o", str(test_project / "datapackage.json")],
        )
        assert result.exit_code == 0

        import json

        datapackage = json.loads((test_project / "datapackage.json").read_text())
        methodology_key = "https://sunstone.institute/rdf/vocab#methodology"
        assert methodology_key in datapackage
        assert datapackage[methodology_key] == "https://data.example.com/un-members/report/DATA_METHODOLOGY.md"


class TestPackagePushCommand:
    """Tests for the package push command."""

    def test_push_non_publishable(self, runner: CliRunner, test_project: Path) -> None:
        """Test pushing without publishing enabled."""
        # Modify datasets.yaml to disable publishing at top level
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace("enabled: true", "enabled: false")
        yaml_path.write_text(content)

        result = runner.invoke(main, ["package", "push", "-f", str(yaml_path)])
        assert result.exit_code != 0
        assert "No publishable datasets found" in result.output

    def test_push_success(self, runner: CliRunner, test_project: Path) -> None:
        """Test successful push."""
        # Create the output file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        # Mock GCS client
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(test_project / "datasets.yaml")])
            assert result.exit_code == 0
            assert "datapackage.json" in result.output
            assert "Package pushed to" in result.output

    def test_push_with_custom_destination(self, runner: CliRunner, test_project: Path) -> None:
        """Test push with custom destination."""
        # Create the output file
        output_dir = test_project / "outputs"
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
                main, ["package", "push", "-f", str(test_project / "datasets.yaml"), "-d", "gs://my-bucket/custom/"]
            )
            assert result.exit_code == 0
            mock_client.bucket.assert_called_with("my-bucket")

    def test_push_invalid_destination_scheme(self, runner: CliRunner, test_project: Path) -> None:
        """Test push with non-gs:// destination fails."""
        # Create the output file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        result = runner.invoke(
            main, ["package", "push", "-f", str(test_project / "datasets.yaml"), "-d", "https://example.com/"]
        )
        assert result.exit_code != 0
        assert "gs://" in result.output

    def test_push_with_as_url(self, runner: CliRunner, test_project: Path) -> None:
        """Test that as_url produces public URLs in datapackage.json while uploads go to GCS."""
        import json

        # Create the output file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        # Add as: to publish config
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "to: gs://example-bucket/datasets/un-members/",
            "to: gs://example-bucket/datasets/un-members/\n  as: https://data.example.com/un-members/",
        )
        yaml_path.write_text(content)

        # Mock GCS client and capture uploaded datapackage content
        uploaded_content = {}
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        def capture_upload(content: str, content_type: str | None = None) -> None:
            uploaded_content["datapackage"] = content

        mock_blob.upload_from_string.side_effect = capture_upload

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(yaml_path)])
            assert result.exit_code == 0

            # Verify datapackage.json has public URLs
            datapackage = json.loads(uploaded_content["datapackage"])
            resource_path = datapackage["resources"][0]["path"]
            assert resource_path == "https://data.example.com/un-members/outputs/current_un_member_states.csv"

            # Verify uploads went to GCS
            mock_client.bucket.assert_called_with("example-bucket")

    def test_push_uploads_methodology_file(self, runner: CliRunner, test_project: Path) -> None:
        """Test that push uploads the methodology file referenced by si:methodology."""
        import json

        # Create the output file and methodology file
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        report_dir = test_project / "report"
        report_dir.mkdir(exist_ok=True)
        (report_dir / "DATA_METHODOLOGY.md").write_text("# Methodology\n")

        # Add defaults with rdfPrefixes and top-level si:methodology
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = (
            'defaults:\n  rdfPrefixes:\n    si: "https://sunstone.institute/rdf/vocab#"\n\n'
            "si:methodology: report/DATA_METHODOLOGY.md\n\n" + content
        )
        yaml_path.write_text(content)

        # Mock GCS client and track blob paths
        uploaded_blobs: list[str] = []
        uploaded_content: dict[str, str] = {}
        mock_client = MagicMock()
        mock_bucket = MagicMock()

        def make_blob(path: str) -> MagicMock:
            blob = MagicMock()
            blob.name = path

            def capture_string(content: str, content_type: str | None = None) -> None:
                uploaded_blobs.append(path)
                uploaded_content[path] = content

            def capture_file(filename: str) -> None:
                uploaded_blobs.append(path)

            blob.upload_from_string.side_effect = capture_string
            blob.upload_from_filename.side_effect = capture_file
            return blob

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.side_effect = make_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(yaml_path)])
            assert result.exit_code == 0

            # Verify methodology file was uploaded
            assert any(
                "DATA_METHODOLOGY.md" in b for b in uploaded_blobs
            ), f"Methodology file not uploaded. Uploaded blobs: {uploaded_blobs}"

            # Verify datapackage.json contains expanded methodology key
            dp_path = [b for b in uploaded_blobs if "datapackage.json" in b][0]
            datapackage = json.loads(uploaded_content[dp_path])
            methodology_key = "https://sunstone.institute/rdf/vocab#methodology"
            assert methodology_key in datapackage

    def test_push_expands_methodology_with_as_url(self, runner: CliRunner, test_project: Path) -> None:
        """Test that push expands si:methodology to full URL when publish.as is set."""
        import json

        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        report_dir = test_project / "report"
        report_dir.mkdir(exist_ok=True)
        (report_dir / "DATA_METHODOLOGY.md").write_text("# Methodology\n")

        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "to: gs://example-bucket/datasets/un-members/",
            "to: gs://example-bucket/datasets/un-members/\n  as: https://data.example.com/un-members/",
        )
        content = (
            'defaults:\n  rdfPrefixes:\n    si: "https://sunstone.institute/rdf/vocab#"\n\n'
            "si:methodology: report/DATA_METHODOLOGY.md\n\n" + content
        )
        yaml_path.write_text(content)

        uploaded_content: dict[str, str] = {}
        mock_client = MagicMock()
        mock_bucket = MagicMock()

        def make_blob(path: str) -> MagicMock:
            blob = MagicMock()

            def capture_string(content: str, content_type: str | None = None) -> None:
                uploaded_content[path] = content

            blob.upload_from_string.side_effect = capture_string
            return blob

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.side_effect = make_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(yaml_path)])
            assert result.exit_code == 0

            dp_path = [k for k in uploaded_content if "datapackage.json" in k][0]
            datapackage = json.loads(uploaded_content[dp_path])
            methodology_key = "https://sunstone.institute/rdf/vocab#methodology"
            assert methodology_key in datapackage
            assert datapackage[methodology_key] == "https://data.example.com/un-members/report/DATA_METHODOLOGY.md"

    def test_push_flattens_methodology_path(self, runner: CliRunner, test_project: Path) -> None:
        """Test that push flattens methodology file path when publish.flatten is true."""
        import json

        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        report_dir = test_project / "report"
        report_dir.mkdir(exist_ok=True)
        (report_dir / "DATA_METHODOLOGY.md").write_text("# Methodology\n")

        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "to: gs://example-bucket/datasets/un-members/",
            "to: gs://example-bucket/datasets/un-members/\n  as: https://data.example.com/un-members/\n  flatten: true",
        )
        content = (
            'defaults:\n  rdfPrefixes:\n    si: "https://sunstone.institute/rdf/vocab#"\n\n'
            "si:methodology: report/DATA_METHODOLOGY.md\n\n" + content
        )
        yaml_path.write_text(content)

        uploaded_blobs: list[str] = []
        uploaded_content: dict[str, str] = {}
        mock_client = MagicMock()
        mock_bucket = MagicMock()

        def make_blob(path: str) -> MagicMock:
            blob = MagicMock()

            def capture_string(content: str, content_type: str | None = None) -> None:
                uploaded_blobs.append(path)
                uploaded_content[path] = content

            def capture_file(filename: str) -> None:
                uploaded_blobs.append(path)

            blob.upload_from_string.side_effect = capture_string
            blob.upload_from_filename.side_effect = capture_file
            return blob

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.side_effect = make_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(yaml_path)])
            assert result.exit_code == 0, result.output

            # Methodology file should be uploaded with flattened path (just filename)
            methodology_blobs = [b for b in uploaded_blobs if "DATA_METHODOLOGY.md" in b]
            assert len(methodology_blobs) == 1
            # Should be "datasets/un-members/DATA_METHODOLOGY.md", not "datasets/un-members/report/DATA_METHODOLOGY.md"
            assert methodology_blobs[0] == "datasets/un-members/DATA_METHODOLOGY.md"

            # datapackage.json should have flattened methodology URL
            dp_path = [k for k in uploaded_content if "datapackage.json" in k][0]
            datapackage = json.loads(uploaded_content[dp_path])
            methodology_key = "https://sunstone.institute/rdf/vocab#methodology"
            assert methodology_key in datapackage
            assert datapackage[methodology_key] == "https://data.example.com/un-members/DATA_METHODOLOGY.md"


class TestIsLfsPointer:
    """Tests for Git LFS pointer file detection."""

    def test_lfs_pointer_detected(self, tmp_path: Path) -> None:
        """Test that an LFS pointer file is correctly identified."""
        pointer = tmp_path / "data.csv"
        pointer.write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\n"
            "size 12345\n"
        )
        assert is_lfs_pointer(pointer) is True

    def test_real_file_not_detected(self, tmp_path: Path) -> None:
        """Test that a normal CSV file is not flagged as LFS pointer."""
        real_file = tmp_path / "data.csv"
        real_file.write_text("Country,Code\nTest,TST\n")
        assert is_lfs_pointer(real_file) is False

    def test_large_file_not_detected(self, tmp_path: Path) -> None:
        """Test that a file larger than 1024 bytes is skipped (fast path)."""
        large_file = tmp_path / "data.csv"
        large_file.write_text("x" * 2000)
        assert is_lfs_pointer(large_file) is False

    def test_binary_file_not_detected(self, tmp_path: Path) -> None:
        """Test that a binary file does not raise an error."""
        binary_file = tmp_path / "data.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03")
        assert is_lfs_pointer(binary_file) is False

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that a missing file returns False."""
        assert is_lfs_pointer(tmp_path / "missing.csv") is False

    def test_push_blocked_by_lfs_pointer(self, runner: CliRunner, test_project: Path) -> None:
        """Test that push fails when data files are LFS pointers."""
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\n"
            "size 12345\n"
        )

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(test_project / "datasets.yaml")])
            assert result.exit_code != 0
            assert "Git LFS pointers" in result.output
            assert "git lfs pull" in result.output
            # Verify no uploads happened
            mock_blob.upload_from_string.assert_not_called()
            mock_blob.upload_from_filename.assert_not_called()


class TestPublishConfigParsing:
    """Tests for top-level publish config parsing."""

    def test_publish_enabled(self, runner: CliRunner, test_project: Path) -> None:
        """Test that top-level publish config is displayed."""
        result = runner.invoke(main, ["dataset", "list", "-f", str(test_project / "datasets.yaml")])
        assert result.exit_code == 0
        assert "Publishing:" in result.output
        assert "to: gs://example-bucket/datasets/un-members/" in result.output

    def test_publish_disabled(self, runner: CliRunner, test_project: Path) -> None:
        """Test that disabled publishing is not displayed."""
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace("enabled: true", "enabled: false")
        yaml_path.write_text(content)

        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_path)])
        assert result.exit_code == 0
        assert "Publishing:" not in result.output

    def test_publish_with_flatten(self, runner: CliRunner, test_project: Path) -> None:
        """Test that flatten option is displayed."""
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        # Add flatten: true to publish config
        content = content.replace(
            "to: gs://example-bucket/datasets/un-members/",
            "to: gs://example-bucket/datasets/un-members/\n  flatten: true",
        )
        yaml_path.write_text(content)

        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_path)])
        assert result.exit_code == 0
        assert "Publishing:" in result.output
        assert "flatten: true" in result.output

    def test_publish_boolean_legacy(self, runner: CliRunner, test_project: Path) -> None:
        """Test that legacy boolean format still works."""
        yaml_path = test_project / "datasets.yaml"
        content = yaml_path.read_text()
        # Replace object format with boolean
        content = content.replace(
            "publish:\n  enabled: true\n  to: gs://example-bucket/datasets/un-members/", "publish: true"
        )
        yaml_path.write_text(content)

        result = runner.invoke(main, ["dataset", "list", "-f", str(yaml_path)])
        assert result.exit_code == 0
        assert "[publish]" not in result.output


class TestPerDatasetPublish:
    """Tests for per-dataset publish configuration."""

    def test_per_dataset_publish_excludes_disabled(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that publish.enabled: false excludes a dataset from the package."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/default/\n"
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
            "    publish:\n"
            "      enabled: false\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "included.csv").write_text("col\nval")
        (tmp_path / "excluded.csv").write_text("col\nval")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "datapackage.json")],
        )
        assert result.exit_code == 0

        import json

        dp = json.loads((tmp_path / "datapackage.json").read_text())
        slugs = [r["name"] for r in dp["resources"]]
        assert "included" in slugs
        assert "excluded" not in slugs

    def test_per_dataset_publish_override_destination(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that per-dataset publish.to overrides the top-level destination."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/default/\n"
            "outputs:\n"
            "  - name: Default Dest\n"
            "    slug: default-dest\n"
            "    location: default.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Custom Dest\n"
            "    slug: custom-dest\n"
            "    location: custom.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/custom/\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "default.csv").write_text("col\nval")
        (tmp_path / "custom.csv").write_text("col\nval")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "datapackage.json")],
        )
        assert result.exit_code == 0
        # Two destinations means two files
        assert (tmp_path / "datapackage.json").exists()
        assert (tmp_path / "datapackage.1.json").exists()

        import json

        dp0 = json.loads((tmp_path / "datapackage.json").read_text())
        dp1 = json.loads((tmp_path / "datapackage.1.json").read_text())

        slugs0 = [r["name"] for r in dp0["resources"]]
        slugs1 = [r["name"] for r in dp1["resources"]]
        assert "default-dest" in slugs0
        assert "custom-dest" in slugs1

    def test_input_with_publish_included(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that input datasets with publish config are included in the package."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/default/\n"
            "inputs:\n"
            "  - name: Published Input\n"
            "    slug: published-input\n"
            "    location: input.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/default/\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Unpublished Input\n"
            "    slug: unpublished-input\n"
            "    location: unpublished.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "outputs:\n"
            "  - name: Output\n"
            "    slug: output\n"
            "    location: output.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "input.csv").write_text("col\nval")
        (tmp_path / "unpublished.csv").write_text("col\nval")
        (tmp_path / "output.csv").write_text("col\nval")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "datapackage.json")],
        )
        assert result.exit_code == 0

        import json

        dp = json.loads((tmp_path / "datapackage.json").read_text())
        slugs = [r["name"] for r in dp["resources"]]
        assert "published-input" in slugs
        assert "output" in slugs
        assert "unpublished-input" not in slugs

    def test_input_without_publish_excluded(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that input datasets without publish config are excluded even with top-level publish."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/default/\n"
            "inputs:\n"
            "  - name: Plain Input\n"
            "    slug: plain-input\n"
            "    location: input.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "outputs: []\n"
        )
        (tmp_path / "input.csv").write_text("col\nval")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "datapackage.json")],
        )
        # No publishable datasets (input has no publish, no outputs)
        assert result.exit_code != 0
        assert "No publishable datasets found" in result.output

    def test_no_top_level_publish_with_per_dataset(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that per-dataset publish works without top-level publish config."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Dataset A\n"
            "    slug: dataset-a\n"
            "    location: a.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/a/\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Dataset B\n"
            "    slug: dataset-b\n"
            "    location: b.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/b/\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "datapackage.json")],
        )
        assert result.exit_code == 0

        import json

        dp0 = json.loads((tmp_path / "datapackage.json").read_text())
        dp1 = json.loads((tmp_path / "datapackage.1.json").read_text())

        slugs0 = [r["name"] for r in dp0["resources"]]
        slugs1 = [r["name"] for r in dp1["resources"]]
        # One dataset per file
        assert len(slugs0) == 1
        assert len(slugs1) == 1
        assert set(slugs0 + slugs1) == {"dataset-a", "dataset-b"}

    def test_push_per_dataset_destinations(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that push sends to multiple destinations."""
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Dataset A\n"
            "    slug: dataset-a\n"
            "    location: a.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/a/datapackage.json\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Dataset B\n"
            "    slug: dataset-b\n"
            "    location: b.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/b/datapackage.json\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(yaml_file)])
            assert result.exit_code == 0
            assert "Pushed to 2 destination(s)" in result.output

            # Verify both datapackage.json paths were uploaded
            blob_calls = [call[0][0] for call in mock_bucket.blob.call_args_list]
            assert "a/datapackage.json" in blob_calls
            assert "b/datapackage.json" in blob_calls

    def test_publish_not_in_custom_properties(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that per-dataset publish config doesn't leak into custom_properties."""
        from sunstone.datasets import DatasetsManager

        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/test/\n"
        )

        manager = DatasetsManager(tmp_path)
        outputs = manager.get_all_outputs()
        assert len(outputs) == 1
        ds = outputs[0]
        assert ds.publish is not None
        assert ds.publish.enabled is True
        assert ds.custom_properties is None or "publish" not in ds.custom_properties


class TestContributorToDict:
    """Tests for _contributor_to_dict helper."""

    def test_title_only(self) -> None:
        """Test contributor with only title set."""
        c = Contributor(title="Alice")
        assert _contributor_to_dict(c) == {"title": "Alice"}

    def test_all_fields(self) -> None:
        """Test contributor with all fields set."""
        c = Contributor(title="Alice", roles=["creator"], path="https://example.com", email="alice@example.com")
        result = _contributor_to_dict(c)
        assert result == {
            "title": "Alice",
            "roles": ["creator"],
            "path": "https://example.com",
            "email": "alice@example.com",
        }

    def test_omits_none_fields(self) -> None:
        """Test that None fields are omitted from the dict."""
        c = Contributor(title="Bob", roles=["publisher"])
        result = _contributor_to_dict(c)
        assert "path" not in result
        assert "email" not in result
        assert result == {"title": "Bob", "roles": ["publisher"]}


class TestPackageMetadataToDict:
    """Tests for _package_metadata_to_dict helper."""

    def test_empty_metadata(self) -> None:
        """Test that all-None metadata produces empty dict."""
        m = PackageMetadata()
        assert _package_metadata_to_dict(m) == {}

    def test_all_scalar_fields(self) -> None:
        """Test metadata with all scalar fields set."""
        m = PackageMetadata(
            title="My Package",
            description="A description",
            version="1.0.0",
            keywords=["data", "test"],
            license="CC-BY-4.0",
            homepage="https://example.com",
            id="12345",
            image="https://example.com/img.png",
        )
        result = _package_metadata_to_dict(m)
        assert result["title"] == "My Package"
        assert result["description"] == "A description"
        assert result["version"] == "1.0.0"
        assert result["keywords"] == ["data", "test"]
        assert result["license"] == "CC-BY-4.0"
        assert result["homepage"] == "https://example.com"
        assert result["id"] == "12345"
        assert result["image"] == "https://example.com/img.png"

    def test_omits_none_fields(self) -> None:
        """Test that only set fields appear in output."""
        m = PackageMetadata(title="Title Only")
        result = _package_metadata_to_dict(m)
        assert result == {"title": "Title Only"}
        assert "description" not in result
        assert "contributors" not in result

    def test_with_contributors(self) -> None:
        """Test metadata with contributors list."""
        m = PackageMetadata(
            title="Pkg",
            contributors=[
                Contributor(title="Alice", roles=["creator"]),
                Contributor(title="Bob"),
            ],
        )
        result = _package_metadata_to_dict(m)
        assert result["contributors"] == [
            {"title": "Alice", "roles": ["creator"]},
            {"title": "Bob"},
        ]


class TestBuildDatapackageWithPackageMetadata:
    """Tests that build_datapackage includes package metadata from datasets.yaml."""

    def test_build_includes_package_metadata(self, runner: CliRunner, test_project: Path) -> None:
        """Test that package build includes title, description, version etc from package section."""
        import json

        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(test_project / "datasets.yaml"), "-o", str(test_project / "dp.json")],
        )
        assert result.exit_code == 0

        dp = json.loads((test_project / "dp.json").read_text())
        assert dp["title"] == "UN Member States Dataset"
        assert "Processed data" in dp["description"]
        assert dp["version"] == "1.0.0"
        assert dp["keywords"] == ["united-nations", "member-states", "international-organizations"]
        assert dp["license"] == "CC-BY-4.0"
        assert dp["contributors"] == [{"title": "Sunstone Institute", "roles": ["creator", "publisher"]}]

    def test_build_without_package_metadata(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that build works fine when no package section is present."""
        import json

        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/test/\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "test.csv").write_text("col\nval")

        result = runner.invoke(
            main,
            ["package", "build", "-f", str(yaml_file), "-o", str(tmp_path / "dp.json")],
        )
        assert result.exit_code == 0

        dp = json.loads((tmp_path / "dp.json").read_text())
        assert "title" not in dp
        assert "description" not in dp
        assert "contributors" not in dp

    def test_push_includes_package_metadata(self, runner: CliRunner, test_project: Path) -> None:
        """Test that package push includes package metadata in the uploaded datapackage.json."""
        import json

        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

        uploaded_content: dict[str, str] = {}
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        def capture_upload(content: str, content_type: str | None = None) -> None:
            uploaded_content["datapackage"] = content

        mock_blob.upload_from_string.side_effect = capture_upload

        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = runner.invoke(main, ["package", "push", "-f", str(test_project / "datasets.yaml")])
            assert result.exit_code == 0

            dp = json.loads(uploaded_content["datapackage"])
            assert dp["title"] == "UN Member States Dataset"
            assert dp["version"] == "1.0.0"
            assert dp["license"] == "CC-BY-4.0"
            assert len(dp["contributors"]) == 1


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

    def test_lineage_help(self, runner: CliRunner) -> None:
        """Test lineage subcommand help."""
        result = runner.invoke(main, ["lineage", "--help"])
        assert result.exit_code == 0
        assert "upstream" in result.output
        assert "tree" in result.output


class TestLineageCLI:
    """Tests for lineage CLI commands."""

    @pytest.fixture
    def lineage_project(self, tmp_path: Path) -> Path:
        """Create a temporary project with lineage data in datasets.yaml."""
        datasets_yaml = tmp_path / "datasets.yaml"
        datasets_yaml.write_text(
            "inputs:\n"
            "  - slug: source-data\n"
            "    name: Source Data\n"
            "    location: inputs/source.csv\n"
            "outputs:\n"
            "  - slug: derived-data\n"
            "    name: Derived Data\n"
            "    location: outputs/derived.csv\n"
            "    lineage:\n"
            "      content_hash: abc123\n"
            '      created_at: "2026-03-06T12:00:00"\n'
            "      sources:\n"
            "        - slug: source-data\n"
        )
        return tmp_path

    def test_lineage_upstream_ascii(self, runner: CliRunner, lineage_project: Path) -> None:
        """Test upstream command shows ASCII tree."""
        datasets_file = str(lineage_project / "datasets.yaml")
        result = runner.invoke(main, ["lineage", "upstream", "-f", datasets_file, "derived-data"])
        assert result.exit_code == 0
        assert "derived-data" in result.output
        assert "source-data" in result.output

    def test_lineage_upstream_json(self, runner: CliRunner, lineage_project: Path) -> None:
        """Test upstream command with --json flag outputs valid JSON."""
        import json as json_mod

        datasets_file = str(lineage_project / "datasets.yaml")
        result = runner.invoke(
            main,
            ["lineage", "upstream", "-f", datasets_file, "--json", "derived-data"],
        )
        assert result.exit_code == 0
        data = json_mod.loads(result.output)
        assert data["slug"] == "derived-data"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["slug"] == "source-data"

    def test_lineage_upstream_not_found(self, runner: CliRunner, lineage_project: Path) -> None:
        """Test upstream command with nonexistent slug returns graceful output."""
        datasets_file = str(lineage_project / "datasets.yaml")
        result = runner.invoke(main, ["lineage", "upstream", "-f", datasets_file, "nonexistent"])
        # get_upstream returns a leaf node for unknown slugs (graceful)
        assert result.exit_code == 0
        assert "nonexistent" in result.output

    def test_lineage_tree(self, runner: CliRunner, lineage_project: Path) -> None:
        """Test tree command works as alias with depth=3 default."""
        datasets_file = str(lineage_project / "datasets.yaml")
        result = runner.invoke(main, ["lineage", "tree", "-f", datasets_file, "derived-data"])
        assert result.exit_code == 0
        assert "derived-data" in result.output
        assert "source-data" in result.output
