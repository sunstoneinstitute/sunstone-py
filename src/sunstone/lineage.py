"""
Lineage metadata structures for tracking data provenance.

Aligned with W3C PROV-O (https://www.w3.org/TR/prov-o/):
- Entity: datasets (DatasetMetadata)
- Activity: script/notebook executions (Activity)
- Agent: users, software, organizations (Agent)
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    import pandas as pd


# ---------------------------------------------------------------------------
# PROV-O core types
# ---------------------------------------------------------------------------


class AgentType(Enum):
    """PROV-O agent subtypes."""

    PERSON = "prov:Person"
    SOFTWARE = "prov:SoftwareAgent"
    ORGANIZATION = "prov:Organization"


@dataclass
class Agent:
    """A PROV-O Agent: something that bears responsibility for an activity
    or for the existence of an entity.

    Maps to prov:Agent and subtypes prov:Person, prov:SoftwareAgent,
    prov:Organization.
    """

    id: str
    """Unique identifier (username, org name, software name)."""

    type: AgentType = AgentType.PERSON
    """The kind of agent."""

    label: Optional[str] = None
    """Human-readable label."""

    version: Optional[str] = None
    """Version string (for SoftwareAgent)."""


@dataclass(frozen=True)
class EntityRef:
    """Lightweight reference to a PROV Entity (dataset).

    Used in relationships to avoid circular object references.
    """

    slug: str
    """Dataset slug identifier."""

    namespace: Optional[str] = None
    """Optional namespace URI for external entities."""


@dataclass(frozen=True)
class ActivityRef:
    """Lightweight reference to a PROV Activity."""

    id: str
    """Activity identifier."""


@dataclass
class FieldDerivation:
    """Records that an output field was derived from a source entity,
    optionally from a specific source field.

    Maps to prov:qualifiedDerivation at the field level.
    """

    output_field: str
    """Name of the output field/column."""

    source_entity: str
    """Slug of the source dataset."""

    source_field: Optional[str] = None
    """Name of the source field, if known. None means derived from
    the dataset as a whole (e.g., computed from multiple fields)."""


@dataclass
class UsageRecord:
    """Records how an Activity used an Entity.

    Maps to prov:qualifiedUsage.
    """

    entity: EntityRef
    """Which entity was used."""

    columns: Optional[List[str]] = None
    """Which columns were selected (None means all)."""

    filters: Optional[Dict[str, Any]] = None
    """Filters applied during read."""


@dataclass
class Activity:
    """A PROV-O Activity: a script or notebook execution that transforms
    input entities into output entities.

    One Activity corresponds to one script/notebook execution.
    """

    id: str
    """Unique identifier (e.g. 'exec-{timestamp}-{hash}')."""

    used: List[UsageRecord] = field(default_factory=list)
    """prov:used — input entities consumed by this activity."""

    generated: List[EntityRef] = field(default_factory=list)
    """Inverse of prov:wasGeneratedBy — output entities produced."""

    was_associated_with: List[Agent] = field(default_factory=list)
    """prov:wasAssociatedWith — agents involved in this activity."""

    started_at: Optional[datetime] = None
    """prov:startedAtTime."""

    ended_at: Optional[datetime] = None
    """prov:endedAtTime."""

    script_path: Optional[str] = None
    """Path to the Python script that was executed."""

    notebook_path: Optional[str] = None
    """Path to the Jupyter notebook that was executed."""

    git_commit: Optional[str] = None
    """Git commit hash at time of execution."""

    git_dirty: Optional[bool] = None
    """Whether the git working tree had uncommitted changes."""

    transformation_params: Optional[Dict[str, Any]] = None
    """User-supplied parameters describing the transformation."""


# ---------------------------------------------------------------------------
# Dataset / source metadata
# ---------------------------------------------------------------------------


@dataclass
class SourceLocation:
    """Location information for a data source."""

    data: Optional[str] = None
    """URL to the data file."""

    metadata: Optional[str] = None
    """URL to metadata about the data."""

    about: Optional[str] = None
    """URL to a page describing the data source."""


@dataclass
class Source:
    """Source attribution information for a dataset.

    Maps to prov:wasAttributedTo on the dataset entity.
    """

    name: str
    """Name of the data source."""

    location: SourceLocation
    """Location information for the source."""

    attributed_to: Union[str, Agent]
    """Organization or individual to attribute the data to.
    Accepts a plain string for backwards compatibility (interpreted
    as an Organization agent)."""

    acquired_at: str
    """Date when the data was acquired (YYYY-MM-DD format)."""

    acquisition_method: str
    """Method used to acquire the data (e.g., 'manual-download', 'api', 'scraping')."""

    license: str
    """SPDX license identifier."""

    updated: Optional[str] = None
    """Optional description of update frequency."""

    @property
    def agent(self) -> Agent:
        """Return the attributed_to value as an Agent object."""
        if isinstance(self.attributed_to, Agent):
            return self.attributed_to
        return Agent(
            id=self.attributed_to,
            type=AgentType.ORGANIZATION,
            label=self.attributed_to,
        )


@dataclass
class FieldSchema:
    """Schema definition for a dataset field."""

    name: str
    """Name of the field/column."""

    type: str | None = None
    """Data type (string, number, integer, boolean, date, datetime, array, object). None means infer at write time."""

    constraints: Optional[Dict[str, Any]] = None
    """Optional constraints (e.g., enum values)."""

    description: Optional[str] = None
    """Human-readable description of the field."""

    unit: Optional[str] = None
    """Human-readable unit of measure (e.g., 'kg', '%', 'people')."""

    source: Optional[str] = None
    """Slug of the input dataset this field's data comes from."""

    unit_source: Optional[str] = None
    """Original unit string format for round-tripping (e.g. QUDT URI). None means Pint string."""


