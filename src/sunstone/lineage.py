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
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Union

if TYPE_CHECKING:
    import pandas as pd
    from .component import ComponentSchema


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

    custom_properties: Optional[Dict[str, Any]] = None
    """Field-level custom/RDF properties (e.g. sosa:observedProperty), expanded at build time."""


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
class PackageEntry:
    """A package definition combining metadata, publish config, and dataset membership.

    Used by ``DatasetsManager.get_packages()`` to represent either a single
    ``package:`` or one entry in a ``packages:`` list from datasets.yaml.
    """

    metadata: PackageMetadata
    """Title, description, version, and other package-level metadata."""

    name: Optional[str] = None
    """Datapackage name/slug. None for singular package: (auto-derived from project slug)."""

    publish: Optional[PublishConfig] = None
    """Where and how to publish this package."""

    datasets: Optional[List[str]] = None
    """Dataset slugs included in this package. None means all outputs (single-package mode)."""


@dataclass
class CsvDialect:
    """CSV dialect for reading and writing delimited text files.

    Fields follow the Frictionless Data ``csv`` dialect convention. Defaults
    match plain pandas ``read_csv`` / ``to_csv`` behavior so a missing
    dialect block is equivalent to passing nothing.
    """

    delimiter: str = ","
    """Field separator (``sep``/``delimiter`` in pandas)."""

    quote_char: str = '"'
    """Character used to quote fields containing special characters."""

    header: bool = True
    """Whether the file has (on read) or should be written with (on write) a header row."""


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

    license: Optional[str] = None
    """SPDX license identifier for output datasets. Falls back to package.license when unset."""

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

    dialect: Optional[CsvDialect] = None
    """CSV dialect (delimiter, quote char, header) for ``text/csv`` datasets.
    ``None`` means use pandas defaults (comma-delimited, double-quote, header row)."""


def compute_dataframe_hash(df: "pd.DataFrame") -> str:
    """
    Compute a fast SHA256 hash of a pandas DataFrame's content.

    Uses pickle serialization for a consistent, fast representation of the data.

    Args:
        df: The pandas DataFrame to hash.

    Returns:
        A prefixed hash string (sha256:hex) representing the DataFrame content.
    """
    import pickle

    # Use pickle protocol 5 for efficiency; hash the bytes directly
    data_bytes = pickle.dumps(df, protocol=5)
    return f"sha256:{hashlib.sha256(data_bytes).hexdigest()}"


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

    data_hash: Optional[str] = None
    """SHA256 hash of the DataFrame content (sha256:hex), used to detect changes."""

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

    def populate_field_derivations(self, columns: List[str], slug: str) -> None:
        """Auto-populate field derivations for columns read from a source dataset.

        Creates a FieldDerivation(output_field=col, source_entity=slug,
        source_field=col) for each column, so that field-level provenance
        is tracked automatically from read through to write.
        """
        derivations = [FieldDerivation(output_field=col, source_entity=slug, source_field=col) for col in columns]
        if self.field_derivations is None:
            self.field_derivations = derivations
        else:
            self.field_derivations.extend(derivations)

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
        if self.data_hash is not None:
            result["data_hash"] = self.data_hash
        return result


