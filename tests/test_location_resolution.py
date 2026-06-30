"""Resolution semantics for DatasetsManager.find_dataset_by_location."""

from sunstone.datasets import DatasetsManager
from sunstone.lineage import FieldSchema


def test_exact_registered_string_matches_regardless_of_cwd(project_copy, monkeypatch, tmp_path):
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(tmp_path)  # somewhere unrelated
    ds = manager.find_dataset_by_location("inputs/official_un_member_states_raw.csv")
    assert ds is not None and ds.slug == "official-un-member-states"


def test_cwd_relative_path_from_subdir_matches(project_copy, monkeypatch):
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(project_copy / "outputs")
    ds = manager.find_dataset_by_location("../inputs/official_un_member_states_raw.csv")
    assert ds is not None and ds.slug == "official-un-member-states"


def test_symlinked_absolute_path_is_canonicalized(project_copy, tmp_path):
    link = tmp_path / "linked_project"
    link.symlink_to(project_copy)
    manager = DatasetsManager(project_copy)
    through_link = link / "inputs" / "official_un_member_states_raw.csv"
    ds = manager.find_dataset_by_location(str(through_link))
    assert ds is not None and ds.slug == "official-un-member-states"


def test_same_filename_in_other_directory_does_not_match(project_copy, monkeypatch):
    # The dropped fuzzy fallback: a file with the same NAME but a different
    # location must NOT resolve to the registered dataset.
    other = project_copy / "elsewhere"
    other.mkdir()
    decoy = other / "official_un_member_states_raw.csv"
    decoy.write_text("x\n")
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(project_copy)
    assert manager.find_dataset_by_location("elsewhere/official_un_member_states_raw.csv") is None


def test_index_invalidated_after_add_output_dataset(project_copy, monkeypatch):
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(project_copy)
    # Build the index once.
    assert manager.find_dataset_by_location("inputs/official_un_member_states_raw.csv") is not None
    # Register a new output, then look it up by location.
    manager.add_output_dataset(
        name="Brand New",
        slug="brand-new",
        location="outputs/brand_new.csv",
        fields=[FieldSchema(name="x", type="string")],
    )
    ds = manager.find_dataset_by_location("outputs/brand_new.csv", "output")
    assert ds is not None and ds.slug == "brand-new"
