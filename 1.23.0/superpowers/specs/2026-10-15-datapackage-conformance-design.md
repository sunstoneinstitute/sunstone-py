# Datapackage Conformance: IRI-only extras, field rules, vocabulary

## Goal

Every property in `datasets.yaml`, `datasets.lock.yaml` and generated
`datapackage.json` is either a Data Package 2.0 (DP) property, a sunstone
configuration key, or an RDF property from a known vocabulary. Agents
(including Sonnet-class models) can produce conforming files by following
`sunstone lint --json` and `sunstone vocab search`, without inventing keys.

## Scope

Four repos, planned and landed in this order:

1. `rdf-registry`: define `dcat-si:methodology` (C11).
2. `sunstone-cms`: read the new IRI keys, keep old fallbacks (C12). Item 3
   (agent objects) is deployed before sunstone-py 1.20 is released; the rest
   lands before 2.x drops any old output key.
3. `sunstone-py`: C1–C9.
4. `claude-plugins`: `sunstone-core:dataset` skill update (C10).

Out of scope: hosting a sunstone DP profile URL, emitting lineage into
`datapackage.json`, SHACL shapes.

## Key classes

Every key in a sunstone file belongs to exactly one class:

| Class | Allowed where | Example |
|---|---|---|
| DP property | Level where DP 2.0 defines it (package, resource, schema, field, source, contributor) | `title`, `mediatype`, `licenses` |
| Config key | `datasets.yaml` only, never emitted | `inputs`, `publish`, `strict` |
| RDF property | Any metadata level | `dct:publisher`, `https://example.org/p` |

An RDF property is a prefixed name (`prefix:local`) or an absolute IRI.
In `datapackage.json`, RDF properties are always expanded to absolute IRIs.

Config keys (closed list): `inputs`, `outputs`, `include`, `defaults`,
`rdfPrefixes`, `package`, `packages`, `publish`, `strict`, `lint`,
`plugins`, `min_sunstone_version`. Within `packages[]`: `datasets`, `publish`.
Within `publish`: `enabled`, `to`, `flatten`, `as`, `as_name`, `public`,
`dialect`.

DP property sets are taken from the DP 2.0 profiles
(`https://datapackage.org/profiles/2.0/`) for every level, not only the keys
the parser reads today. Resource example: `$schema`, `bytes`, `data`,
`description`, `dialect`, `encoding`, `format`, `hash`, `homepage`,
`licenses`, `mediatype`, `name`, `path`, `schema`, `sources`, `title`, `type`.

## Key migration

Old sunstone keys are renamed to DP names, then upstream RDF terms, then
`dcat-si` (`https://sunstone.institute/rdf/data#`). The alias table covers
sunstone's own keys and `dct:title` on fields only. Unknown user keys are
never aliased automatically.

| Level | Old | New |
|---|---|---|
| top | `si:methodology` | `dcat-si:methodology` |
| dataset | `name` | `title` |
| dataset | `slug` | `name` |
| dataset | `location` | `path` |
| dataset | `fields` | `schema.fields` |
| dataset | `primaryKey` | `schema.primaryKey` |
| dataset | `license` | `licenses` (DP list form) |
| source | `name` | `title` |
| source | `attributedTo` | `prov:wasAttributedTo` (string IRI/label, or object with `@id`, `@type`, `rdfs:label`) |
| source | `attributedTo.version` | `version` |
| source | `license` | `dct:license` |
| source | `updated` | `dct:modified` |
| source | `acquiredAt` | dataset `prov:generatedAtTime` |
| source | `acquisitionMethod` | dataset `prov:wasGeneratedBy: {"@type": prov:Activity, dct:type: <method>}` |
| source | `location.data` | `dcat:downloadURL` |
| source | `location.web` / `location.about` | `dcat:landingPage` |
| source | `location.metadata` | `rdfs:seeAlso` |
| source | `location.access` | `dcat:accessURL` |
| field | `unit` | `si:unit` (Pint string); also `qudt:hasUnit` when it maps to a QUDT IRI |
| field | `source`, `si:sourceField` | `dct:source`: a string, or a source object normalized like a dataset source (acquisition keys stay on it) |
| field source | `publisher` | `dct:publisher` (agent object) |
| field | `dct:title` | `title` |
| lock `lineage.sources[]` | `attributedTo`, `license` | `prov:wasAttributedTo`, `dct:license` |