@dataclass
class Contributor:
    """Contributor information for a datapackage."""

    title: str
    """Name or title of the contributor."""

    roles: Optional[List[str]] = None
    """Roles of the contributor (e.g., 'creator', 'publisher', 'maintainer')."""

    path: Optional[str] = None
    """URL to contributor's website or profile."""

    email: Optional[str] = None
    """Email address of the contributor."""


@dataclass
class PackageMetadata:
    """Top-level package metadata for datapackage v2 compatibility.

    See https://datapackage.org/profiles/2.0/datapackage.json for the full spec.
    """

    title: Optional[str] = None
    """Human-readable title of the package."""

    description: Optional[str] = None
    """Description of the package (Markdown supported)."""

    version: Optional[str] = None
    """Package version number (semver recommended)."""

    keywords: Optional[List[str]] = None
    """Keywords/tags for discoverability."""

    license: Optional[str] = None
    """SPDX license identifier for output datasets."""

    contributors: Optional[List[Contributor]] = None
    """List of contributors to the package."""

    homepage: Optional[str] = None
    """URL to the project homepage."""

    id: Optional[str] = None
    """Globally unique identifier (UUID or DOI)."""

    image: Optional[str] = None
    """URL to a representative image."""


@dataclass
class PublishConfig:
    """Configuration for publishing datasets."""

    enabled: bool = False
    """Whether publishing is enabled."""

    to: Optional[str] = None
    """Destination URL or path. If not ending in .json, /datapackage.json is appended."""

    flatten: bool = False
    """If true, ignore directory structure and put all files in the same directory as datapackage.json."""

    as_url: Optional[str] = None
    """Public base URL for resource paths in datapackage.json. When set, resource paths become full URLs (e.g., https://foo.com/data/bar/file.csv)."""


@dataclass
class DatasetMetadata:
    """Metadata for a dataset from datasets.yaml."""

    name: str
    """Human-readable name of the dataset."""

    slug: str
    """Kebab-case identifier for the dataset."""

    location: str
    """File path or URL for the dataset."""

    description: Optional[str] = None
    """Human-readable description of the dataset."""

    resource_type: Optional[str] = None
    """Resource type (e.g., 'table'). Optional."""

    fields: Optional[List[FieldSchema]] = None
    """Schema definitions for dataset fields. Required for table resources."""

    source: Optional[Source] = None
    """Source attribution (for input datasets)."""

    strict: bool = False
    """Whether strict mode is enabled (lineage cannot be modified)."""

    dataset_type: str = "input"
    """Type of dataset: 'input' or 'output'."""

    rdf_prefixes: Optional[Dict[str, str]] = None
    """RDF namespace prefixes for custom properties."""

    custom_properties: Optional[Dict[str, Any]] = None
    """Custom properties including RDF triples."""

    publish: Optional[PublishConfig] = None
    """Per-dataset publish configuration (overrides top-level)."""

    # PROV-O relation fields (optional, populated when available)
    was_derived_from: Optional[List[EntityRef]] = None
    """prov:wasDerivedFrom — source entities this dataset was derived from."""

    was_generated_by: Optional[ActivityRef] = None
    """prov:wasGeneratedBy — the activity that generated this entity."""

    generated_at_time: Optional[datetime] = None
    """prov:generatedAtTime — when this entity was created/updated."""

    field_derivations: Optional[List[FieldDerivation]] = None
    """prov:qualifiedDerivation — field-level derivation detail."""


