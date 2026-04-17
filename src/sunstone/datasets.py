"""
Parser and manager for datasets.yaml files.
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ruamel.yaml import YAML

from .exceptions import DatasetNotFoundError, DatasetValidationError
from .lineage import (
    Activity,
    ActivityRef,
    Agent,
    AgentType,
    Contributor,
    DatasetMetadata,
    EntityRef,
    FieldDerivation,
    FieldSchema,
    LineageMetadata,
    PackageEntry,
    PackageMetadata,
    PublishConfig,
    Source,
    SourceLocation,
    UsageRecord,
)

logger = logging.getLogger(__name__)

# Configure ruamel.yaml for round-trip parsing (preserves comments) with proper indentation
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)


def _field_schema_to_dict(field: FieldSchema) -> dict:
    """Convert a FieldSchema to a dict for YAML serialization, omitting None values."""
    d: dict = {"name": field.name}
    if field.type is not None:
        d["type"] = field.type
    if field.constraints:
        d["constraints"] = field.constraints
    if field.description:
        d["description"] = field.description
    if field.unit:
        d["unit"] = field.unit_source if field.unit_source else field.unit
    if field.source:
        d["source"] = field.source
    return d


class DatasetsManager:
    """
    Manager for parsing and updating datasets.yaml files.

    This class handles reading, parsing, and updating dataset metadata
    from datasets.yaml files in Sunstone projects.
    """

    def __init__(
        self,
        project_path: Union[str, Path],
        datasets_file: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize the datasets manager.

        Args:
            project_path: Path to the project directory containing datasets.yaml.
            datasets_file: Path to a specific datasets YAML file. If relative,
                resolved against project_path. Defaults to "datasets.yaml".

        Raises:
            FileNotFoundError: If the datasets file doesn't exist.
        """
        self.project_path = Path(project_path).resolve()
        if datasets_file is not None:
            df_path = Path(datasets_file)
            self.datasets_file = df_path if df_path.is_absolute() else self.project_path / df_path
        else:
            self.datasets_file = self.project_path / "datasets.yaml"

        if not self.datasets_file.exists():
            raise FileNotFoundError(f"{self.datasets_file} not found")

        self._data: Dict[str, Any] = {}
        self._defaults: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load and parse the datasets.yaml file."""
        with open(self.datasets_file, "r") as f:
            self._data = _yaml.load(f) or {}

        if "inputs" not in self._data:
            self._data["inputs"] = []
        if "outputs" not in self._data:
            self._data["outputs"] = []

        # Load defaults if present
        self._defaults = self._data.get("defaults", {})

        # Load top-level rdfPrefixes if present
        self._rdf_prefixes: Dict[str, str] = self._data.get("rdfPrefixes", {})

    def _save(self) -> None:
        """Save the current data back to datasets.yaml."""
        with open(self.datasets_file, "w") as f:
            _yaml.dump(self._data, f)

    def _parse_source_location(self, loc_data: Dict[str, Any]) -> SourceLocation:
        """Parse source location data from YAML."""
        return SourceLocation(
            data=loc_data.get("data"),
            metadata=loc_data.get("metadata"),
            about=loc_data.get("about"),
        )

    def _parse_source(self, source_data: Dict[str, Any]) -> Source:
        """Parse source attribution data from YAML."""
        attributed_to_raw = source_data["attributedTo"]
        if isinstance(attributed_to_raw, dict):
            attributed_to: str | Agent = Agent(
                id=attributed_to_raw["id"],
                type=AgentType(attributed_to_raw.get("type", "prov:Organization")),
                label=attributed_to_raw.get("label"),
                version=attributed_to_raw.get("version"),
            )
        else:
            attributed_to = str(attributed_to_raw)

        return Source(
            name=source_data["name"],
            location=self._parse_source_location(source_data["location"]),
            attributed_to=attributed_to,
            acquired_at=source_data["acquiredAt"],
            acquisition_method=source_data["acquisitionMethod"],
            license=source_data["license"],
            updated=source_data.get("updated"),
        )

    def _parse_fields(self, fields_data: List[Dict[str, Any]]) -> List[FieldSchema]:
        """Parse field schema data from YAML."""
        from .units import is_qudt_uri, parse_unit_string

        result = []
        for field in fields_data:
            unit_str = field.get("unit")
            unit_value = unit_str
            unit_source = None

            if unit_str and is_qudt_uri(unit_str):
                try:
                    pint_unit, unit_source = parse_unit_string(unit_str)
                    unit_value = str(pint_unit)
                except Exception:
                    unit_value = unit_str
                    unit_source = unit_str

            result.append(
                FieldSchema(
                    name=field["name"],
                    type=field["type"],
                    constraints=field.get("constraints"),
                    description=field.get("description"),
                    unit=unit_value,
                    source=field.get("source"),
                    unit_source=unit_source,
                )
            )
        return result

    def _parse_publish(self, publish_data: Any) -> Optional[PublishConfig]:
        """
        Parse publish configuration from YAML.

        Supports both legacy boolean format and new object format:
        - publish: true -> PublishConfig(enabled=True)
        - publish: false -> None
        - publish: { enabled: true, to: "...", flatten: false } -> PublishConfig(...)
        """
        if publish_data is None:
            return None
        if isinstance(publish_data, bool):
            return PublishConfig(enabled=publish_data)
        if isinstance(publish_data, dict):
            enabled = publish_data.get("enabled", False)
            return PublishConfig(
                enabled=enabled,
                to=publish_data.get("to"),
                flatten=publish_data.get("flatten", False),
                as_url=publish_data.get("as"),
            )
        return None

    def _parse_activity(self, activity_data: Dict[str, Any]) -> Activity:
        """Parse a PROV-O Activity from YAML lineage data."""
        from datetime import datetime

        agents = []
        for agent_data in activity_data.get("agents", []):
            agents.append(
                Agent(
                    id=agent_data["id"],
                    type=AgentType(agent_data.get("type", "prov:Person")),
                    label=agent_data.get("label"),
                    version=agent_data.get("version"),
                )
            )

        used = []
        for usage_data in activity_data.get("used", []):
            entity_val = usage_data.get("entity", "")
            if isinstance(entity_val, dict):
                entity_ref = EntityRef(slug=entity_val["slug"], namespace=entity_val.get("namespace"))
            else:
                entity_ref = EntityRef(slug=str(entity_val))
            used.append(
                UsageRecord(
                    entity=entity_ref,
                    columns=usage_data.get("columns"),
                    filters=usage_data.get("filters"),
                )
            )

        started_at = None
        if "started_at" in activity_data:
            started_at = datetime.fromisoformat(activity_data["started_at"])
        ended_at = None
        if "ended_at" in activity_data:
            ended_at = datetime.fromisoformat(activity_data["ended_at"])

        return Activity(
            id=activity_data["id"],
            used=used,
            was_associated_with=agents,
            started_at=started_at,
            ended_at=ended_at,
            script_path=activity_data.get("script_path"),
            notebook_path=activity_data.get("notebook_path"),
            git_commit=activity_data.get("git_commit"),
            git_dirty=activity_data.get("git_dirty"),
            transformation_params=activity_data.get("transformation_params"),
        )

    def _parse_field_derivations(self, derivations_data: List[Dict[str, Any]]) -> List[FieldDerivation]:
        """Parse field derivation data from YAML."""
        return [
            FieldDerivation(
                output_field=d["output_field"],
                source_entity=d["source_entity"],
                source_field=d.get("source_field"),
            )
            for d in derivations_data
        ]

    @staticmethod
    def _activity_to_dict(activity: Activity) -> Dict[str, Any]:
        """Serialize an Activity to a dict for YAML output."""
        result: Dict[str, Any] = {"id": activity.id}

        if activity.started_at:
            result["started_at"] = activity.started_at.isoformat()
        if activity.ended_at:
            result["ended_at"] = activity.ended_at.isoformat()
        if activity.script_path:
            result["script_path"] = activity.script_path
        if activity.notebook_path:
            result["notebook_path"] = activity.notebook_path
        if activity.git_commit:
            result["git_commit"] = activity.git_commit
        if activity.git_dirty is not None:
            result["git_dirty"] = activity.git_dirty

        if activity.was_associated_with:
            agents_list = []
            for agent in activity.was_associated_with:
                agent_dict: Dict[str, Any] = {"id": agent.id, "type": agent.type.value}
                if agent.label:
                    agent_dict["label"] = agent.label
                if agent.version:
                    agent_dict["version"] = agent.version
                agents_list.append(agent_dict)
            result["agents"] = agents_list

        if activity.used:
            used_list = []
            for usage in activity.used:
                usage_dict: Dict[str, Any] = {"entity": usage.entity.slug}
                if usage.columns:
                    usage_dict["columns"] = usage.columns
                if usage.filters:
                    usage_dict["filters"] = usage.filters
                used_list.append(usage_dict)
            result["used"] = used_list

        if activity.transformation_params:
            result["transformation_params"] = activity.transformation_params

        return result

    @staticmethod
    def _field_derivations_to_list(derivations: List[FieldDerivation]) -> List[Dict[str, Any]]:
        """Serialize FieldDerivations to a list of dicts for YAML output."""
        result = []
        for d in derivations:
            entry: Dict[str, Any] = {
                "output_field": d.output_field,
                "source_entity": d.source_entity,
            }
            if d.source_field:
                entry["source_field"] = d.source_field
            result.append(entry)
        return result

    def _parse_contributor(self, contrib_data: Dict[str, Any]) -> Contributor:
        """Parse contributor data from YAML."""
        return Contributor(
            title=contrib_data["title"],
            roles=contrib_data.get("roles"),
            path=contrib_data.get("path"),
            email=contrib_data.get("email"),
        )

    def _parse_package(self, package_data: Optional[Dict[str, Any]]) -> Optional[PackageMetadata]:
        """
        Parse package metadata from YAML.

        Args:
            package_data: Raw package data from YAML, or None.

        Returns:
            PackageMetadata if data is present, None otherwise.
        """
        if package_data is None:
            return None

        contributors = None
        if "contributors" in package_data:
            contributors = [self._parse_contributor(c) for c in package_data["contributors"]]

        return PackageMetadata(
            title=package_data.get("title"),
            description=package_data.get("description"),
            version=package_data.get("version"),
            keywords=package_data.get("keywords"),
            license=package_data.get("license"),
            contributors=contributors,
            homepage=package_data.get("homepage"),
            id=package_data.get("id"),
            image=package_data.get("image"),
        )

    def _is_rdf_property_key(self, key: str) -> bool:
        """Check if a key is an RDF property (contains : or is a URI)."""
        return ":" in key or key.startswith("http://") or key.startswith("https://")

    def _extract_rdf_properties(
        self, dataset_data: Dict[str, Any]
    ) -> tuple[Optional[Dict[str, str]], Optional[Dict[str, Any]]]:
        """
        Extract RDF prefixes and custom properties from dataset data.

        Returns:
            Tuple of (rdf_prefixes, custom_properties)
        """
        # Standard dataset fields to exclude from custom properties
        standard_fields = {
            "name",
            "slug",
            "description",
            "location",
            "fields",
            "source",
            "strict",
            "lineage",
            "rdfPrefixes",
            "publish",
        }

        # Get RDF prefixes with precedence: dataset > top-level > defaults
        rdf_prefixes = dataset_data.get("rdfPrefixes")
        if rdf_prefixes is None and self._rdf_prefixes:
            rdf_prefixes = self._rdf_prefixes
        if rdf_prefixes is None and "rdfPrefixes" in self._defaults:
            rdf_prefixes = self._defaults["rdfPrefixes"]

        # Extract custom properties (including RDF triples)
        custom_properties = {}
        for key, value in dataset_data.items():
            if key not in standard_fields:
                custom_properties[key] = value

        # Also merge in defaults if they're RDF properties
        for key, value in self._defaults.items():
            if key not in ["rdfPrefixes"] and self._is_rdf_property_key(key) and key not in custom_properties:
                custom_properties[key] = value

        return (rdf_prefixes if rdf_prefixes else None, custom_properties if custom_properties else None)

    def _parse_dataset(self, dataset_data: Dict[str, Any], dataset_type: str) -> DatasetMetadata:
        """
        Parse dataset metadata from YAML data.

        Args:
            dataset_data: Raw dataset data from YAML.
            dataset_type: Either 'input' or 'output'.

        Returns:
            Parsed DatasetMetadata object.
        """
        source = None
        if "source" in dataset_data:
            source = self._parse_source(dataset_data["source"])

        rdf_prefixes, custom_properties = self._extract_rdf_properties(dataset_data)

        fields_data = dataset_data.get("fields")
        fields = self._parse_fields(fields_data) if fields_data is not None else None

        publish = self._parse_publish(dataset_data.get("publish"))

        slug = dataset_data["slug"]
        if publish is not None:
            import warnings

            warnings.warn(
                f"Per-dataset 'publish:' on '{slug}' is deprecated. Use 'packages:' with a 'datasets:' list instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Parse PROV-O fields from lineage section (outputs only)
        lineage_raw = dataset_data.get("lineage", {})
        was_derived_from = None
        was_generated_by = None
        generated_at_time = None
        field_derivations_parsed = None

        if lineage_raw:
            from datetime import datetime as _dt

            # was_derived_from from sources list
            sources_raw = lineage_raw.get("sources", [])
            if sources_raw:
                was_derived_from = [EntityRef(slug=s["slug"] if isinstance(s, dict) else str(s)) for s in sources_raw]

            # generated_at_time from created_at
            created_at_raw = lineage_raw.get("created_at")
            if created_at_raw:
                try:
                    generated_at_time = _dt.fromisoformat(str(created_at_raw))
                except (ValueError, TypeError):
                    pass

            # activity → was_generated_by ref
            activity_raw = lineage_raw.get("activity")
            if activity_raw:
                was_generated_by = ActivityRef(id=activity_raw["id"])

            # field_derivations
            fd_raw = lineage_raw.get("field_derivations")
            if fd_raw:
                field_derivations_parsed = self._parse_field_derivations(fd_raw)

        return DatasetMetadata(
            name=dataset_data["name"],
            slug=dataset_data["slug"],
            location=dataset_data["location"],
            description=dataset_data.get("description"),
            resource_type=dataset_data.get("type"),
            fields=fields,
            source=source,
            strict=dataset_data.get("strict", False),
            dataset_type=dataset_type,
            rdf_prefixes=rdf_prefixes,
            custom_properties=custom_properties,
            publish=publish,
            was_derived_from=was_derived_from,
            was_generated_by=was_generated_by,
            generated_at_time=generated_at_time,
            field_derivations=field_derivations_parsed,
        )

    def find_dataset_by_location(self, location: str, dataset_type: Optional[str] = None) -> Optional[DatasetMetadata]:
        """
        Find a dataset by its file location.

        Args:
            location: The file path or URL to search for.
            dataset_type: Optional filter by 'input' or 'output'.

        Returns:
            DatasetMetadata if found, None otherwise.
        """
        # Normalize location to handle both absolute and relative paths
        location_path = Path(location)
        if location_path.is_absolute():
            # Try to make it relative to project path
            try:
                location = str(location_path.relative_to(self.project_path))
            except ValueError:
                # Not relative to project path, use as-is
                location = str(location_path)
        else:
            location = str(location_path)

        search_types = ["input", "output"] if dataset_type is None else [dataset_type]

        # Resolve the requested location to an absolute path
        location_path = Path(location)
        if not location_path.is_absolute():
            location_abs = (self.project_path / location_path).resolve()
        else:
            location_abs = location_path.resolve()

        for dtype in search_types:
            key = "inputs" if dtype == "input" else "outputs"
            for dataset_data in self._data.get(key, []):
                dataset_location = dataset_data["location"]

                # Try multiple resolution strategies:
                # 1. Direct string match
                if dataset_location == location:
                    return self._parse_dataset(dataset_data, dtype)

                # 2. Resolve dataset location as-is
                dataset_loc = Path(dataset_location)
                if not dataset_loc.is_absolute():
                    dataset_abs = (self.project_path / dataset_loc).resolve()
                else:
                    dataset_abs = dataset_loc.resolve()

                if dataset_abs == location_abs:
                    return self._parse_dataset(dataset_data, dtype)

                # 3. If the requested location exists, and just the filename matches,
                #    check if they point to the same existing file
                if location_abs.exists() and dataset_abs.exists():
                    if location_abs.samefile(dataset_abs):
                        return self._parse_dataset(dataset_data, dtype)

                # 4. If requested location exists but dataset location in yaml doesn't,
                #    check if the filename matches (for cases where the directory changed)
                if location_abs.exists() and not dataset_abs.exists():
                    if dataset_loc.name == location_path.name:
                        # Same filename - this might be a match
                        if (
                            location_abs.samefile(self.project_path / dataset_loc.name)
                            if (self.project_path / dataset_loc.name).exists()
                            else False
                        ):
                            return self._parse_dataset(dataset_data, dtype)
                        # Check in common subdirectories
                        for subdir in ["inputs", "outputs", "data"]:
                            candidate = self.project_path / subdir / dataset_loc.name
                            if candidate.exists() and location_abs.samefile(candidate):
                                return self._parse_dataset(dataset_data, dtype)

        return None

    def find_dataset_by_slug(self, slug: str, dataset_type: Optional[str] = None) -> Optional[DatasetMetadata]:
        """
        Find a dataset by its slug.

        Args:
            slug: The dataset slug to search for.
            dataset_type: Optional filter by 'input' or 'output'.

        Returns:
            DatasetMetadata if found, None otherwise.
        """
        search_types = ["input", "output"] if dataset_type is None else [dataset_type]

        for dtype in search_types:
            key = "inputs" if dtype == "input" else "outputs"
            for dataset_data in self._data.get(key, []):
                if dataset_data["slug"] == slug:
                    return self._parse_dataset(dataset_data, dtype)

        return None

    def get_all_inputs(self) -> List[DatasetMetadata]:
        """
        Get all input datasets.

        Returns:
            List of all input dataset metadata.
        """
        return [self._parse_dataset(data, "input") for data in self._data.get("inputs", [])]

    def get_all_outputs(self) -> List[DatasetMetadata]:
        """
        Get all output datasets.

        Returns:
            List of all output dataset metadata.
        """
        return [self._parse_dataset(data, "output") for data in self._data.get("outputs", [])]

    def get_publish_config(self) -> Optional[PublishConfig]:
        """
        Get the top-level publish configuration.

        Returns:
            Publish configuration if present, None otherwise.
        """
        return self._parse_publish(self._data.get("publish"))

    def get_package_metadata(self) -> Optional[PackageMetadata]:
        """
        Get the top-level package metadata.

        Returns:
            PackageMetadata if present, None otherwise.
        """
        return self._parse_package(self._data.get("package"))

    def get_packages(self) -> list[PackageEntry]:
        """Get package definitions from datasets.yaml.

        Supports two mutually exclusive forms:
        - ``package:`` (singular): backward-compatible single package.
          Top-level ``publish:`` is copied into the package entry.
          Returns a single PackageEntry with ``datasets=None`` (all outputs).
        - ``packages:`` (plural): list of explicit package definitions,
          each with ``name``, ``datasets``, optional metadata and ``publish``.

        Returns:
            List of PackageEntry objects. Empty if neither form is present.

        Raises:
            ValueError: If both ``package:`` and ``packages:`` are present,
                if ``packages:`` is used with top-level ``publish:``,
                if a packages entry is missing ``name`` or ``datasets``,
                or if a dataset slug doesn't exist.
        """
        has_singular = "package" in self._data
        has_plural = "packages" in self._data

        if has_singular and has_plural:
            raise ValueError(
                "Cannot use both 'package:' and 'packages:' in datasets.yaml. "
                "Use 'package:' for a single package or 'packages:' for multiple."
            )

        if has_plural:
            if "publish" in self._data:
                raise ValueError(
                    "A top-level 'publish:' is not allowed with 'packages:'. "
                    "Move publish config into each package entry."
                )
            return [self._parse_package_entry(entry) for entry in self._data["packages"]]

        if has_singular:
            metadata = self._parse_package(self._data["package"])
            if metadata is None:
                metadata = PackageMetadata()
            publish = self.get_publish_config()
            return [PackageEntry(metadata=metadata, name=None, publish=publish, datasets=None)]

        return []

    def _parse_package_entry(self, entry_data: Dict[str, Any]) -> PackageEntry:
        """Parse a single entry from the packages: list.

        Args:
            entry_data: Raw dict from YAML.

        Returns:
            A PackageEntry with validated dataset slugs.

        Raises:
            ValueError: If name or datasets is missing, or a slug doesn't exist.
        """
        name = entry_data.get("name")
        if not name:
            raise ValueError("Each 'packages:' entry: 'name' is required.")

        datasets = entry_data.get("datasets")
        if datasets is None:
            raise ValueError(f"Package '{name}': 'datasets' list is required in each packages: entry.")

        # Validate all slugs exist
        all_slugs = {ds.get("slug") for ds in self._data.get("inputs", []) + self._data.get("outputs", [])}
        for slug in datasets:
            if slug not in all_slugs:
                raise ValueError(f"Package '{name}': dataset slug '{slug}' not found in inputs or outputs.")

        # Parse package metadata from remaining fields
        metadata_keys = {
            "title",
            "description",
            "version",
            "keywords",
            "license",
            "contributors",
            "homepage",
            "id",
            "image",
        }
        metadata_data = {k: v for k, v in entry_data.items() if k in metadata_keys}
        metadata = (self._parse_package(metadata_data) if metadata_data else None) or PackageMetadata()

        publish = self._parse_publish(entry_data.get("publish"))

        return PackageEntry(
            metadata=metadata,
            name=name,
            publish=publish,
            datasets=list(datasets),
        )

    def get_top_level_custom_properties(self) -> Dict[str, Any]:
        """
        Get top-level custom properties from datasets.yaml.

        Returns all top-level fields whose key contains a ':' character
        (i.e., RDF/namespaced properties), filtering out standard fields
        like package, publish, inputs, outputs, and defaults.
        """
        return {key: value for key, value in self._data.items() if ":" in key}

    def get_default_rdf_prefixes(self) -> Dict[str, str]:
        """
        Get the default RDF prefixes.

        Checks top-level rdfPrefixes first, then falls back to defaults section.

        Returns:
            Dictionary of prefix -> namespace URI mappings, or empty dict if none.
        """
        if self._rdf_prefixes:
            return dict(self._rdf_prefixes)
        prefixes: Dict[str, str] = self._defaults.get("rdfPrefixes", {})
        return prefixes

    def add_output_dataset(
        self,
        name: str,
        slug: str,
        location: str,
        fields: List[FieldSchema],
        description: Optional[str] = None,
        rdf_prefixes: Optional[Dict[str, str]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> DatasetMetadata:
        """
        Add a new output dataset to datasets.yaml.

        Args:
            name: Human-readable name.
            slug: Kebab-case identifier.
            location: File path for the output.
            fields: List of field schemas.
            description: Optional dataset description.
            rdf_prefixes: Optional RDF namespace prefix map.
            custom_properties: Optional custom/RDF properties to include.

        Returns:
            The newly created DatasetMetadata.

        Raises:
            DatasetValidationError: If a dataset with this slug already exists.
        """
        if self.find_dataset_by_slug(slug, "output"):
            raise DatasetValidationError(f"Output dataset with slug '{slug}' already exists")
        dataset_data: Dict[str, Any] = {
            "name": name,
            "slug": slug,
            "location": location,
            "fields": [_field_schema_to_dict(field) for field in fields],
        }
        if description is not None:
            dataset_data["description"] = description
        if rdf_prefixes is not None:
            dataset_data["rdfPrefixes"] = rdf_prefixes
        if custom_properties is not None:
            for key, value in custom_properties.items():
                dataset_data[key] = value
        self._data["outputs"].append(dataset_data)
        self._save()
        return self._parse_dataset(dataset_data, "output")

    def update_output_dataset(
        self,
        slug: str,
        fields: Optional[List[FieldSchema]] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        rdf_prefixes: Optional[Dict[str, str]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> DatasetMetadata:
        """
        Update an existing output dataset.

        Args:
            slug: The slug of the dataset to update.
            fields: Optional new field schema.
            location: Optional new location.
            description: Optional dataset description.
            rdf_prefixes: Optional RDF namespace prefix map.
            custom_properties: Optional custom/RDF properties to include.

        Returns:
            The updated DatasetMetadata.

        Raises:
            DatasetNotFoundError: If the dataset doesn't exist.
        """
        for i, dataset_data in enumerate(self._data["outputs"]):
            if dataset_data["slug"] == slug:
                if fields is not None:
                    dataset_data["fields"] = [_field_schema_to_dict(field) for field in fields]
                if location is not None:
                    dataset_data["location"] = location
                if description is not None:
                    dataset_data["description"] = description
                if rdf_prefixes is not None:
                    dataset_data["rdfPrefixes"] = rdf_prefixes
                if custom_properties is not None:
                    for key, value in custom_properties.items():
                        dataset_data[key] = value
                self._save()
                return self._parse_dataset(dataset_data, "output")

        raise DatasetNotFoundError(f"Output dataset with slug '{slug}' not found")

    def set_dataset_strict(self, slug: str, strict: bool, dataset_type: Optional[str] = None) -> None:
        """
        Set or remove strict mode for a dataset.

        Args:
            slug: The slug of the dataset to update.
            strict: If True, enable strict mode. If False, disable it.
            dataset_type: Optional filter by 'input' or 'output'. If None, searches both.

        Raises:
            DatasetNotFoundError: If the dataset doesn't exist.
        """
        search_types = ["input", "output"] if dataset_type is None else [dataset_type]

        for dtype in search_types:
            key = "inputs" if dtype == "input" else "outputs"
            for dataset_data in self._data.get(key, []):
                if dataset_data["slug"] == slug:
                    if strict:
                        dataset_data["strict"] = True
                    elif "strict" in dataset_data:
                        del dataset_data["strict"]
                    self._save()
                    return

        raise DatasetNotFoundError(f"Dataset with slug '{slug}' not found")

    def update_output_lineage(
        self,
        slug: str,
        lineage: LineageMetadata,
        content_hash: str,
        strict: bool = False,
        context: Optional[dict] = None,
        transformation_params: Optional[dict] = None,
        activity: Optional[Activity] = None,
    ) -> None:
        """
        Update lineage metadata for an output dataset.

        The timestamp is only updated when the content hash changes, preventing
        unnecessary updates when the data hasn't changed.

        In strict mode, validates that the lineage matches what would be written
        without modifying the file. In relaxed mode, updates the file with lineage.

        Args:
            slug: The slug of the output dataset to update.
            lineage: The lineage metadata to persist.
            content_hash: SHA256 hash of the DataFrame content.
            strict: If True, validate without modifying. If False, update the file.
            context: Optional execution context dict (backwards compat).
            transformation_params: Optional transformation parameters dict.
            activity: Optional PROV-O Activity for this output.

        Raises:
            DatasetNotFoundError: If the dataset doesn't exist.
            DatasetValidationError: In strict mode, if lineage differs from what's in the file.
        """
        from datetime import datetime

        # Find the output dataset
        dataset_idx = None
        for i, dataset_data in enumerate(self._data["outputs"]):
            if dataset_data["slug"] == slug:
                dataset_idx = i
                break

        if dataset_idx is None:
            raise DatasetNotFoundError(f"Output dataset with slug '{slug}' not found")

        # Get existing lineage data if present
        existing_lineage = self._data["outputs"][dataset_idx].get("lineage", {})
        existing_hash = existing_lineage.get("content_hash")

        # Determine if content has changed
        content_changed = existing_hash != content_hash

        # If content hasn't changed, skip the write entirely
        if not content_changed:
            return

        timestamp = datetime.now().isoformat()

        # Build lineage metadata to add (order: content_hash, created_at, sources)
        lineage_data: dict[str, Any] = {}
        lineage_data["content_hash"] = content_hash
        if timestamp:
            lineage_data["created_at"] = timestamp
        if lineage.sources:
            lineage_data["sources"] = [{"slug": src.slug} for src in lineage.sources]
        if context:
            # Convert script_path to relative when it's within the project
            if "script_path" in context:
                try:
                    rel = Path(context["script_path"]).resolve().relative_to(self.project_path)
                    if not str(rel).startswith(".."):
                        context = {**context, "script_path": rel.as_posix()}
                except ValueError:
                    pass  # Outside project_path, keep absolute
            lineage_data["context"] = context
        if transformation_params:
            lineage_data["transformation_params"] = transformation_params

        # PROV-O Activity (new)
        if activity is not None:
            from dataclasses import replace as _replace

            # Relativize script_path without mutating the caller's object
            activity_to_write = activity
            if activity.script_path:
                try:
                    rel = Path(activity.script_path).resolve().relative_to(self.project_path)
                    if not str(rel).startswith(".."):
                        activity_to_write = _replace(activity, script_path=rel.as_posix())
                except ValueError:
                    pass
            lineage_data["activity"] = self._activity_to_dict(activity_to_write)

        # Field derivations (new)
        field_derivations = lineage.field_derivations
        if field_derivations:
            lineage_data["field_derivations"] = self._field_derivations_to_list(field_derivations)

        # Create a copy of the data with updated lineage
        updated_data = self._data.copy()
        updated_data["outputs"] = [dict(d) for d in self._data["outputs"]]
        updated_data["outputs"][dataset_idx] = dict(self._data["outputs"][dataset_idx])

        # Add or update lineage in the copy
        if lineage_data:
            updated_data["outputs"][dataset_idx]["lineage"] = lineage_data

        # Write to temp file
        temp_fd, temp_path = tempfile.mkstemp(suffix=".yaml", prefix="datasets_", dir=self.project_path)

        try:
            with os.fdopen(temp_fd, "w") as f:
                _yaml.dump(updated_data, f)

            if strict:
                # In strict mode, check if files differ
                import filecmp

                if not filecmp.cmp(self.datasets_file, temp_path, shallow=False):
                    # Files differ - this is an error in strict mode
                    os.unlink(temp_path)
                    raise DatasetValidationError(
                        f"In strict mode, lineage metadata for '{slug}' would be updated in datasets.yaml. "
                        f"Expected lineage is already present in the file, but found differences."
                    )
                else:
                    # Files are the same - clean up temp file
                    os.unlink(temp_path)
            else:
                # In relaxed mode, replace the file
                os.replace(temp_path, self.datasets_file)
                # Reload the data
                self._load()

        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def get_absolute_path(self, location: str) -> Path:
        """
        Get the absolute path for a dataset location.

        Args:
            location: The location string from dataset metadata.

        Returns:
            Absolute path to the dataset file.
        """
        location_path = Path(location)
        if location_path.is_absolute():
            return location_path
        return (self.project_path / location_path).resolve()

    def fetch_from_url(
        self,
        dataset: DatasetMetadata,
        timeout: int = 30,
        force: bool = False,
        max_redirects: int = 10,
    ) -> Path:
        """
        Fetch a dataset from its source URL if available.

        .. deprecated::
            Use ``PluginRegistry.get().fetch(url, dest)`` instead.

        Args:
            dataset: The dataset metadata containing source URL.
            timeout: Request timeout in seconds.
            force: If True, fetch even if local file exists.
            max_redirects: Maximum number of redirects to follow (default: 10).

        Returns:
            Path to the local file (newly downloaded or existing).

        Raises:
            ValueError: If dataset has no source URL or no handler matches.
        """
        import warnings

        warnings.warn(
            "fetch_from_url is deprecated. Use PluginRegistry.get().fetch(url, dest) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        if not dataset.source or not dataset.source.location.data:
            raise ValueError(f"Dataset '{dataset.slug}' has no source URL")

        local_path = self.get_absolute_path(dataset.location)

        # Skip if file exists and not forcing
        if local_path.exists() and not force:
            logger.info("Using existing local file: %s", local_path)
            return local_path

        url = dataset.source.location.data

        from .handlers import HttpURLHandler, LocalFileHandler
        from .plugins import PluginRegistry

        registry = PluginRegistry.get(self.project_path)
        url_handler = registry.find_url_handler(url)

        if url_handler is None:
            raise ValueError(f"No URL handler found for '{url}'. Install a plugin that handles this URL scheme.")
        if isinstance(url_handler, LocalFileHandler):
            raise ValueError(f"No URL handler found for '{url}'. Install a plugin that handles this URL scheme.")

        local_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(url_handler, HttpURLHandler):
            headers: dict[str, str] = {}
            for auth in registry.get_auth_providers():
                headers = auth.authenticate(url, headers, dataset)
            with url_handler.open(url, "rb", headers=headers) as src, open(local_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            return local_path

        return registry.fetch(url, local_path)
