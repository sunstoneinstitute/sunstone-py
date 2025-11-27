"""
Parser and manager for datasets.yaml files.
"""

import ipaddress
import logging
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin, urlparse

import requests
import yaml

from .exceptions import DatasetNotFoundError, DatasetValidationError
from .lineage import DatasetMetadata, FieldSchema, Source, SourceLocation

logger = logging.getLogger(__name__)


def _is_public_url(url: str) -> bool:
    """
    Validate that a URL points to a public (non-private) resource.

    This function prevents SSRF attacks by blocking:
    - Non-HTTP(S) schemes (e.g., file://, ftp://)
    - Private IP addresses (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
    - Localhost and loopback addresses
    - Link-local addresses (169.254.x.x)

    Args:
        url: The URL to validate.

    Returns:
        True if the URL points to a public resource, False otherwise.
    """
    try:
        parsed = urlparse(url)

        # Only allow HTTP and HTTPS schemes
        if parsed.scheme not in ("http", "https"):
            logger.warning("URL scheme '%s' not allowed (only http/https permitted)", parsed.scheme)
            return False

        # Ensure hostname is present
        if not parsed.hostname:
            logger.warning("URL has no hostname")
            return False

        # Resolve hostname to all IP addresses (IPv4 and IPv6) and check each
        try:
            addrinfos = socket.getaddrinfo(parsed.hostname, None)
            for addrinfo in addrinfos:
                sockaddr = addrinfo[4]
                ip = sockaddr[0]
                try:
                    ip_obj = ipaddress.ip_address(ip)
                except ValueError:
                    logger.warning(
                        "Invalid IP address resolved from hostname: %s (%s)",
                        parsed.hostname,
                        ip,
                    )
                    return False

                # Block private, loopback, and link-local addresses
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    logger.warning(
                        "URL hostname '%s' resolves to restricted IP address: %s",
                        parsed.hostname,
                        ip,
                    )
                    return False

        except socket.gaierror:
            logger.warning("Unable to resolve hostname: %s", parsed.hostname)
            return False

        return True

    except Exception as e:
        logger.warning("Error validating URL '%s': %s", url, e)
        return False