Known non-alias fixes in org repos (done by hand, guided by `migrate` output):

| Repo | Old | New |
|---|---|---|
| projects (FishFarmingProject) | `coverage` | `dct:temporal` |
| research-stack | `si:ontologySource` | `dct:source` |
| research-stack | `si:ontologyConceptScheme` | `dct:subject` |
| research-stack | `si:ontologyName` | removed (redundant with scheme IRIs) |
| research-stack | `si:embeddingModel` | `prov:wasGeneratedBy: {prov:used: <model IRI>}` on the output |

Acquisition moves from `source` to the input dataset: the source describes
the upstream data, while acquisition time and method describe how the local
copy was generated. `<method>` is a literal such as `manual-download`, `api`
or `scraping`.

Dataset `name` changes meaning, so each entry's form is detected before
normalizing: `slug` present means old form (`name` is the title), `title`
present means new form (`name` is the identifier). Both present is a MUST
violation. Neither present leaves the entry without a title, which fails the
naming rules.

An RDF property value may be an object. It is a JSON-LD node object: a blank
node, or a named node when it has `@id`, linked to the subject by the
property. `prov:wasGeneratedBy: {prov:used: <IRI>}` yields
`<resource> prov:wasGeneratedBy _:b . _:b prov:used <IRI> .` Keys inside the
object follow the same rules (RDF property, `@id` or `@type`) and are
expanded the same way.

## Rules

Levels follow RFC 2119. Enforcement:

| Level | 1.x | 2.0 |
|---|---|---|
| MUST / MUST NOT | `FutureWarning` on read/write, lint error | `ConformanceError` on read/write, lint error |
| SHOULD | lint warning | lint warning |
| MAY | not checked | not checked |

Grace period: in 1.x, a MUST rule that is new or stricter in 1.20 (all R3xx
rules, and R102 and R104, which were warnings before) is a lint warning, so
a project that linted clean on 1.19 still does. Rules that were already
errors in 1.19 stay errors. In 2.0 all MUST rules are lint errors.

Rule IDs: existing lint IDs R001–R202 keep their numbers. New rules use R3xx.

### Extras (all levels)

- MUST: every key is a DP property for its level, a config key (in
  `datasets.yaml`), or an RDF property.
- MUST: a prefix resolves through declared `rdfPrefixes` or the standard
  prefixes.
- MUST: a term in a shipped vocabulary (`si`, `dcat-si`, `dct`, `dcat`,
  `prov`, `schema`, `qudt`, `rdfs`, `skos`, `sosa`) exists in that
  vocabulary.
  Project-declared prefixes are not term-checked.
- MUST NOT: old alias keys (2.0 only; 1.x warns and normalizes).
- MUST: a file that uses any new-form key sets `min_sunstone_version` to
  `1.20.0` or higher, so 1.8–1.19 readers stop with their version error
  instead of misreading it.

- MUST NOT: an RDF property that duplicates a DP key, a config key or a
  value sunstone generates. See "Duplicate properties" below.

### Provenance

- MUST (input source): `title`; `dct:publisher` with `rdfs:label`; a link
  (`"@id"`, `dcat:downloadURL` or `dcat:landingPage`); `dct:license` (SPDX
  id).
- MUST (input dataset): `prov:generatedAtTime`, and `prov:wasGeneratedBy`
  with `dct:type`.
- SHOULD (input source): `skos:altLabel` on the publisher, `dct:issued`,
  `dct:modified`. When the source is a publication (`dct:isPartOf` or
  `dct:bibliographicCitation` present): `dct:creator` and `"@id"`.
- MAY (input source): `prov:wasAttributedTo`, free-text attribution. It
  holds today's `attributedTo` text after migration.
- MUST NOT: a `doi.org` URL in `dcat:downloadURL` or `dcat:landingPage`.
  A DOI goes in `"@id"`.
- MUST (published output): at least one resolved source in
  `datapackage.json` (direct or via `was_derived_from`).
- Field `dct:source` is a per-column attribution: a string naming the
  source, or a source object.
