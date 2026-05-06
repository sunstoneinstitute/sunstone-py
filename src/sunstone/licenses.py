"""
License tracking with SPDX validation and compatibility enforcement.

Provides an embedded list of common research-data licenses, a property
model (attribution / ShareAlike / NonCommercial / public-domain), a
rules-based compatibility engine, and a ``LicenseCompatibilityError``
that surfaces actionable conflict descriptions at write time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .exceptions import SunstoneError


class LicenseCompatibilityError(SunstoneError):
    """Raised when a target license is incompatible with one or more source licenses."""

    pass


@dataclass(frozen=True)
class LicenseProperties:
    """Properties of a license that drive compatibility rules.

    These properties are sufficient to encode the compatibility behavior of
    every license in the embedded registry. A license missing from the
    registry has unknown properties and is treated conservatively.
    """

    spdx: str
    """SPDX identifier (e.g., 'CC-BY-4.0')."""

    name: str
    """Human-readable license name."""

    public_domain: bool = False
    """True for CC0, PDDL, and similar — compatible with everything."""

    attribution: bool = False
    """True if downstream users must credit the source (CC-BY family, ODC-By, ODbL)."""

    share_alike: bool = False
    """True if derivatives must use the same license (CC-BY-SA, ODbL, CC-BY-NC-SA)."""

    non_commercial: bool = False
    """True if commercial use is forbidden (CC-BY-NC, CC-BY-NC-SA, CC-BY-NC-3.0-IGO)."""

    family: Optional[str] = None
    """Identifier for the ShareAlike family. Only same-family SA licenses are mutually compatible."""

    aliases: tuple[str, ...] = ()
    """Alternate identifiers (case-insensitive) that map to this license."""


# ---------------------------------------------------------------------------
# Embedded license registry
#
# This is intentionally focused on the licenses the issue mentions —
# CC, ODC, CC0/PDDL, plus a couple of LicenseRef- entries. New licenses
# should be added by appending to this list.
# ---------------------------------------------------------------------------

_REGISTRY_ENTRIES: tuple[LicenseProperties, ...] = (
    # Public-domain dedications
    LicenseProperties(
        spdx="CC0-1.0",
        name="Creative Commons Zero v1.0 Universal",
        public_domain=True,
    ),
    LicenseProperties(
        spdx="PDDL-1.0",
        name="Open Data Commons Public Domain Dedication and Licence 1.0",
        public_domain=True,
    ),
    LicenseProperties(
        spdx="LicenseRef-US-PD",
        name="United States Public Domain (work of US Federal Government)",
        public_domain=True,
    ),
    # Attribution-only
    LicenseProperties(
        spdx="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International",
        attribution=True,
    ),
    LicenseProperties(
        spdx="CC-BY-3.0",
        name="Creative Commons Attribution 3.0 Unported",
        attribution=True,
    ),
    LicenseProperties(
        spdx="ODC-By-1.0",
        name="Open Data Commons Attribution License 1.0",
        attribution=True,
    ),
    LicenseProperties(
        spdx="LicenseRef-OGL-3.0",
        name="UK Open Government Licence v3.0",
        attribution=True,
    ),
    # Attribution + ShareAlike
    LicenseProperties(
        spdx="CC-BY-SA-4.0",
        name="Creative Commons Attribution-ShareAlike 4.0 International",
        attribution=True,
        share_alike=True,
        family="cc-by-sa-4",
    ),
    LicenseProperties(
        spdx="CC-BY-SA-3.0",
        name="Creative Commons Attribution-ShareAlike 3.0 Unported",
        attribution=True,
        share_alike=True,
        family="cc-by-sa-3",
    ),
    LicenseProperties(
        spdx="ODbL-1.0",
        name="Open Data Commons Open Database License 1.0",
        attribution=True,
        share_alike=True,
        family="odbl-1",
    ),
    # Attribution + NonCommercial
    LicenseProperties(
        spdx="CC-BY-NC-4.0",
        name="Creative Commons Attribution-NonCommercial 4.0 International",
        attribution=True,
        non_commercial=True,
    ),
    LicenseProperties(
        spdx="CC-BY-NC-3.0-IGO",
        name="Creative Commons Attribution-NonCommercial 3.0 IGO",
        attribution=True,
        non_commercial=True,
    ),
    # Attribution + NonCommercial + ShareAlike
    LicenseProperties(
        spdx="CC-BY-NC-SA-4.0",
        name="Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
        attribution=True,
        share_alike=True,
        non_commercial=True,
        family="cc-by-nc-sa-4",
    ),
    LicenseProperties(
        spdx="CC-BY-NC-SA-3.0",
        name="Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported",
        attribution=True,
        share_alike=True,
        non_commercial=True,
        family="cc-by-nc-sa-3",
    ),
)


_BY_LOWER: dict[str, LicenseProperties] = {}
for _entry in _REGISTRY_ENTRIES:
    _BY_LOWER[_entry.spdx.lower()] = _entry
    for _alias in _entry.aliases:
        _BY_LOWER[_alias.lower()] = _entry


def known_licenses() -> list[LicenseProperties]:
    """Return all licenses in the embedded registry, sorted by SPDX identifier."""
    return sorted(_REGISTRY_ENTRIES, key=lambda e: e.spdx.lower())


def is_valid_spdx(identifier: str) -> bool:
    """True if *identifier* is a known SPDX id, a known LicenseRef-, or any LicenseRef-* form.

    LicenseRef-* identifiers are accepted as user-defined per the SPDX spec —
    they cannot be used in property-based compatibility rules unless they
    appear in the embedded registry.
    """
    if not identifier:
        return False
    if identifier.lower() in _BY_LOWER:
        return True
    return identifier.startswith("LicenseRef-") and len(identifier) > len("LicenseRef-")


def get_properties(identifier: str) -> Optional[LicenseProperties]:
    """Return :class:`LicenseProperties` for *identifier*, or ``None`` if unknown.

    Returns ``None`` for valid LicenseRef-* identifiers that are not in the
    embedded registry — callers must decide how to treat unknown licenses.
    """
    return _BY_LOWER.get(identifier.lower()) if identifier else None


# ---------------------------------------------------------------------------
# Compatibility checking
# ---------------------------------------------------------------------------


@dataclass
class LicenseCompatibilityResult:
    """Outcome of a compatibility check between source licenses and a target license."""

    target: str
    """The proposed target license identifier."""

    sources: list[str] = field(default_factory=list)
    """Source license identifiers that were considered (deduplicated)."""

    compatible: bool = True
    """True if the target license satisfies every source's downstream requirements."""

    conflicts: list[str] = field(default_factory=list)
    """Human-readable conflict descriptions; empty when ``compatible`` is True."""

    suggestions: list[str] = field(default_factory=list)
    """Suggested target licenses that would resolve the conflicts (best-effort)."""

    unknown_sources: list[str] = field(default_factory=list)
    """Source identifiers not present in the registry (e.g., user-defined LicenseRef-*)."""

    unknown_target: bool = False
    """True if the target identifier is not in the registry."""