class DatasetsManager:
    """
    Manager for parsing and updating datasets.yaml files.

    This class handles reading, parsing, and updating dataset metadata
    from datasets.yaml files in Sunstone projects.
    """

    def __init__(self, project_path: Union[str, Path]):
        """
        Initialize the datasets manager.

        Args:
            project_path: Path to the project directory containing datasets.yaml.

        Raises:
            FileNotFoundError: If datasets.yaml doesn't exist in the project path.
        """
        self.project_path = Path(project_path).resolve()
        self.datasets_file = self.project_path / "datasets.yaml"

        if not self.datasets_file.exists():
            raise FileNotFoundError(f"datasets.yaml not found in {self.project_path}")

        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load and parse the datasets.yaml file."""
        with open(self.datasets_file, "r") as f:
            self._data = yaml.safe_load(f) or {}

        if "inputs" not in self._data:
            self._data["inputs"] = []
        if "outputs" not in self._data:
            self._data["outputs"] = []

    def _save(self) -> None:
        """Save the current data back to datasets.yaml."""
        with open(self.datasets_file, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)

    def _parse_source_location(self, loc_data: Dict[str, Any]) -> SourceLocation:
        """Parse source location data from YAML."""
        return SourceLocation(
            data=loc_data.get("data"),
            metadata=loc_data.get("metadata"),
            about=loc_data.get("about"),
        )

    def _parse_source(self, source_data: Dict[str, Any]) -> Source:
        """Parse source attribution data from YAML."""
        return Source(
            name=source_data["name"],
            location=self._parse_source_location(source_data["location"]),
            attributed_to=source_data["attributedTo"],
            acquired_at=source_data["acquiredAt"],
            acquisition_method=source_data["acquisitionMethod"],
            license=source_data["license"],
            updated=source_data.get("updated"),
        )

    def _parse_fields(self, fields_data: List[Dict[str, Any]]) -> List[FieldSchema]:
        """Parse field schema data from YAML."""
        return [
            FieldSchema(name=field["name"], type=field["type"], constraints=field.get("constraints"))
            for field in fields_data
        ]

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

        return DatasetMetadata(
            name=dataset_data["name"],
            slug=dataset_data["slug"],
            location=dataset_data["location"],
            fields=self._parse_fields(dataset_data["fields"]),
            source=source,
            publish=dataset_data.get("publish", False),
            dataset_type=dataset_type,
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

    def add_output_dataset(
        self, name: str, slug: str, location: str, fields: List[FieldSchema], publish: bool = False
    ) -> DatasetMetadata:
        """
        Add a new output dataset to datasets.yaml.

        Args:
            name: Human-readable name.
            slug: Kebab-case identifier.
            location: File path for the output.
            fields: List of field schemas.
            publish: Whether to publish this dataset.

        Returns:
            The newly created DatasetMetadata.

        Raises:
            DatasetValidationError: If a dataset with this slug already exists.
        """
        # Check if slug already exists
        if self.find_dataset_by_slug(slug, "output"):
            raise DatasetValidationError(f"Output dataset with slug '{slug}' already exists")

        # Create the dataset entry
        dataset_data = {
            "name": name,
            "slug": slug,
            "location": location,
            "publish": publish,
            "fields": [
                {
                    "name": field.name,
                    "type": field.type,
                    **({"constraints": field.constraints} if field.constraints else {}),
                }
                for field in fields
            ],
        }

        # Add to outputs
        self._data["outputs"].append(dataset_data)

        # Save changes
        self._save()

        return self._parse_dataset(dataset_data, "output")

    def update_output_dataset(
        self, slug: str, fields: Optional[List[FieldSchema]] = None, location: Optional[str] = None
    ) -> DatasetMetadata:
        """
        Update an existing output dataset.

        Args:
            slug: The slug of the dataset to update.
            fields: Optional new field schema.
            location: Optional new location.

        Returns:
            The updated DatasetMetadata.

        Raises:
            DatasetNotFoundError: If the dataset doesn't exist.
        """
        for i, dataset_data in enumerate(self._data["outputs"]):
            if dataset_data["slug"] == slug:
                if fields is not None:
                    dataset_data["fields"] = [
                        {
                            "name": field.name,
                            "type": field.type,
                            **({"constraints": field.constraints} if field.constraints else {}),
                        }
                        for field in fields
                    ]
                if location is not None:
                    dataset_data["location"] = location

                self._save()
                return self._parse_dataset(dataset_data, "output")

        raise DatasetNotFoundError(f"Output dataset with slug '{slug}' not found")

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

        Args:
            dataset: The dataset metadata containing source URL.
            timeout: Request timeout in seconds.
            force: If True, fetch even if local file exists.
            max_redirects: Maximum number of redirects to follow (default: 10).

        Returns:
            Path to the local file (newly downloaded or existing).

        Raises:
            ValueError: If dataset has no source URL or URL is not allowed.
            requests.RequestException: If the fetch fails.
        """
        if not dataset.source or not dataset.source.location.data:
            raise ValueError(f"Dataset '{dataset.slug}' has no source URL")

        local_path = self.get_absolute_path(dataset.location)

        # Skip if file exists and not forcing
        if local_path.exists() and not force:
            logger.info("Using existing local file: %s", local_path)
            return local_path

        url = dataset.source.location.data

        # Validate URL points to public resource to prevent SSRF attacks
        if not _is_public_url(url):
            raise ValueError(
                f"URL '{url}' is not allowed. Only HTTP/HTTPS URLs pointing to public internet addresses are permitted."
            )

        logger.info("Fetching dataset from URL: %s", url)

        try:
            # Disable automatic redirects and handle them manually to prevent SSRF bypass
            # An attacker could use a public URL that redirects to a private IP
            current_url = url
            response = requests.get(current_url, timeout=timeout, allow_redirects=False)
            redirect_count = 0

            while response.is_redirect and redirect_count < max_redirects:
                redirect_url = response.headers.get("Location")
                if not redirect_url:
                    raise ValueError("Redirect response without Location header")

                # Resolve relative URLs against the current URL
                redirect_url = urljoin(current_url, redirect_url)

                # Validate the redirect target URL for SSRF protection
                if not _is_public_url(redirect_url):
                    raise ValueError(
                        f"Redirect URL '{redirect_url}' is not allowed. Only HTTP/HTTPS URLs "
                        "pointing to public internet addresses are permitted."
                    )

                logger.info("Following redirect to: %s", redirect_url)
                current_url = redirect_url
                response = requests.get(current_url, timeout=timeout, allow_redirects=False)
                redirect_count += 1

            if response.is_redirect:
                raise ValueError(f"Too many redirects (max: {max_redirects})")

            response.raise_for_status()

            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # Save to local file
            with open(local_path, "wb") as f:
                f.write(response.content)

            logger.info("✓ Successfully saved to %s (%d bytes)", local_path, len(response.content))
            return local_path

        except requests.Timeout:
            logger.error("Request timed out after %d seconds", timeout)
            raise
        except requests.RequestException as e:
            logger.error("Failed to fetch from URL: %s", e)
            raise