- SHOULD (field source object): the input source keys above (R316).
- SHOULD: an input's field sources differ from its dataset source (R317).
  The input source is the downloaded file; field sources on an input are
  for upstream sources the publisher documents per column (aggregators
  such as OWID or WDI).
- SHOULD: a field source does not repeat the dataset's only resolved
  source, its `source` block or lineage sources (R318, outputs). A field
  source repeats a dataset source when a string equals (case-insensitive)
  its `title`, publisher `rdfs:label` or `skos:altLabel`, or an object has
  the same `title` and publisher label.
- Emitted sources in `datapackage.json` carry all source properties above as
  expanded IRIs, alongside the existing `title`, `path` and `dcat:*` keys.
  `path` is derived on write (first of `dcat:downloadURL`,
  `dcat:landingPage`, `rdfs:seeAlso`, `dcat:accessURL`, `"@id"`), never
  authored.

### Source references

A source is structured so a renderer can choose its level of detail. The
render templates live in sunstone-cms issue #610.

| Part | Key | Value |
|---|---|---|
| Identifier | `"@id"` | DOI as `https://doi.org/<doi>`, or another persistent IRI |
| Work title | `title` | string |
| Publisher | `dct:publisher` | agent object |
| Authors | `dct:creator` | list of agent objects |
| Year | `dct:issued` | year or date |
| Container | `dct:isPartOf` | object with `rdfs:label` (journal, volume, pages) |
| Full citation | `dct:bibliographicCitation` | string |
| Links | `dcat:downloadURL`, `dcat:landingPage`, `dcat:accessURL` | URL |
| License | `dct:license` | SPDX id |
| Legacy attribution | `prov:wasAttributedTo` | string |

An agent object has `rdfs:label` (full name), optional `skos:altLabel`
(short name) and optional `"@id"` (IRI). `"@id"` is quoted in YAML.

Agents are written inline. A file that names the same agent more than once
uses a YAML anchor on the first use and aliases after it:

```yaml
dct:publisher: &fao
  rdfs:label: Food and Agriculture Organization of the United Nations
  skos:altLabel: FAO
# later in the same file
dct:publisher: *fao
```

Anchors are plain YAML: ruamel keeps them on round-trip saves, and an alias
loads as the same object, so C4 and C7 rename keys once for every use.
Anchors do not cross files, so each include file anchors its own agents.
sunstone-py writes the expanded object into `datapackage.json`.

Restructuring the existing sources (authors, year, container out of free
text) is done by agents using the dataset skill, project by project, during
the 1.x grace period. `sunstone migrate` only makes the mechanical changes
(C7).

### Lineage

- SHOULD: each output has a lock entry with `sources` and `activity`.
- MUST: lock `sources` reference registered dataset names.
- MUST NOT: inline `lineage` in `datasets.yaml`.

### Types

- MUST: every field of a tabular resource has a `type` registered in
  `FieldTypeRegistry`. `cli.py` `VALID_FIELD_TYPES` is removed in favor of
  the registry.

### Units

- SHOULD: fields of type `integer` or `number` have `si:unit`.
- SHOULD: `si:unit` parses as Pint or a QUDT IRI. Not a MUST, so
  domain-specific units remain usable.

### Name and title

- MUST: dataset `title` and `name`; `name` is kebab-case.
- MUST: field `name`.
- MUST (when publishing): package `title`.

### Description

- SHOULD: dataset `description` (R004 becomes a warning).
- SHOULD: field `description` on published outputs (R105).

### Methodology

- SHOULD: top-level `dcat-si:methodology`, the path or URL of the
  methodology document.
- MUST: when the project publishes a package (`publish` is set on
  `package` or any `packages[]` entry). Lint cannot tell who produced a
  dataset, so publishing is the test.

### Recommended properties

Checked at the stated level. Properties not listed here are allowed if they
pass the extras rules.