def _dedupe_preserving_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _check_pair(source: LicenseProperties, target: LicenseProperties) -> Optional[str]:
    """Return a conflict description if *target* fails to satisfy *source*; else ``None``."""
    if source.public_domain:
        return None
    if source.share_alike:
        if not target.share_alike or source.family != target.family:
            return (
                f"{source.spdx} is ShareAlike: derivatives must be released under "
                f"{source.spdx} (or a same-family ShareAlike license), not {target.spdx}"
            )
    if source.non_commercial and not target.non_commercial:
        return f"{source.spdx} is NonCommercial: derivatives must also be NonCommercial, not {target.spdx}"
    if source.attribution and not (target.attribution or target.share_alike):
        return (
            f"{source.spdx} requires attribution: derivatives must use a license "
            f"that preserves attribution, not {target.spdx}"
        )
    return None


def _suggest_targets(sources: list[LicenseProperties]) -> list[str]:
    """Suggest target licenses that could satisfy every known source."""
    candidates: list[str] = []
    for entry in known_licenses():
        if all(_check_pair(src, entry) is None for src in sources):
            candidates.append(entry.spdx)
    return candidates


def check_compatibility(
    source_licenses: Iterable[str],
    target_license: str,
) -> LicenseCompatibilityResult:
    """Check whether *target_license* is compatible with every license in *source_licenses*.

    Unknown licenses (valid LicenseRef-* identifiers not in the registry, or
    unrecognized identifiers) are reported on the result but do not raise. The
    caller is responsible for deciding whether to treat unknowns as a failure.
    """
    deduped_sources = _dedupe_preserving_order(source_licenses)
    result = LicenseCompatibilityResult(target=target_license, sources=deduped_sources)

    target_props = get_properties(target_license)
    if target_props is None:
        result.unknown_target = True

    known_source_props: list[LicenseProperties] = []
    for source_id in deduped_sources:
        props = get_properties(source_id)
        if props is None:
            result.unknown_sources.append(source_id)
            continue
        known_source_props.append(props)

    if target_props is None:
        # Without target properties we cannot apply the rules engine. Surface as a
        # conflict so callers don't silently pass unknown targets.
        if known_source_props:
            result.compatible = False
            result.conflicts.append(
                f"Target license {target_license!r} is not in the embedded registry; "
                f"compatibility cannot be verified against known sources "
                f"{[p.spdx for p in known_source_props]!r}."
            )
        return result

    for src_props in known_source_props:
        conflict = _check_pair(src_props, target_props)
        if conflict:
            result.compatible = False
            result.conflicts.append(conflict)

    if not result.compatible:
        result.suggestions = _suggest_targets(known_source_props)

    return result


# ---------------------------------------------------------------------------
# Most-restrictive license picker
# ---------------------------------------------------------------------------


def _restrictiveness(props: LicenseProperties) -> tuple[int, int, int, int, str]:
    """Sort key — higher tuple = more restrictive."""
    return (
        1 if props.share_alike else 0,
        1 if props.non_commercial else 0,
        1 if props.attribution else 0,
        0 if props.public_domain else 1,
        props.spdx.lower(),
    )


def get_most_restrictive_license(licenses: Iterable[str]) -> Optional[str]:
    """Return the SPDX identifier of the most restrictive license in *licenses*.

    Returns ``None`` if *licenses* is empty or contains no known licenses.
    Useful for auto-suggesting an output license for a derived dataset.
    """
    known: list[LicenseProperties] = []
    for ident in licenses:
        props = get_properties(ident)
        if props is not None:
            known.append(props)
    if not known:
        return None
    return max(known, key=_restrictiveness).spdx