def compute_dataframe_hash(df: "pd.DataFrame") -> str:
    """
    Compute a fast SHA256 hash of a pandas DataFrame's content.

    Uses pickle serialization for a consistent, fast representation of the data.

    Args:
        df: The pandas DataFrame to hash.

    Returns:
        A SHA256 hex digest string representing the DataFrame content.
    """
    import pickle

    # Use pickle protocol 5 for efficiency; hash the bytes directly
    data_bytes = pickle.dumps(df, protocol=5)
    return hashlib.sha256(data_bytes).hexdigest()


@dataclass
class LineageMetadata:
    """
    Lineage metadata tracking the provenance of data in a DataFrame.

    This tracks all source datasets that contributed to the current DataFrame.
    """

    sources: List[DatasetMetadata] = field(default_factory=list)
    """List of source datasets that contributed to this data."""

    created_at: Optional[datetime] = None
    """Timestamp when this lineage was last updated (content changed)."""

    content_hash: Optional[str] = None
    """SHA256 hash of the DataFrame content, used to detect changes."""

    project_path: Optional[str] = None
    """Path to the project directory containing datasets.yaml."""

    activity: Optional[Activity] = None
    """The PROV-O Activity that generated this data. When present,
    this is the canonical provenance record; ``sources`` is kept
    for backwards compatibility."""

    field_derivations: Optional[List[FieldDerivation]] = None
    """Field-level derivation detail (prov:qualifiedDerivation).
    Propagated through DataFrame operations."""

    def add_source(self, dataset: DatasetMetadata) -> None:
        """
        Add a source dataset to the lineage.

        Args:
            dataset: The dataset metadata to add to sources.
        """
        if dataset not in self.sources:
            self.sources.append(dataset)

    def merge(self, other: "LineageMetadata") -> "LineageMetadata":
        """
        Merge lineage from another DataFrame.

        Args:
            other: The other lineage metadata to merge.

        Returns:
            A new LineageMetadata with combined sources and field derivations.
        """
        merged = LineageMetadata(
            sources=self.sources.copy(),
            project_path=self.project_path or other.project_path,
        )

        # Add sources from other that aren't already present
        for source in other.sources:
            if source not in merged.sources:
                merged.sources.append(source)

        # Merge field derivations (union, deduplicated by output_field + source)
        all_derivations: List[FieldDerivation] = []
        seen: set[tuple[str, str, Optional[str]]] = set()

        for fd_list in (self.field_derivations, other.field_derivations):
            if fd_list:
                for fd in fd_list:
                    key = (fd.output_field, fd.source_entity, fd.source_field)
                    if key not in seen:
                        seen.add(key)
                        all_derivations.append(fd)

        if all_derivations:
            merged.field_derivations = all_derivations

        return merged

    def get_licenses(self) -> List[str]:
        """
        Get all unique licenses from source datasets.

        Returns:
            List of unique license identifiers.
        """
        licenses = set()
        for source in self.sources:
            if source.source and source.source.license:
                licenses.add(source.source.license)
        return sorted(licenses)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert lineage metadata to a dictionary representation.

        Returns:
            Dictionary containing lineage information.
        """
        result: Dict[str, Any] = {
            "sources": [
                {
                    "slug": src.slug,
                    "name": src.name,
                    "location": src.location,
                }
                for src in self.sources
            ],
        }
        if self.created_at is not None:
            result["created_at"] = self.created_at.isoformat()
        if self.content_hash is not None:
            result["content_hash"] = self.content_hash
        return result


@dataclass
class Metadata:
    """Unified metadata container for data objects.

    Holds lineage, dataset identity, description, RDF prefixes,
    custom properties, and per-field metadata. Not DataFrame-specific —
    can be reused for other data containers.
    """

    lineage: LineageMetadata = field(default_factory=LineageMetadata)
    """Lineage metadata tracking data provenance."""

    description: str | None = None
    """Human-readable description of the dataset."""

    rdf_prefixes: Dict[str, str] | None = None
    """RDF namespace prefixes for custom properties."""

    custom_properties: Dict[str, Any] | None = None
    """Custom properties including RDF triples."""

    field_metadata: Dict[str, "FieldSchema"] = field(default_factory=dict)
    """Per-column metadata, keyed by column name."""

    slug: str | None = None
    """Dataset slug (kebab-case identifier), used at write time."""

    name: str | None = None
    """Human-readable dataset name, used at write time."""