| Scope | Property | Level | Use |
|---|---|---|---|
| dataset | `dct:temporal` | SHOULD | Time coverage |
| dataset | `dct:spatial` | SHOULD | Geographic coverage (place IRI or name) |
| dataset | `dcat:theme` | SHOULD | Classification against a Sunstone concept scheme |
| dataset | `dcat:keyword` | MAY | Free-text tags |
| dataset | `dct:conformsTo` | MAY | Standard or schema the data follows |
| dataset | `dct:references` | MAY | Related publications |
| dataset | `rdfs:seeAlso` | MAY | Other related resources |
| dataset | `dct:accrualPeriodicity` | MAY | Update frequency |
| dataset | `dct:language` | MAY | Language of text values |
| dataset | `dct:source`, `dct:subject` | MAY | Derivation source and topic (ontology-mapping outputs) |
| source | `dct:creator` | MAY | Producer, when different from the publisher |
| field | `skos:exactMatch` | MAY | Concept IRI for the field |
| field | `sosa:observedProperty` | MAY | Observed property IRI |
| field | `qudt:hasQuantityKind` | MAY | Quantity kind, alongside `si:unit` |
| field | `dct:conformsTo` | MAY | Code list or standard the values follow |

SHOULD properties are checked on published outputs only.

### Duplicate properties (MUST NOT)

| Scope | Property | Use instead |
|---|---|---|
| dataset | `dct:identifier` | `name` |
| dataset | `dct:title` | `title` |
| dataset | `dct:description` | `description` |
| dataset | `dct:license` | `licenses` |
| dataset | `dct:created` | generated at write time |
| dataset | `prov:wasDerivedFrom` | generated from lineage |
| output dataset | `prov:generatedAtTime` | generated at write time (inputs set it, see Provenance) |
| dataset | `schema:keywords` | `dcat:keyword` |
| dataset | `schema:temporalCoverage` | `dct:temporal` |
| field | `dct:title` | `title` (aliased in 1.x) |
| field | `dct:description` | `description` |
| field | `qudt:unit` | `si:unit` |
| field | `prov:wasDerivedFrom` | `dct:source` |
| source | `si:publisher` | `dct:publisher` |

## Components (sunstone-py)

### C1. Vocabulary data — `src/sunstone/vocab/`

- DP property sets per level, config key list, alias table, recommended
  and duplicate property tables.
- `dcat-si` added to `STANDARD_RDF_PREFIXES`.
- One JSON file per shipped vocabulary: for each property, CURIE, IRI,
  label, definition. Labels from `rdfs:label`, `dct:title`,
  `skos:prefLabel`. Definitions from `rdfs:comment`, `skos:definition`,
  `dct:description`.
- `scripts/sync_vocab.py` downloads vocabularies (and reads
  `rdf-registry/rdf/*.ttl` for `si` and `dcat-si`) with `rdflib`, and writes
  the JSON files. `rdflib` is a dev dependency only. Runtime never fetches.

### C2. Rule registry — `src/sunstone/rules.py`

`Rule(id, level, category, scope, check, message, fix)`. `scope` is
`yaml` or `datapackage` plus the level (package, resource, source, field,
lock). Categories: extras, provenance, lineage, types, units, naming, methodology,
description.

### C3. Validator — `src/sunstone/conformance.py`

- `validate_datasets_yaml(data) -> list[Violation]`
- `validate_lock(lock, data) -> list[Violation]` (`data` is the normalized
  `datasets.yaml`, needed to check that lock sources name registered datasets)
- `validate_datapackage(descriptor) -> list[Violation]`
- `Violation(rule_id, level, path, message, fix)`. `path` addresses the key,
  e.g. `inputs[3].source.attributedTo`.
- `ENFORCE_MUST` constant: `False` in 1.x, `True` in 2.0.

### C4. Read hook

`DatasetsManager._load` normalizes alias keys to new keys (one model for the
rest of the code), runs C3, and emits one `FutureWarning` per load (the
main file with its includes merged):
the MUST violation count, the first five with their paths, and "run
`sunstone lint` for all of them; these become errors in sunstone-py 2.0".
Alias keys produce one more `FutureWarning` per file (main or include) naming
`sunstone migrate`. `FutureWarning` is used because Python hides
`DeprecationWarning` raised inside a library; `DeprecationWarning` stays
for deprecated Python APIs.

### C5. Write hook

`build_datapackage` (`cli.py`) and `packaging.push_group` emit new keys as
expanded IRIs, set `$schema` to the DP 2.0 profile URL, and run C3 on the
finished descriptor before writing or pushing. Existing output fields stay
in 1.x, alongside their new forms:

