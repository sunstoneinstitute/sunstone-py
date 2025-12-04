"""
Lineage metadata structures for tracking data provenance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


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
    """Source attribution information for a dataset."""

    name: str
    """Name of the data source."""

    location: SourceLocation
    """Location information for the source."""

    attributed_to: str
    """Organization or individual to attribute the data to."""

    acquired_at: str
    """Date when the data was acquired (YYYY-MM-DD format)."""

    acquisition_method: str
    """Method used to acquire the data (e.g., 'manual-download', 'api', 'scraping')."""

    license: str
    """SPDX license identifier."""
    # TODO: Consider using a library for SPDX license validation.

    updated: Optional[str] = None
    """Optional description of update frequency."""


@dataclass
class FieldSchema:
    """Schema definition for a dataset field."""

    name: str
    """Name of the field/column."""

    type: str
    """Data type (string, number, integer, boolean, date, datetime)."""

    constraints: Optional[Dict[str, Any]] = None
    """Optional constraints (e.g., enum values)."""


@dataclass
class DatasetMetadata:
    """Metadata for a dataset from datasets.yaml."""

    name: str
    """Human-readable name of the dataset."""

    slug: str
    """Kebab-case identifier for the dataset."""

    location: str
    """File path or URL for the dataset."""

    fields: List[FieldSchema]
    """Schema definitions for dataset fields."""

    source: Optional[Source] = None
    """Source attribution (for input datasets)."""

    publish: bool = False
    """Whether this dataset should be published (for output datasets)."""

    dataset_type: str = "input"
    """Type of dataset: 'input' or 'output'."""


@dataclass
class LineageMetadata:
    """
    Lineage metadata tracking the provenance of data in a DataFrame.

    This tracks all source datasets that contributed to the current DataFrame.
    """

    sources: List[DatasetMetadata] = field(default_factory=list)
    """List of source datasets that contributed to this data."""

    created_at: datetime = field(default_factory=datetime.now)
    """Timestamp when this lineage was created."""

    project_path: Optional[str] = None
    """Path to the project directory containing datasets.yaml."""

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
            A new LineageMetadata with combined sources.
        """
        merged = LineageMetadata(
            sources=self.sources.copy(),
            created_at=datetime.now(),
            project_path=self.project_path or other.project_path,
        )

        # Add sources from other that aren't already present
        for source in other.sources:
            if source not in merged.sources:
                merged.sources.append(source)

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
        return {
            "sources": [
                {
                    "slug": src.slug,
                    "name": src.name,
                    "location": src.location,
                }
                for src in self.sources
            ],
            "created_at": self.created_at.isoformat(),
        }
