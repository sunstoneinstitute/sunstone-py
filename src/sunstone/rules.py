"""Rule registry: every lint/conformance rule with its RFC 2119 level and scope."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .conformance import ConformanceContext, Violation


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Level(str, Enum):
    MUST = "MUST"
    MUST_NOT = "MUST NOT"
    SHOULD = "SHOULD"
    MAY = "MAY"
    """Not checked; only used to label recommended keys in ``KEY_LEVELS``."""
    INFO = "INFO"


class Category(str, Enum):
    EXTRAS = "extras"
    PROVENANCE = "provenance"
    LINEAGE = "lineage"
    TYPES = "types"
    UNITS = "units"
    NAMING = "naming"
    DESCRIPTION = "description"
    METHODOLOGY = "methodology"
    CONFIG = "config"


@dataclass
class Rule:
    id: str
    level: Level
    category: Category
    scope: frozenset[str]
    title: str
    message: str
    fix: str
    grace: bool = False
    """True for MUST rules that are new or stricter in 1.20: a lint warning while ``ENFORCE_MUST`` is False (1.x)."""
    check: Optional[Callable[["ConformanceContext"], Iterator["Violation"]]] = None

    @property
    def severity(self) -> Severity:
        from .conformance import ENFORCE_MUST

        return severity_for(self, ENFORCE_MUST)

    @property
    def description(self) -> str:
        return self.message


def severity_for(rule: Rule, enforce_must: bool) -> Severity:
    if rule.level in (Level.MUST, Level.MUST_NOT):
        if rule.grace and not enforce_must:
            return Severity.WARNING
        return Severity.ERROR
    if rule.level is Level.SHOULD:
        return Severity.WARNING
    return Severity.INFO


_STRICTER_IN_1_20 = frozenset({"R102", "R104"})
"""Rules that were lint warnings in 1.19 and are MUST in 1.20."""


def _r(id: str, level: Level, category: Category, scope: str, title: str, message: str, fix: str) -> Rule:
    grace = id.startswith("R3") or id in _STRICTER_IN_1_20
    return Rule(id, level, category, frozenset(scope.split()), title, message, fix, grace)


Y, L, D = "yaml", "lock", "datapackage"

RULES: dict[str, Rule] = {
    r.id: r
    for r in [
        _r(
            "R001",
            Level.MUST,
            Category.NAMING,
            f"{Y}:dataset {D}:resource",
            "Dataset missing 'title'",
            "Every dataset must have a human-readable title.",
            "Add a 'title:' line.",
        ),
        _r(
            "R002",
            Level.MUST,
            Category.NAMING,
            f"{Y}:dataset {D}:resource",
            "Dataset missing 'name'",
            "Every dataset must have a unique kebab-case name.",
            "Add a 'name:' line.",
        ),
        _r(
            "R003",
            Level.MUST,
            Category.NAMING,
            f"{Y}:dataset",
            "Dataset missing 'path'",
            "Every dataset must declare its file path.",
            "Add a 'path:' relative to the project root.",
        ),
        _r(
            "R004",
            Level.SHOULD,
            Category.DESCRIPTION,
            f"{Y}:dataset",
            "Dataset missing 'description'",
            "Every dataset should have a description (one or two sentences).",
            "Add a one-line 'description:'.",
        ),
        _r(
            "R005",
            Level.MUST,
            Category.PROVENANCE,
            f"{Y}:dataset",
            "Dataset missing license",
            "Inputs carry 'dct:license' on the source; outputs carry 'licenses' or inherit the package's 'licenses'.",
            "Add an SPDX license identifier (e.g. 'CC-BY-4.0').",
        ),
        _r(
            "R006",
            Level.MUST,
            Category.PROVENANCE,
            f"{Y}:dataset",
            "License is not a recognised identifier",
            "License must be an SPDX identifier or a project allow-list value.",
            "Use an SPDX identifier (https://spdx.org/licenses/).",
        ),
        _r(
            "R007",
            Level.MUST,
            Category.NAMING,
            f"{Y}:field",
            "Field missing 'name'",
            "Every field must have a name.",
            "Add a 'name:' line.",
        ),
        _r(
            "R008",
            Level.MUST,
            Category.TYPES,
            f"{Y}:field",
            "Field missing 'type'",
            "Every field must declare a type.",
            "Add a 'type:' line (string, integer, number, ...).",
        ),
        _r(
            "R009",
            Level.MUST,
            Category.CONFIG,
            f"{Y}:document",
            "Malformed lint.disable entry",
            "Each 'lint.disable' entry maps a known rule ID to a non-empty justification. R009 cannot be suppressed.",
            "Use 'lint.disable:\\n  R104: \"reason\"'.",
        ),
        _r(
            "R010",
            Level.MUST_NOT,
            Category.PROVENANCE,
            f"{Y}:dataset",
            "Output license is NoDerivatives",
            "An output must not carry a NoDerivatives license (CC-BY-ND, CC-BY-NC-ND) unless it declares 'prov:wasQuotedFrom' (an unmodified copy of one source).",
            "Use the license the sources allow for derivatives, record the rights holder's permission under the source's 'dct:rights', or, if the output copies one source unmodified, add 'prov:wasQuotedFrom: <source name>'.",
        ),
        _r(
            "R101",
            Level.SHOULD,
            Category.PROVENANCE,
            f"{Y}:dataset",
            "Input missing 'source' block",
            "Inputs should declare where the data came from.",
            "Add a 'source:' block with title, dct:publisher (rdfs:label), a link (\"@id\", dcat:downloadURL or dcat:landingPage) and dct:license.",
        ),
        _r(
            "R102",
            Level.MUST,
            Category.PROVENANCE,
            f"{Y}:source",
            "Source block missing required keys",
            'A source needs title, dct:publisher with rdfs:label, a link ("@id", dcat:downloadURL or dcat:landingPage) and dct:license.',
            "Fill in the missing source keys; write the publisher as an object: 'dct:publisher: {rdfs:label: <full name>, skos:altLabel: <short name>}'.",
        ),
        _r(
            "R103",
            Level.SHOULD,
            Category.UNITS,
            f"{Y}:field",
            "Numeric field missing 'si:unit'",
            "Fields of type integer or number should declare 'si:unit'.",
            "Add 'si:unit:' (e.g. 'meter', 'USD').",
        ),
        _r(
            "R104",
            Level.MUST,
            Category.NAMING,
            f"{Y}:dataset",
            "Name not in kebab-case",
            "Dataset names are lowercase ASCII letters/digits separated by single hyphens.",
            "Rename to kebab-case (e.g. 'un-member-states').",
        ),
        _r(
            "R105",
            Level.SHOULD,
            Category.DESCRIPTION,
            f"{Y}:field",
            "Published output field missing 'description'",
            "Published outputs should describe every field.",
            "Add a 'description:' line.",
        ),
        _r(
            "R201",
            Level.INFO,
            Category.DESCRIPTION,
            f"{Y}:field",
            "Generic field name without description",
            "Fields named like 'total' or 'value' are ambiguous.",
            "Rename the field or add a clear description.",
        ),
        _r(
            "R202",
            Level.INFO,
            Category.NAMING,
            f"{Y}:dataset",
            "Generic dataset title",
            "Titles like 'data' or 'output' are ambiguous.",
            "Choose a domain-specific title.",
        ),
        _r(
            "R301",
            Level.MUST,
            Category.EXTRAS,
            f"{Y}:document {Y}:dataset {Y}:source {Y}:field {Y}:package {Y}:node {L}:entry {L}:source {D}:package {D}:resource {D}:field {D}:source",
            "Unknown key",
            "Every key is a Data Package property for its level, a sunstone config key, or an RDF property (prefix:local or IRI).",
            'Run `sunstone vocab search "<concept>" --at <path>` and use a listed key.',
        ),
        _r(
            "R302",
            Level.MUST,
            Category.EXTRAS,
            f"{Y}:document {Y}:dataset {Y}:source {Y}:field {Y}:package {Y}:node {L}:source",
            "Undeclared RDF prefix",
            "A prefix must be declared in 'rdfPrefixes' or be a standard prefix.",
            "Declare the prefix under 'rdfPrefixes:' or use a standard one.",
        ),
        _r(
            "R303",
            Level.MUST,
            Category.EXTRAS,
            f"{Y}:document {Y}:dataset {Y}:source {Y}:field {Y}:package {Y}:node {L}:source {D}:package {D}:resource {D}:field {D}:source",
            "Unknown vocabulary term",
            "Terms in shipped vocabularies (si, dcat-si, dct, dcat, prov, schema, qudt, rdfs, skos, sosa) must exist.",
            'Run `sunstone vocab search "<concept>"` to find the right term.',
        ),
        _r(
            "R304",
            Level.MUST_NOT,
            Category.EXTRAS,
            f"{Y}:document {Y}:dataset {Y}:source {Y}:field {Y}:package {L}:source",
            "Deprecated key",
            "Old sunstone keys are replaced by Data Package or RDF names.",
            "Run `sunstone migrate`.",
        ),
        _r(
            "R305",
            Level.MUST,
            Category.EXTRAS,
            f"{Y}:dataset",
            "Dataset has both 'slug' and 'title'",
            "An entry is either old form (slug + name) or new form (name + title), not both.",
            "Remove 'slug' and keep 'name' as the identifier, or run `sunstone migrate` on an old-form entry.",
        ),
        _r(
            "R306",
            Level.MUST,
            Category.EXTRAS,
            f"{Y}:document",
            "New-form keys without min_sunstone_version >= 1.20.0",
            "A file that uses new-form keys must set 'min_sunstone_version' to 1.20.0 or higher so older readers stop instead of misreading it.",
            "Add 'min_sunstone_version: \"1.20.0\"' at the top of datasets.yaml (or run `sunstone migrate`).",
        ),
        _r(
            "R307",
            Level.MUST_NOT,
            Category.EXTRAS,
            f"{Y}:dataset {Y}:source {Y}:field",
            "RDF property duplicates a Data Package key or a generated value",
            "Use the Data Package key (title, description, licenses, name) or let sunstone generate the value.",
            "Remove the RDF property and use the key named in the message.",
        ),
        _r(
            "R308",
            Level.MUST,
            Category.EXTRAS,
            f"{Y}:document",
            "Include file cannot be merged",
            "An 'include' entry must name an existing file with no nested includes, no document-level keys and no dataset names already in use.",
            "Fix or remove the 'include' entry named in the message.",
        ),
        _r(
            "R311",
            Level.SHOULD,
            Category.PROVENANCE,
            f"{Y}:source",
            "Source missing recommended keys",
            'Sources should carry skos:altLabel on the publisher, dct:issued and dct:modified; a publication (dct:isPartOf or dct:bibliographicCitation present) should also carry dct:creator and "@id".',
            "Add the missing keys to the source block (authors as 'dct:creator: [{rdfs:label: ...}]', the DOI as '\"@id\": https://doi.org/<doi>').",
        ),
        _r(
            "R315",
            Level.MUST_NOT,
            Category.PROVENANCE,
            f"{Y}:source {D}:source",
            "DOI used as a link",
            'A doi.org URL is an identifier: it goes in "@id", not in dcat:downloadURL or dcat:landingPage.',
            "Move the DOI to '\"@id\":' on the source and put the publisher's page in dcat:landingPage, if any.",
        ),
        _r(
            "R316",
            Level.SHOULD,
            Category.PROVENANCE,
            f"{Y}:field",
            "Field source object missing recommended keys",
            'A field-level source object should carry title, dct:publisher with rdfs:label, a link ("@id", dcat:downloadURL or dcat:landingPage) and dct:license, like a dataset source.',
            "Add the missing keys to the field's dct:source, or use a plain string naming the source.",
        ),
        _r(
            "R317",
            Level.SHOULD,
            Category.PROVENANCE,
            f"{Y}:dataset",
            "Input field sources repeat the dataset source",
            "An input's source is the file that was downloaded. Field-level sources on an input are only for upstream sources the publisher documents per column (aggregators such as OWID or WDI).",
            "Remove the field sources that repeat the dataset source.",
        ),
        _r(
            "R318",
            Level.SHOULD,
            Category.PROVENANCE,
            f"{Y}:field",
            "Field source repeats the dataset's only source",
            "A field source equal to the dataset's only resolved source (its source block or lineage sources) adds nothing.",
            "List sources at dataset level; use field-level sources only when columns come from different sources and are used on their own (e.g. a chart of one column).",
        ),
        _r(
            "R312",
            Level.MUST,
            Category.PROVENANCE,
            f"{Y}:dataset",
            "Input missing acquisition metadata",
            "Inputs must carry 'prov:generatedAtTime' and 'prov:wasGeneratedBy' with 'dct:type'.",
            "Add 'prov:generatedAtTime: <date>' and 'prov:wasGeneratedBy: {\"@type\": prov:Activity, dct:type: manual-download}'.",
        ),
        _r(
            "R313",
            Level.MUST,
            Category.PROVENANCE,
            f"{Y}:dataset {D}:resource",
            "Published output has no sources",
            "Each published output must resolve at least one source, directly or through its lineage.",
            "Add a 'source:' block or save the output through sunstone so the lock file records its inputs.",
        ),
        _r(
            "R314",
            Level.SHOULD,
            Category.DESCRIPTION,
            f"{Y}:dataset",
            "Published output missing recommended coverage properties",
            "Published outputs should carry dct:temporal, dct:spatial and dcat:theme.",
            "Add 'dct:temporal:', 'dct:spatial:' and 'dcat:theme:' (a Sunstone concept IRI) to the output.",
        ),
        _r(
            "R321",
            Level.SHOULD,
            Category.LINEAGE,
            f"{Y}:dataset",
            "Output has no lock entry with sources and activity",
            "Outputs should be written through sunstone so datasets.lock.yaml records sources and activity.",
            "Write the output with sunstone.pandas/polars, or run `sunstone dataset resolve`.",
        ),
        _r(
            "R322",
            Level.MUST,
            Category.LINEAGE,
            f"{L}:source",
            "Lock source references unknown dataset",
            "Lock-file sources must reference registered dataset names.",
            "Register the dataset or run `sunstone dataset resolve`.",
        ),
        _r(
            "R323",
            Level.MUST_NOT,
            Category.LINEAGE,
            f"{Y}:dataset",
            "Inline 'lineage' in datasets.yaml",
            "Lineage lives in datasets.lock.yaml.",
            "Run `sunstone dataset migrate`.",
        ),
        _r(
            "R331",
            Level.MUST,
            Category.TYPES,
            f"{Y}:field",
            "Unknown field type",
            "Field types must be registered in FieldTypeRegistry.",
            "Use one of the registered types (sunstone dataset validate lists them).",
        ),
        _r(
            "R341",
            Level.SHOULD,
            Category.UNITS,
            f"{Y}:field",
            "Unit is not Pint or QUDT",
            "'si:unit' should parse as a Pint unit or be a QUDT IRI.",
            "Use a Pint unit string (e.g. 'kg', 'USD') or a QUDT IRI; domain units stay allowed.",
        ),
        _r(
            "R351",
            Level.MUST,
            Category.NAMING,
            f"{Y}:package {D}:package",
            "Package missing 'title' when publishing",
            "A published package must have a title.",
            "Add 'title:' to the package block.",
        ),
        _r(
            "R361",
            Level.SHOULD,
            Category.METHODOLOGY,
            f"{Y}:document",
            "No methodology document",
            "Projects should declare 'dcat-si:methodology', the path or URL of the methodology document.",
            "Add 'dcat-si:methodology: METHODOLOGY.md' at the top level of datasets.yaml.",
        ),
        _r(
            "R362",
            Level.MUST,
            Category.METHODOLOGY,
            f"{Y}:document",
            "Publishing without a methodology document",
            "A project that publishes a package must declare 'dcat-si:methodology'.",
            "Add 'dcat-si:methodology: METHODOLOGY.md' at the top level of datasets.yaml.",
        ),
    ]
}


def register_check(rule_id: str) -> Callable[[Any], Any]:
    def deco(fn: Any) -> Any:
        RULES[rule_id].check = fn
        return fn

    return deco