| Existing output key | New key emitted alongside |
|---|---|
| package `https://sunstone.institute/rdf/vocab#methodology` | `https://sunstone.institute/rdf/data#methodology` |
| field `unit` | `https://sunstone.institute/rdf/vocab#unit` (+ `qudt:hasUnit` IRI when mapped) |
| field `source` | `http://purl.org/dc/terms/source` (string, or the object with expanded keys) |
| package `license` | `licenses` |
| field `http://purl.org/dc/terms/title` | `title` |
| resource `scheme` (frictionless) | none; removed with the other old keys |

Field `source` keeps its 1.19 value: a string as is, an old-form object as
authored. For a new-form object it is derived by reversing the renames
(`title` → `name`, `dct:publisher` label → `publisher`, links → `location.*`,
a DOI `"@id"` → `location.web`); keys without an old form are kept.

`datapackage.json` is retired in favour of DCAT under data-platform spec
[DP-SPEC-32](https://worklode.dev.sunstoneinstitute.ai/DP-SPEC-32). 2.x
removes the left column only as part of that retirement, and only after C12.
No other `datapackage.json` key is removed.

One existing value changes shape in 1.20: source `dct:publisher` and
`dct:creator` in `datapackage.json` are agent objects, not strings. The CMS
reads the string today, so sunstone-cms deploys C12 item 3 (reading
`rdfs:label` from these objects) before sunstone-py 1.20.0 is released.

### C6. Lint

`lint.py` runs C2 rules. `sunstone lint --json` includes `path` and `fix`
per violation.

### C7. Migration — `sunstone migrate`

Rewrites `datasets.yaml`, its include files and `datasets.lock.yaml` with
ruamel round-trip (comments and order kept). Idempotent. Besides the alias
renames, it moves a `doi.org` URL from `location.data` or `location.web` to
the source's `"@id"`, wraps a string `dct:publisher` or `dct:creator` into
`{rdfs:label: <string>}`, and keeps the old `attributedTo` text as
`prov:wasAttributedTo`. It never splits free text and never deletes a
value: when the old key's target already holds a different value, the old
key stays where it is and the conflict is reported. Reports remaining
unknown plain keys with top `vocab search` suggestions.

### C8. Generated artifacts — `scripts/gen_schemas.py`

- `schemas/datasets.schema.json`: for editors via
  `# yaml-language-server: $schema=...`.
- `schemas/datapackage-profile.json`: DP 2.0 plus `patternProperties`
  restricting extras to prefixed names or IRIs.
- `docs/datasets-yaml-reference.md`: every allowed key per level, its class,
  rule level and an example.
- A test fails when any of them differs from regenerated output.

JSON Schema covers key shape. Term existence and SHOULD checks live in C3.

### C9. `sunstone vocab search <text>`

Linear scan, no index. The corpus is every record in the C1 JSON files
(shipped vocabularies plus DP and config keys), a few thousand records, so a
scan is fast enough.

1. Each record has four match fields: local name (raw, plus camelCase split
   into words: `wasAttributedTo` → `was attributed to`), CURIE, label,
   definition. All lowercased.
2. The query is lowercased and split on whitespace. A record matches when
   every query word is a substring of at least one match field.
3. Each query word's tier is the best field it matched: local name or
   CURIE (1), label (2), definition (3). A record's tier is the worst of
   its words' tiers, so "download url" ranks `dcat:downloadURL` (both words
   in the name) above `dcat:accessURL` ("download" only in the definition).
4. Results sort by tier, then source (DP and config keys, then `dct`,
   `dcat`, `prov`, `schema`, `skos`, `rdfs`, `qudt`, `sosa`, `si`, `dcat-si`), then
   CURIE. Default limit 20, `--limit` to change.

Output: `curie  IRI  label: definition`; `--json` for agents.

`--at <path>` restricts DP and config results to keys valid at one level of
`datasets.yaml`. The path uses dotted key names without array markers, e.g.
`--at inputs.source` or `--at outputs.schema.fields`. With `--at` and no search text, it lists
every allowed key at that level with its class and rule level (like
`kubectl explain`). RDF terms are allowed at any level and are not filtered.