@dataclass
class Metadata:
    """Unified metadata container for data objects.

    Holds lineage, description, RDF prefixes,
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

    component_metadata: Dict[str, "ComponentSchema"] = field(default_factory=dict)
    """Per-component metadata (columns, bands, variables, layers). The
    canonical store; `field_metadata` is a typed view over the column entries
    here for tabular kinds."""

    # Default JSON-LD context prefixes (class-level constant, not a dataclass field)
    _DEFAULT_PREFIXES: ClassVar[Dict[str, str]] = {
        "dcat": "http://www.w3.org/ns/dcat#",
        "dct": "http://purl.org/dc/terms/",
        "prov": "http://www.w3.org/ns/prov#",
        "si": "https://sunstone.institute/rdf/vocab#",
        "schema": "http://schema.org/",
    }

    def __setitem__(self, key: str, value: Any) -> None:
        if ":" not in key:
            raise ValueError(
                f"Metadata keys must be prefixed RDF names (contain ':'). "
                f"Got bare key {key!r}. Use a regular attribute for non-RDF fields."
            )
        if self.custom_properties is None:
            self.custom_properties = {}
        self.custom_properties[key] = value

    def __getitem__(self, key: str) -> Any:
        if self.custom_properties is None or key not in self.custom_properties:
            raise KeyError(key)
        return self.custom_properties[key]

    def __delitem__(self, key: str) -> None:
        if self.custom_properties is None or key not in self.custom_properties:
            raise KeyError(key)
        del self.custom_properties[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str) or self.custom_properties is None:
            return False
        return key in self.custom_properties

    def to_jsonld(self) -> Dict[str, Any]:
        """Serialize metadata to a JSON-LD document.

        Returns:
            A dictionary representing a JSON-LD document with ``@context``,
            ``@type``, and mapped metadata fields.  ``None``-valued fields
            are omitted, and ``lineage.project_path`` is never included.
        """
        # Build @context: defaults merged with user prefixes
        context = dict(self._DEFAULT_PREFIXES)
        if self.rdf_prefixes:
            context.update(self.rdf_prefixes)

        doc: Dict[str, Any] = {
            "@context": context,
            "@type": "dcat:Distribution",
            "si:version": "1.0",
        }

        # Core identity fields
        if self.slug is not None:
            doc["dct:identifier"] = self.slug
        if self.name is not None:
            doc["dct:title"] = self.name
        if self.description is not None:
            doc["dct:description"] = self.description

        # Lineage fields
        if self.lineage.created_at is not None:
            doc["dct:created"] = self.lineage.created_at.isoformat()
        if self.lineage.data_hash is not None:
            doc["si:dataHash"] = self.lineage.data_hash

        # Sources
        if self.lineage.sources:
            sources_list = []
            for src in self.lineage.sources:
                source_doc: Dict[str, Any] = {
                    "dct:identifier": src.slug,
                    "dct:title": src.name,
                }
                # Prefer the original source URL over the local file path
                if src.source and src.source.location and src.source.location.data:
                    source_doc["dcat:downloadURL"] = src.source.location.data
                elif src.location:
                    source_doc["dcat:downloadURL"] = src.location
                sources_list.append(source_doc)
            doc["prov:wasDerivedFrom"] = sources_list

        # Build field derivation lookup
        fd_by_field: Dict[str, FieldDerivation] = {}
        if self.lineage.field_derivations:
            for fd in self.lineage.field_derivations:
                fd_by_field[fd.output_field] = fd

        # Field metadata + derivations
        if self.field_metadata:
            fields: Dict[str, Any] = {}
            for col_name, fs in self.field_metadata.items():
                entry: Dict[str, Any] = {}
                if fs.description is not None:
                    entry["dct:description"] = fs.description
                if fs.unit is not None:
                    entry["si:unit"] = fs.unit
                if fs.type is not None:
                    entry["si:type"] = fs.type
                if fs.custom_properties:
                    for key, value in fs.custom_properties.items():
                        entry[key] = value
                if col_name in fd_by_field:
                    fd = fd_by_field[col_name]
                    derivation: Dict[str, Any] = {"dct:identifier": fd.source_entity}
                    if fd.source_field is not None:
                        derivation["si:sourceField"] = fd.source_field
                    entry["prov:wasDerivedFrom"] = derivation
                if entry:
                    fields[col_name] = entry
            if fields:
                doc["si:fields"] = fields

        # Custom properties as top-level keys
        if self.custom_properties:
            for key, value in self.custom_properties.items():
                doc[key] = value

        return doc

    @classmethod
    def from_jsonld(cls, doc: Dict[str, Any]) -> "Metadata":
        """Reconstruct a Metadata instance from a JSON-LD document.

        Unrecognized top-level keys are placed into ``custom_properties``
        for forward compatibility.  User-defined prefixes (those not in
        ``_DEFAULT_PREFIXES``) are extracted into ``rdf_prefixes``.

        Args:
            doc: A JSON-LD dictionary previously produced by ``to_jsonld()``
                or compatible external tooling.

        Returns:
            A new ``Metadata`` instance.
        """
        default_prefixes = {
            "dcat": "http://www.w3.org/ns/dcat#",
            "dct": "http://purl.org/dc/terms/",
            "prov": "http://www.w3.org/ns/prov#",
            "si": "https://sunstone.institute/rdf/vocab#",
            "schema": "http://schema.org/",
        }

        # Extract user prefixes from @context
        context = doc.get("@context", {})
        user_prefixes = {k: v for k, v in context.items() if k not in default_prefixes}
        rdf_prefixes = user_prefixes if user_prefixes else None

        # Core fields
        slug = doc.get("dct:identifier")
        name = doc.get("dct:title")
        description = doc.get("dct:description")

        # Lineage
        created_at = None
        created_str = doc.get("dct:created")
        if created_str is not None:
            created_at = datetime.fromisoformat(created_str)

        data_hash = doc.get("si:dataHash")

        # Sources
        sources: List[DatasetMetadata] = []
        for src in doc.get("prov:wasDerivedFrom", []):
            sources.append(
                DatasetMetadata(
                    slug=src.get("dct:identifier", ""),
                    name=src.get("dct:title", ""),
                    location=src.get("dcat:downloadURL", ""),
                )
            )

        # Field metadata and derivations
        field_metadata: Dict[str, FieldSchema] = {}
        field_derivations: List[FieldDerivation] = []
        si_fields = doc.get("si:fields", {})
        _field_known_keys = {"si:type", "dct:description", "si:unit", "prov:wasDerivedFrom"}
        for col_name, entry in si_fields.items():
            field_custom = {k: v for k, v in entry.items() if k not in _field_known_keys}
            fs = FieldSchema(
                name=col_name,
                type=entry.get("si:type"),
                description=entry.get("dct:description"),
                unit=entry.get("si:unit"),
                custom_properties=field_custom or None,
            )
            field_metadata[col_name] = fs
            derivation = entry.get("prov:wasDerivedFrom")
            if derivation is not None:
                field_derivations.append(
                    FieldDerivation(
                        output_field=col_name,
                        source_entity=derivation["dct:identifier"],
                        source_field=derivation.get("si:sourceField"),
                    )
                )

        lineage = LineageMetadata(
            sources=sources,
            created_at=created_at,
            data_hash=data_hash,
            field_derivations=field_derivations if field_derivations else None,
        )

        # Collect unknown top-level keys into custom_properties
        known_keys = {
            "@context",
            "@type",
            "si:version",
            "dct:identifier",
            "dct:title",
            "dct:description",
            "dct:created",
            "si:dataHash",
            "prov:wasDerivedFrom",
            "si:fields",
        }
        custom_properties: Dict[str, Any] = {}
        for key, value in doc.items():
            if key not in known_keys:
                custom_properties[key] = value

        return cls(
            lineage=lineage,
            slug=slug,
            name=name,
            description=description,
            rdf_prefixes=rdf_prefixes,
            custom_properties=custom_properties if custom_properties else None,
            field_metadata=field_metadata,
        )
