"""Polars write facades.

Writes a polars-payload Asset through the engine-aware BuiltinFormatHandler
(bypassing ParquetFormatHandler so all formats go through the polars engine),
then registers the output and persists lineage to ``datasets.lock.yaml`` —
mirroring the pandas sibling (``sunstone.pandas.write``).
"""

from __future__ import annotations

import hashlib
import io as _io
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from sunstone.datasets import DatasetsManager
from sunstone.exceptions import LineageWarning, StrictModeError

if TYPE_CHECKING:
    from .core import DataFrame


def _emit_derivation_warning_if_needed(asset: Any, slug: str) -> None:
    """Emit a one-shot LineageWarning when the asset is derived but has no Activity."""
    lin = asset.metadata.lineage
    source_slugs = {s.slug for s in lin.sources}
    is_derived = len(source_slugs) > 1 or (bool(source_slugs) and slug not in source_slugs)
    if is_derived and lin.activity is None:
        warnings.warn(
            f"Output '{slug}' written from a polars DataFrame whose derivation chain has no "
            "Activity records. Operation-level lineage is not yet tracked for the polars engine. See Spec 2.",
            LineageWarning,
            stacklevel=4,
        )


def _infer_polars_dtype(dtype: Any) -> str:
    """Map a polars dtype to a dataset type string.

    Matches on the base dtype name (e.g. ``Datetime(us, None)`` → ``Datetime``)
    so parameterised/nested dtypes don't accidentally match substrings.
    """
    type_base = str(dtype).split("(")[0]
    if type_base.startswith(("Int", "UInt")):
        return "integer"
    elif type_base.startswith("Float"):
        return "number"
    elif type_base == "Boolean":
        return "boolean"
    elif type_base in ("Date", "Datetime", "Time", "Duration"):
        return "datetime"
    return "string"


def _build_polars_field_schema(df: "DataFrame") -> "list[Any]":
    """Build a FieldSchema list merging explicit field metadata with dtype inference.

    Explicit metadata set via ``df.set_field_metadata(col, ...)`` takes precedence;
    dtype inference is used as a fallback for columns without explicit metadata.
    This mirrors the pandas sibling's ``_build_field_schema`` merge precedence.
    """
    from sunstone.lineage import FieldSchema

    fields = []
    for col_name, dtype in zip(df.data.columns, df.data.dtypes):
        explicit = df.metadata.field_metadata.get(col_name)
        if explicit:
            if explicit.type is None:
                fields.append(
                    FieldSchema(
                        name=explicit.name,
                        type=_infer_polars_dtype(dtype),
                        description=explicit.description,
                        unit=explicit.unit,
                        source=explicit.source,
                        constraints=explicit.constraints,
                    )
                )
            else:
                fields.append(explicit)
        else:
            fields.append(FieldSchema(name=col_name, type=_infer_polars_dtype(dtype)))
    return fields


def _enforce_license_compatibility(
    manager: DatasetsManager,
    dataset_slug: str,
    target_license: Optional[str],
) -> None:
    """Check the proposed write against source licenses.

    Mirrors the pandas sibling's ``WriteMixin._enforce_license_compatibility``.
    When no target license is declared, auto-derives one from the source licenses
    and persists it to the output dataset.

    Raises :class:`~sunstone.licenses.LicenseCompatibilityError` if the target
    license is incompatible with any source license.
    """
    from sunstone.licenses import (
        LicenseCompatibilityError,
        check_compatibility,
        derive_compatible_target,
    )
    from sunstone.session import get_session

    source_slugs = get_session().current_source_slugs()
    source_licenses: list[str] = []
    for slug in source_slugs:
        ds = manager.find_dataset_by_slug(slug)
        if ds is None:
            continue
        if ds.dataset_type == "input" and ds.source is not None and ds.source.license:
            source_licenses.append(ds.source.license)
        elif ds.dataset_type == "output":
            eff = manager.effective_license_for(slug)
            if eff:
                source_licenses.append(eff)

    if not source_licenses:
        return

    if target_license is None:
        derived = derive_compatible_target(source_licenses)
        if derived is None:
            unique = sorted(set(source_licenses))
            raise LicenseCompatibilityError(
                f"Output '{dataset_slug}' has source datasets with licenses "
                f"{unique} but no compatible default license can be derived "
                f"(mutually incompatible or contains unknown identifiers). "
                f"Set 'license:' on the dataset, on a package, or pass "
                f"license= to the writer."
            )
        manager.update_output_dataset(slug=dataset_slug, license=derived)
        target_license = derived

    result = check_compatibility(source_licenses, target_license)
    if result.compatible:
        return

    message_lines = [f"License compatibility check failed for output '{dataset_slug}' (target: {target_license})."]
    message_lines.extend(f"  - {c}" for c in result.conflicts)
    if result.suggestions:
        message_lines.append("Suggested compatible target licenses: " + ", ".join(result.suggestions))
    if result.unknown_sources:
        message_lines.append("Unknown source licenses (not validated): " + ", ".join(result.unknown_sources))
    raise LicenseCompatibilityError("\n".join(message_lines))