## C10. claude-plugins: `sunstone-core:dataset`

- Replace `references/datasets-yaml-schema.md` with the generated
  `docs/datasets-yaml-reference.md` (sync script).
- Instruct: never write a key absent from the reference; find a term with
  `sunstone vocab search "<concept>" --at <path> --json` and pick from its
  results; done only when
  `sunstone lint --json --warnings-as-errors` is clean.
- Examples use the new key forms.

## C11. rdf-registry

Add `dcat-si:methodology` to `rdf/data.ttl`. C1's vocabulary sync reads it
from there. No upstream term fits: `prov:hadPlan` is an optional plan of
intent reached through a qualified association, `dct:provenance` covers
custody, `dct:conformsTo` names a shared standard, and
`schema:measurementTechnique` covers measuring one variable.

| Axiom | Value | Reason |
|---|---|---|
| type | `owl:ObjectProperty` | Value is a document IRI |
| `rdfs:label`, `rdfs:comment`, `rdfs:isDefinedBy` | present | OOPS! documentation pitfalls |
| `rdfs:domain` | `dcat:Resource` | Covers packages and datasets without inferring `dcat:Dataset` |
| `rdfs:range` | `foaf:Document` | OOPS! P11 (missing domain or range) |
| `rdfs:subPropertyOf` | `foaf:page` | DCAT-AP uses `foaf:page` for documentation, so generic DCAT consumers still follow the link |
| `rdfs:seeAlso` | `si:methodology` | The term it replaces |

The `rdfs:comment` states the difference from `prov:hadPlan` (a document of
the method applied, not a plan of intent) and from
`schema:measurementTechnique` (the whole dataset, not one variable).

## C12. sunstone-cms

The CMS imports `datapackage.json` from GCS (`DataPackages/endpoints/import.ts`)
and matches short keys plus a few full IRIs. It uses no JSON-LD context, so
each new IRI is matched literally. Changes, each keeping the old key as a
fallback:

1. Methodology (`import.ts`): read `https://sunstone.institute/rdf/data#methodology`,
   then `https://sunstone.institute/rdf/vocab#methodology`.
2. Field schema (`extractSchema`): map the `si:unit` IRI to `unit` and the
   `dct:source` IRI to `source`, before the short keys. Store
   `qudt:hasUnit` as `unitIri` when present.
3. Sources (`sourcesFromSchemaFields.ts` `toSourceRecords`): store the
   structured parts from "Source references" (identifier, title, publisher
   label and short name, creators, year, container, citation, links,
   license) and render them with the templates in sunstone-cms#610. When
   `dct:publisher` is missing, fall back to the `prov:wasAttributedTo` text,
   so unstructured sources are not dropped.
4. `methodology-service.ts`: replace the local `Source` interface (old
   `datasets.yaml` shape) with the DP source shape used by
   `sourcesFromSchemaFields.ts`.
5. Tests: an `import.test.ts` fixture in the 1.20 output shape (old and new
   keys) and one with new keys only; both import identically.

All new values go into existing `json` columns, so no DB migration.

## Releases

- 1.x minor: C1–C9, alias normalization with warnings, MUST violations warn,
  `sunstone migrate`, new IRI keys in `datapackage.json`.
- 2.0: `ENFORCE_MUST = True`; reader drops aliases (`migrate` keeps them);
  lock files lose old plain keys. Old `datapackage.json` keys stay until the
  DCAT retirement (DP-SPEC-32, see C5).
- 2.0 prerequisite: every `datasets.yaml` in the org repos (`projects`,
  `research-stack`, `trusthere-data`, `ai-democracy-project`,
  `thegrid-project`) is migrated and restructured, and passes
  `sunstone lint` with MUST enforced. The 1.x releases are the grace period
  for this.

## Testing

- One unit test per rule (pass and fail case).
- Fixture projects in old and new form; C4 normalizes both to equal models.
- Migration round-trip keeps comments and is idempotent.
- Generated-artifact staleness test (C8).
- `datapackage.json` golden test: new keys present, no existing key removed
  or changed.
- `vocab search` ranking tests (`attributed` finds `prov:wasAttributedTo`
  first).
- Paths written to files use `as_posix()` (Windows CI).
