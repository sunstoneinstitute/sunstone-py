"""CSVW sidecar support — read/write helpers used by ``BuiltinFormatHandler``.

The implementation is intentionally JSON-only: CSVW sidecar files are
plain JSON-LD documents and the third-party ``csvw`` library is not
required. The ``available()`` helper exists so future work could opt
into the richer library without breaking callers.

This is a private module; no public API guarantees.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .exceptions import CSVWSidecarError
from .lineage import FieldSchema, Metadata
from .plugins import SidecarResource, URLHandler  # type: ignore[attr-defined]


logger = logging.getLogger(__name__)


def available() -> bool:
    """Return True if CSVW sidecar support is available.

    Always True today — sidecar I/O is plain JSON-LD and needs no third-party
    library. Kept as a public hook so handlers and tests can degrade
    gracefully if a future revision moves to the ``csvw`` library.
    """
    return True


# Standard csvw / W3C properties handled directly. Anything else on the
# table dict that contains ":" (RDF-style) is treated as a custom property.
_TABLE_CORE_KEYS = frozenset(
    {
        "url",
        "tableSchema",
        "dialect",
        "@id",
        "@type",
        "@context",
        "tables",  # if someone passed a TableGroup-shaped dict; handled at caller
        "dc:description",  # already mapped to Metadata.description
        "dct:description",  # already mapped to Metadata.description
    }
)


def csvw_to_metadata(table: dict) -> Metadata:
    """Map a CSVW table description (a dict, as produced by the csvw
    library's ``Table.asdict()`` or by direct JSON load) into a sunstone
    ``Metadata`` object.

    Mapping:

    - ``dc:description`` (or ``dct:description``) → ``Metadata.description``
    - ``tableSchema.columns[*].name`` → ``FieldSchema.name``
    - ``tableSchema.columns[*].dc:description`` (or ``dct:``) → ``FieldSchema.description``
    - ``tableSchema.columns[*].datatype`` → ``FieldSchema.type`` (string form;
      not used to drive read dtypes — see issue #56)
    - any non-core RDF-shaped key (``ns:term``) on the table dict is added
      to ``Metadata.custom_properties``

    Returns an empty ``Metadata()`` when the table has no recognizable
    fields.
    """
    description = table.get("dct:description") or table.get("dc:description")

    schema = table.get("tableSchema") or {}
    columns = schema.get("columns") or []

    field_metadata: dict[str, FieldSchema] = {}
    for col in columns:
        name = col.get("name")
        if not name:
            continue
        col_desc = col.get("dct:description") or col.get("dc:description")
        datatype_raw = col.get("datatype")
        if isinstance(datatype_raw, dict):
            datatype = datatype_raw.get("base")
        else:
            datatype = datatype_raw
        field_metadata[str(name)] = FieldSchema(
            name=str(name),
            type=str(datatype) if datatype is not None else None,
            description=str(col_desc) if col_desc is not None else None,
        )

    custom: dict[str, Any] = {k: v for k, v in table.items() if k not in _TABLE_CORE_KEYS and ":" in k}

    return Metadata(
        description=description,
        field_metadata=field_metadata,
        custom_properties=custom or None,
    )


def metadata_to_csvw_table(data_path: Path, metadata: Metadata) -> dict:
    """Inverse of :func:`csvw_to_metadata`. Build a single CSVW table
    description (dict) describing the CSV at ``data_path`` according to
    the given ``Metadata``.

    The returned dict is suitable for use as one entry inside a
    ``TableGroup``'s ``tables`` list, or as the body of a per-CSV
    sidecar document.

    Notes:

    - The ``url`` key is always set using POSIX-style separators (CSVW
      requires forward slashes; Windows backslashes are not portable).
    - Only fields present in ``metadata.field_metadata`` are emitted.
      Columns inferred at write time but not annotated are not added —
      caller is expected to merge inferred and explicit field metadata
      before calling this.
    """
    table: dict = {
        "url": _as_posix(data_path),
    }
    if metadata.description:
        table["dct:description"] = metadata.description

    columns: list[dict] = []
    for name, fs in metadata.field_metadata.items():
        col: dict = {"name": name}
        if fs.type is not None:
            col["datatype"] = fs.type
        if fs.description is not None:
            col["dct:description"] = fs.description
        columns.append(col)
    table["tableSchema"] = {"columns": columns}

    if metadata.custom_properties:
        for k, v in metadata.custom_properties.items():
            if k in _TABLE_CORE_KEYS:
                continue
            table[k] = v

    return table


def _as_posix(path: Path | str) -> str:
    """Return a POSIX-style path string suitable for use in CSVW ``url``
    fields (forward slashes regardless of OS)."""
    if isinstance(path, Path):
        return path.as_posix()
    return PurePosixPath(str(path).replace("\\", "/")).as_posix()


# Tier-1: per-CSV strict-name candidates. Lookup is by suffix
# substitution on the data file name. The W3C CSVW convention is to
# append ``-metadata.json`` to the FULL CSV filename (so ``out.csv``
# becomes ``out.csv-metadata.json``).
_TIER1_NAME_TEMPLATES: tuple[str, ...] = (
    "{name}-metadata.json",  # canonical W3C: foo.csv -> foo.csv-metadata.json
    "{stem}-metadata.json",  # alternate:     foo.csv -> foo-metadata.json
    "{stem}.csvm.json",  # sunstone:      foo.csv -> foo.csvm.json
)

# Tier-2: multi-CSV bare-name candidates in the data file's directory.
_TIER2_NAMES: tuple[str, ...] = ("csvm.json", "metadata.json")


def _csvw_signature_ok(doc: object) -> bool:
    """Heuristic CSVW-ness check.

    The csvw library's parser is permissive (warns on unknown fields
    rather than raising). We use a structural check instead: the
    document must declare ``@context`` referring to the CSVW namespace
    AND have either ``tableSchema`` (single table) or a non-empty
    ``tables`` list.

    The @context match uses a substring check for "csvw" rather than
    equality with the W3C namespace URI. This is intentional: the check is
    a heuristic gate, not a conformance check. False negatives (rejecting
    valid CSVW) would be more damaging than false positives, since
    ``_table_for_data_path`` will return None for any structurally
    malformed document anyway.
    """
    if not isinstance(doc, dict):
        return False
    context = doc.get("@context")
    if context is None:
        return False
    # @context can be a string, a list, or an object — flatten to a set
    # of strings for membership checking.
    if isinstance(context, str):
        ctx_strings = {context}
    elif isinstance(context, list):
        ctx_strings = {c for c in context if isinstance(c, str)}
    elif isinstance(context, dict):
        ctx_strings = {context.get("@vocab", "")}
    else:
        ctx_strings = set()
    if not any("csvw" in c for c in ctx_strings):
        return False
    return "tableSchema" in doc or bool(doc.get("tables"))


def _table_for_data_path(doc: dict, data_path: Path, sidecar_dir: Path | None = None) -> dict | None:
    """From a parsed CSVW document (single-table or table-group), return
    the table dict whose ``url`` matches ``data_path``, or None.

    Matching is by basename, absolute POSIX path, and (when ``sidecar_dir``
    is given) by POSIX-relative-to-sidecar form."""
    target_name = data_path.name
    target_posix = _as_posix(data_path)
    target_rel: str | None = None
    if sidecar_dir is not None:
        try:
            target_rel = _as_posix(data_path.relative_to(sidecar_dir))
        except ValueError:
            target_rel = None

    def candidates_match(url: str) -> bool:
        # Normalize the stored URL to POSIX form before comparison so that
        # sidecars written on Windows (where ``str(path)`` produces backslashes)
        # still match against POSIX-canonical targets.
        url_posix = _as_posix(url)
        return (
            url_posix == target_name
            or url_posix == target_posix
            or (target_rel is not None and url_posix == target_rel)
        )

    # Single-table sidecar
    if "tableSchema" in doc:
        url = doc.get("url")
        if url is not None and candidates_match(url):
            return doc
        return None

    # Multi-table sidecar
    table: dict
    for table in doc.get("tables") or []:
        url = table.get("url")
        if url is not None and candidates_match(url):
            return table

    return None


def _is_local_path(path: Path) -> bool:
    """Heuristic: is ``path`` resolvable on the local filesystem?

    Uses ``urlparse(path).scheme`` — empty/file scheme or single-letter
    Windows drive letter is treated as local. Paths with a scheme like
    ``gs://`` / ``s3://`` are non-local.
    """
    s = str(path)
    parsed = urlparse(s)
    if parsed.scheme in ("", "file"):
        return True
    if len(parsed.scheme) == 1 and parsed.scheme.isalpha():
        return True
    return False


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via temp + os.replace.

    The temp file lives in the same directory so the rename is
    cross-device-safe. On any failure during the write, the temp file
    is removed and the original (if any) is left untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def upsert_table_in_sidecar(
    sidecar_path: Path,
    data_path: Path,
    table_dict: dict,
    url_handler: URLHandler,
) -> None:
    """Read-modify-write the sidecar at ``sidecar_path`` so that it
    contains exactly one table entry for ``data_path`` (replacing any
    existing entry; preserving entries for other CSVs).

    Atomicity: for local-filesystem paths the write goes to a temporary
    file in the same directory and is then ``os.replace``'d into place
    (atomic on POSIX, atomic-enough on NTFS). For non-local paths
    (resolved via the URLHandler), atomic rename is not available — the
    file is overwritten directly. CSVW sidecars are predominantly a
    local-filesystem convention, so this is acceptable.

    Raises ``CSVWSidecarError`` if ``sidecar_path`` exists but is not a
    valid CSVW document (refuses to clobber unrelated files).
    """
    # Read existing contents (if any)
    existing_text = _open_text_via_handler(url_handler, sidecar_path)
    doc: dict[str, Any]
    if existing_text is None:
        doc = {
            "@context": "http://www.w3.org/ns/csvw",
            "tables": [],
        }
    else:
        try:
            doc = json.loads(existing_text)
        except json.JSONDecodeError as e:
            raise CSVWSidecarError(
                f"Refusing to overwrite '{sidecar_path}': existing file is not "
                f"valid JSON ({e}). If you intended to overwrite, delete the "
                f"file first."
            ) from e
        if not _csvw_signature_ok(doc):
            raise CSVWSidecarError(
                f"Refusing to overwrite '{sidecar_path}': existing file is not "
                f"a valid CSVW document. If you intended to overwrite, delete "
                f"the file first."
            )

        # Normalize single-table form -> table-group form so we always
        # write the same shape on disk.
        if "tableSchema" in doc and "tables" not in doc:
            single: dict[str, Any] = dict(doc)
            single.pop("@context", None)
            doc = {
                "@context": doc.get("@context", "http://www.w3.org/ns/csvw"),
                "tables": [single],
            }

    # Normalize the table_dict url to be relative to the sidecar location.
    # metadata_to_csvw_table may receive an absolute Path and produce an
    # absolute url — normalise it to a path relative to the sidecar's
    # parent directory (CSVW requires relative URLs).
    sidecar_dir = sidecar_path.parent
    try:
        rel = data_path.relative_to(sidecar_dir)
        normalised_url = _as_posix(rel)
    except ValueError:
        # data_path is not under the sidecar dir; fall back to basename
        normalised_url = data_path.name
    table_dict = dict(table_dict)
    table_dict["url"] = normalised_url

    # Replace or append the entry for data_path. Use _table_for_data_path
    # so the matching is symmetric with find_sidecar's read path
    # (basename, absolute POSIX, OR relative-from-sidecar-dir).
    tables: list[dict[str, Any]] = doc.setdefault("tables", [])
    target_table = _table_for_data_path({"tables": tables}, data_path, sidecar_dir=sidecar_dir)
    if target_table is not None:
        idx = tables.index(target_table)
        tables[idx] = table_dict
    else:
        tables.append(table_dict)

    # Serialize once before touching disk so a serialization failure
    # doesn't leave a half-written file.
    serialized = json.dumps(doc, indent=2, ensure_ascii=False)

    if _is_local_path(sidecar_path):
        _atomic_write_text(sidecar_path, serialized)
    else:
        # Non-local: best-effort overwrite via the URL handler
        with url_handler.open(str(sidecar_path), "w") as f:
            f.write(serialized)


# RDF property URI used to point a CSV resource at its CSVW sidecar in
# datapackage.json. Tracked in rdf-registry#6 for promotion to a
# registry-managed term.
CSVW_METADATA_PROPERTY = "https://sunstone.institute/rdf/vocab#csvwMetadata"


def _candidate_sidecar_paths(data_path: Path) -> list[Path]:
    """All on-disk candidate sidecar paths for ``data_path``, in
    discovery order: tier-1 (per-CSV) then tier-2 (multi-CSV)."""
    parent = data_path.parent
    name = data_path.name
    stem = data_path.stem
    candidates = [parent / template.format(name=name, stem=stem) for template in _TIER1_NAME_TEMPLATES]
    candidates.extend(parent / n for n in _TIER2_NAMES)
    return candidates


def _read_sidecar_doc_lenient(path: Path) -> dict | None:
    """Read and parse a sidecar; return the doc dict if it's valid CSVW,
    else None. Used for enumeration where we ignore non-CSVW files."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    try:
        doc: dict = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not _csvw_signature_ok(doc):
        return None
    return doc


def _sidecar_referenced_csv_paths(sidecar_path: Path, doc: dict) -> set[Path]:
    """Return the set of CSV paths a sidecar references, resolved
    relative to the sidecar's directory."""
    parent = sidecar_path.parent
    refs: set[Path] = set()

    if "tableSchema" in doc:
        url = doc.get("url")
        if url:
            refs.add((parent / url).resolve())
    for table in doc.get("tables") or []:
        url = table.get("url")
        if url:
            refs.add((parent / url).resolve())
    return refs


def enumerate_sidecars_for(
    data_paths: list[Path],
    *,
    extra_sidecar_paths: Iterable[Path] = (),
) -> list[SidecarResource]:
    """Enumerate all CSVW sidecars covering any CSV in ``data_paths``.

    Discovery: for each data file, scans tier-1 and tier-2 candidate
    paths in its directory. Additionally, ``extra_sidecar_paths`` lets
    callers (e.g. the BuiltinFormatHandler) inject sidecars they know
    were written this run (for example, a user-specified shared csvm at
    a non-conventional name).

    Validation (Q8 — hard fail): every discovered sidecar must reference
    only CSVs in ``data_paths``. Any extra reference raises
    ``PackageValidationError``.

    TODO: optional auto-filtered csvm copies per package as an
    alternative to hard-fail. Disabled for now per explicit user
    choice. File a follow-up issue if/when this is needed.

    Returns a list of ``SidecarResource`` (one per unique sidecar file),
    each with the set of covered CSVs from ``data_paths`` and the
    cross-reference RDF property to attach to those CSVs in the
    datapackage.json.
    """
    from .exceptions import PackageValidationError

    data_path_originals: dict[Path, Path] = {p.resolve(): p for p in data_paths}
    data_path_set = set(data_path_originals.keys())
    sidecar_to_covers: dict[Path, set[Path]] = {}
    sidecar_originals: dict[Path, Path] = {}  # resolved -> original

    def _consider(sidecar_path: Path, doc: dict) -> None:
        # Record which package CSVs this sidecar covers
        refs = _sidecar_referenced_csv_paths(sidecar_path, doc)
        covered_resolved = refs & data_path_set
        if not covered_resolved:
            return  # sidecar exists but doesn't cover any package CSV
        # Validate: refs must be a subset of the package
        extras = refs - data_path_set
        if extras:
            extra_names = sorted(p.name for p in extras)
            raise PackageValidationError(
                f"Sidecar '{sidecar_path}' references CSVs not in this "
                f"package: {', '.join(extra_names)}. Either remove the entry "
                f"from the sidecar, include those CSVs in the package, or "
                f"use a different sidecar for this package."
            )
        resolved = sidecar_path.resolve()
        sidecar_to_covers.setdefault(resolved, set()).update(covered_resolved)
        sidecar_originals.setdefault(resolved, sidecar_path)

    seen_sidecars: set[Path] = set()

    for data_path in data_paths:
        for candidate in _candidate_sidecar_paths(data_path):
            r = candidate.resolve()
            if r in seen_sidecars:
                continue
            doc = _read_sidecar_doc_lenient(candidate)
            if doc is None:
                continue
            seen_sidecars.add(r)
            _consider(candidate, doc)

    for extra in extra_sidecar_paths:
        r = extra.resolve()
        if r in seen_sidecars:
            continue
        doc = _read_sidecar_doc_lenient(extra)
        if doc is None:
            # Caller said this exists but it isn't valid CSVW now —
            # surface as a structural failure so the package build
            # doesn't silently drop it.
            raise PackageValidationError(
                f"Expected CSVW sidecar '{extra}' is missing or not valid CSVW at package-build time."
            )
        seen_sidecars.add(r)
        _consider(extra, doc)

    return [
        SidecarResource(
            path=sidecar_originals[resolved_sidecar],
            covers=sorted(
                (data_path_originals[c] for c in covers_resolved),
                key=lambda p: p.as_posix(),
            ),
            cross_ref_property=CSVW_METADATA_PROPERTY,
        )
        for resolved_sidecar, covers_resolved in sorted(sidecar_to_covers.items(), key=lambda kv: kv[0].as_posix())
    ]


def _open_text_via_handler(url_handler: URLHandler, path: Path) -> str | None:
    """Open a file via the URLHandler in text mode and read it.

    Returns None if the file does not exist (treats FileNotFoundError as
    a miss). Re-raises other I/O errors.
    """
    try:
        with url_handler.open(str(path), "r") as f:
            return f.read()
    except FileNotFoundError:
        return None


def find_sidecar(
    data_path: Path,
    url_handler: URLHandler,
) -> tuple[Path, dict] | None:
    """Locate and parse a CSVW sidecar describing ``data_path``.

    Lookup tiers (first match wins per tier; tier 1 short-circuits tier 2):

    Tier 1 (per-CSV, strict naming — parse failures raise):
      - ``<data_path>.csv-metadata.json``
      - ``<stem>-metadata.json``
      - ``<data_path>.csvm.json``

    Tier 2 (multi-CSV, lenient naming — parse failures logged & skipped):
      - ``csvm.json``     (in the data file's directory)
      - ``metadata.json``

    Returns ``(sidecar_path, table_dict)`` where ``table_dict`` is the
    single ``csvw:Table`` description matching ``data_path``. Returns
    ``None`` if no sidecar covers this CSV.
    """
    parent = data_path.parent
    name = data_path.name
    stem = data_path.stem

    # Tier 1: strict naming
    for template in _TIER1_NAME_TEMPLATES:
        candidate = parent / template.format(name=name, stem=stem)
        text = _open_text_via_handler(url_handler, candidate)
        if text is None:
            continue
        # Strict: any failure to parse-as-CSVW raises
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            raise CSVWSidecarError(f"CSVW sidecar '{candidate}' is not valid JSON: {e}") from e
        if not _csvw_signature_ok(doc):
            raise CSVWSidecarError(
                f"CSVW sidecar '{candidate}' is not a valid CSVW document "
                f"(missing @context for csvw or tableSchema/tables)."
            )
        table = _table_for_data_path(doc, data_path, sidecar_dir=candidate.parent)
        if table is None:
            raise CSVWSidecarError(f"CSVW sidecar '{candidate}' does not contain a table for '{data_path.name}'.")
        return (candidate, table)

    # Tier 2: lenient naming
    for tier2_name in _TIER2_NAMES:
        candidate = parent / tier2_name
        text = _open_text_via_handler(url_handler, candidate)
        if text is None:
            continue
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            logger.info(
                "Sidecar candidate %s is not JSON; skipping (lenient name).",
                candidate,
            )
            continue
        if not _csvw_signature_ok(doc):
            logger.info(
                "Sidecar candidate %s is not a CSVW document; skipping (lenient name).",
                candidate,
            )
            continue
        # Found a parseable CSVW document; this file is authoritative for
        # the directory's multi-CSV metadata. Look for our table.
        table = _table_for_data_path(doc, data_path, sidecar_dir=candidate.parent)
        if table is not None:
            return (candidate, table)
        # File was authoritative but didn't cover us — return None.
        return None

    return None