def _write(
    df: "DataFrame",
    path: str,
    *,
    format: str,
    slug: str,
    name: str,
    license: Optional[str] = None,
    check_license: bool = True,
    **kwargs: Any,
) -> None:
    """Central write helper for polars write facades.

    Registers the output dataset if needed, writes bytes via the polars-aware
    BuiltinFormatHandler (bypassing ParquetFormatHandler so all three formats
    go through the polars engine path), computes a content hash, and persists
    lineage to ``datasets.lock.yaml``.

    Mirrors the pandas sibling (``sunstone.pandas.write.WriteMixin``) including:
    - Strict-mode enforcement (raises :class:`~sunstone.exceptions.StrictModeError`
      when the output is unregistered and strict mode is on).
    - Full dataset-level metadata (``description``, ``rdf_prefixes``,
      ``custom_properties``, ``license``) forwarded to ``add_output_dataset``.
    - Explicit per-column metadata from ``df.metadata.field_metadata`` merged
      ahead of dtype inference in the field schema.
    - License compatibility check (mirroring ``_enforce_license_compatibility``).
    """
    from sunstone.handlers import BuiltinFormatHandler
    from sunstone.plugins import PluginRegistry
    from sunstone.session import get_session

    # Stamp slug/name + engine onto the asset metadata before writing.
    asset = df.asset
    asset.metadata.slug = slug
    asset.metadata.name = name
    asset.metadata.lineage.engine = "polars"

    # Resolve project path from asset lineage (propagated during construction).
    project_path_str = asset.metadata.lineage.project_path
    project_path_resolved = Path(project_path_str) if project_path_str else Path.cwd()
    manager = DatasetsManager(project_path_resolved)

    # Find or auto-register the output dataset.
    dataset = manager.find_dataset_by_location(path, "output")

    if dataset is None:
        if df.strict_mode:
            raise StrictModeError(
                f"Output dataset at '{path}' not registered in datasets.yaml. "
                f"In strict mode, outputs must be pre-registered."
            )
        # Relaxed mode: auto-register with full dataset-level metadata.
        fields = _build_polars_field_schema(df)
        dataset = manager.add_output_dataset(
            name=name,
            slug=slug,
            location=path,
            fields=fields,
            description=df.metadata.description,
            rdf_prefixes=df.metadata.rdf_prefixes,
            custom_properties=df.metadata.custom_properties,
            license=license,
        )
    elif license is not None and dataset.license != license:
        # Persist explicit override on a pre-registered dataset.
        dataset = manager.update_output_dataset(slug=dataset.slug, license=license)

    # Warn when derived-without-activity (lineage gap). Emitted only once the
    # write is going to proceed — a strict-mode write that raised above must
    # not leave a misleading warning behind.
    _emit_derivation_warning_if_needed(asset, slug)

    if check_license:
        target_license = license or manager.effective_license_for(dataset.slug)
        _enforce_license_compatibility(manager, dataset.slug, target_license)

    # Write to a BytesIO buffer first so we can hash the bytes, then copy to
    # the actual file (avoids writing twice and avoids seeking limitations).
    absolute_path = manager.get_absolute_path(dataset.location)
    registry = PluginRegistry.get(manager.project_path)
    location_abs = str(absolute_path)

    handler = BuiltinFormatHandler()
    buf = _io.BytesIO()
    handler.write(asset, buf, format=format, path=location_abs, engine="polars", **kwargs)
    data_bytes = buf.getvalue()

    url_handler = registry.find_url_handler(location_abs)
    if url_handler is not None:
        with url_handler.open(location_abs, "wb") as stream:
            stream.write(data_bytes)
    else:
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(data_bytes)

    data_hash = "sha256:" + hashlib.sha256(data_bytes).hexdigest()

    # Flush session and persist lineage to datasets.lock.yaml.
    session = get_session()
    lineage_data = session.flush_to_output()

    effective_lineage = asset.metadata.lineage
    if not effective_lineage.sources and lineage_data.get("sources"):
        for src in lineage_data["sources"]:
            src_dataset = manager.find_dataset_by_slug(src["slug"])
            if src_dataset is not None:
                effective_lineage.add_source(src_dataset)

    manager.update_output_lineage(
        slug=dataset.slug,
        lineage=effective_lineage,
        data_hash=data_hash,
        strict=df.strict_mode,
        context=lineage_data.get("context"),
        transformation_params=lineage_data.get("transformation_params"),
        activity=lineage_data.get("_activity"),
    )
