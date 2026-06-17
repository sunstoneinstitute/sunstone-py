# Field-Level Observed-Property Metadata Design

**Date**: 2026-06-14
**Status**: Proposed

## Problem

`datasets.yaml` field metadata can express the *magnitude* of a measurement
(`unit:`) but not the **observed property** — i.e. *what material or quantity the
number actually represents*. For the Norwegian aquaculture datasets this is a real
loss of meaning:

```yaml
- name: N Tonnes
  type: number
  unit: http://qudt.org/vocab/unit/TONNE   # tonnes of *what*?
```

`N Tonnes`, `P Tonnes`, `Oc Tonnes`, `total_tonnes`, `aquacultureTonnes`,
`biomass`, and feed `total` are all "tonnes", but the substance behind each
(total nitrogen, total phosphorus, organic carbon, salmon biomass, aquafeed) is
only recoverable from the human-readable `description`. There is no
machine-linkable way to say "this column is a mass of nitrogen".

### Why we can't just add it today

Unlike the **dataset level** — where any `prefix:term` key on an input/output
becomes a custom RDF property and is expanded into `datapackage.json`
(`datasets.py:_extract_rdf_properties`, `:553`) — the **field level** has no such
channel:

- `FieldSchema` (`lineage.py:218`) carries only
  `name / type / constraints / description / unit / source / unit_source`.
- `_parse_fields` (`datasets.py:337`) reads exactly those keys and **silently
  drops** any other key on a field mapping.
- `_field_schema_to_dict` (`datasets.py:68`) and the field loop in
  `Metadata.to_jsonld` (`lineage.py:~683`) emit only those same keys
  (`to_jsonld` emits just `dct:description`, type, unit, constraints).

So a field-level `sosa:observedProperty` written in `datasets.yaml` would parse
without error and then vanish — it never reaches `datapackage.json`.

This is also a **doc↔implementation gap**: `docs/datapackage-extra-metadata.md`
documents field-level `sosa:observedProperty`, `qudt:unit`, and `skos:definition`
as the *intended* output shape, but the parser cannot produce it.

## Goals

- Let a field carry arbitrary, machine-readable RDF annotations (observed
  property, substance/constituent, quantity kind, feature of interest) that
  round-trip through `datasets.yaml` and are expanded into `datapackage.json`
  and the JSON-LD emitted by `Metadata.to_jsonld`.
- Mirror the existing **dataset-level** custom-property mechanism exactly
  (prefix detection, prefix expansion, `defaults.rdfPrefixes` inheritance) so the
  authoring story is consistent.
- Fully additive and backwards-compatible: existing field schemas are unchanged.

## Non-goals

- Shipping a curated substance→URI lookup table (a possible follow-up; see Open
  Questions).
- Changing how `unit:` / QUDT resolution works.
- Modelling concentration/time-series observations beyond the "static column =
  observed property" mapping.

## Modelling approach

A measured column is treated as the result of an **observation**. We decompose it
into four optional layers, of which only the first two are normally needed:

| Layer | Property | Vocabulary |
|-------|----------|------------|
| Quantity kind | `qudt:hasQuantityKind` | QUDT (`quantitykind:Mass`, `Count`, …) |
| Observed property / constituent | `sosa:observedProperty` | NERC/BODC P01 (marine), or a minted ObservableProperty |
| Substance identity | `dct:subject` (+ `skos:exactMatch`) | ChEBI / ENVO / Wikidata |
| Feature of interest (optional) | `sosa:hasFeatureOfInterest` | ENVO (e.g. coastal water) |

### Vocabulary layering (all four, by role)

Per the agreed direction we layer the vocabularies by what each is good at, and
cross-link the alternates with `skos:exactMatch`:

- **QUDT + SOSA** — the structural backbone (`hasQuantityKind`,
  `observedProperty`). Always present.
- **NERC/BODC** (`vocab.nerc.ac.uk` P01/P02) — the marine-science standard for
  the *observed property* of nutrient parameters; the natural primary for
  Norwegian coastal nutrient loading, and already referenced in
  `datapackage-extra-metadata.md`.
- **ChEBI / OBO** — the *substance* identity (the chemical entity), good for
  cross-domain linking.
- **ENVO + Wikidata** — environmental-material / pollutant / waste framing
  (ENVO) and accessible fallback identifiers (Wikidata).

> **Exact concept IDs must be looked up, not guessed.** Candidate identifiers
> below are starting points to verify against each authority's resolver before
> use. In particular, a *mass load in tonnes/year* is not the same observable as
> a *concentration*; NERC P01 codes are largely concentration-oriented, so the
> `sosa:observedProperty` for a load may need a minted local ObservableProperty
> whose constituent is the ChEBI substance (see Open Questions).

## `datasets.yaml` authoring shape

Field mappings gain the same "any `prefix:term` key is a custom RDF property"
behaviour the dataset level already has. Prefixes resolve against the dataset's
`rdfPrefixes` / top-level / `defaults.rdfPrefixes`, exactly as today. All the
relevant prefixes (`qudt`, `sosa`, `dct`, `skos`, `envo`) are already in
`STANDARD_RDF_PREFIXES`; NERC has no standard prefix, so use full URIs or declare
one.

```yaml
- name: N Tonnes
  type: number
  unit: http://qudt.org/vocab/unit/TONNE
  description: Estimated total-nitrogen discharge from aquaculture, per county-year.
  qudt:hasQuantityKind: http://qudt.org/vocab/quantitykind/Mass
  sosa:observedProperty: http://vocab.nerc.ac.uk/collection/P01/current/TNITZZXX/   # total nitrogen (verify)
  dct:subject: http://purl.obolibrary.org/obo/CHEBI_25555                            # nitrogen (verify)
  skos:exactMatch:
    - https://www.wikidata.org/wiki/Q627                                            # nitrogen
```

### Worked targets for the aquaculture fields

| Field(s) | `qudt:hasQuantityKind` | Observed property / substance (candidates — verify) |
|---|---|---|
| `N Tonnes`, `total_tonnes`(N) | `quantitykind:Mass` | NERC P01 total-N; `CHEBI_25555` nitrogen; `wd:Q627` |
| `P Tonnes`, `total_tonnes`(P) | `quantitykind:Mass` | NERC P01 total-P; `CHEBI_28659` phosphorus; `wd:Q674` |
| `Oc Tonnes` | `quantitykind:Mass` | NERC TOC parameter; `CHEBI_27594` carbon (+ "organic"); ENVO organic-carbon |
| `biomass`, `weightLiveStock` | `quantitykind:Mass` | salmon biomass; `dwc:scientificName Salmo salar`; ENVO organism-biomass |
| feed `total`, `fishSales` | `quantitykind:Mass` | aquafeed / farmed-fish mass |
| `peEquivalent`, `Pe N/P/Oc` | (dimensionless) | population equivalent — **no clean ontology term**; describe, or mint `si:populationEquivalent` |
| mortality `*_sea`/`*_hatchery` | `quantitykind:Count` | dead-fish count (not a mass) |

Pollutant/waste *role* can additionally be attached at the **dataset** level
(where custom props already flow) via `dct:subject` to e.g. eutrophication
(`wd:Q183399`) / nutrient pollution — keeping field annotations focused on the
observed property.

## Implementation in `sunstone-py`

All changes mirror the dataset-level custom-property path; no new concepts.

1. **`FieldSchema` (`lineage.py:218`)** — add:
   ```python
   custom_properties: Optional[Dict[str, Any]] = None
   """Field-level custom/RDF properties (e.g. sosa:observedProperty), expanded at build time."""
   ```

2. **`_parse_fields` (`datasets.py:337`)** — after extracting the known keys,
   collect every remaining key for which `_is_rdf_property_key(key)` is true into
   `custom_properties` (reuse the existing helper at `datasets.py:551`). Unknown
   *non-RDF* keys keep being ignored, preserving current leniency.

3. **`_field_schema_to_dict` (`datasets.py:68`)** — emit `custom_properties` back
   out so `datasets.yaml` round-trips losslessly.

4. **`Metadata.to_jsonld` field loop (`lineage.py:~683`)** — add each field's
   custom properties to the per-field JSON-LD entry, applying the same prefix
   expansion used for dataset-level properties.

5. **Datapackage build** — include the (expanded) field custom properties in each
   `schema.fields[]` entry, so `datapackage.json` carries them. Reuse the
   dataset-level expansion routine; prefixes come from the resolved
   dataset/`defaults` `rdfPrefixes`.

6. **Prefix resolution** — field properties inherit the dataset's effective
   prefix map; no separate per-field `rdfPrefixes` block (can be a later
   extension if needed).

7. **Tests** (`tests/test_datasets.py`, `tests/test_rdf.py`,
   `tests/test_packaging.py`) — round-trip of a field custom prop through
   `datasets.yaml`; prefix expansion of a field `sosa:observedProperty`;
   appearance in built `datapackage.json`; back-compat for fields with no custom
   props.

8. **CHANGELOG** — `Added: field-level RDF/custom properties in datasets.yaml
   (e.g. sosa:observedProperty) now flow to datapackage.json`.

## `datapackage.json` output shape

```json
{
  "name": "N Tonnes",
  "type": "number",
  "http://qudt.org/schema/qudt/unit": "http://qudt.org/vocab/unit/TONNE",
  "http://qudt.org/schema/qudt/hasQuantityKind": "http://qudt.org/vocab/quantitykind/Mass",
  "http://www.w3.org/ns/sosa/observedProperty": "http://vocab.nerc.ac.uk/collection/P01/current/TNITZZXX/",
  "http://purl.org/dc/terms/subject": "http://purl.obolibrary.org/obo/CHEBI_25555",
  "http://www.w3.org/2004/02/skos/core#exactMatch": ["https://www.wikidata.org/wiki/Q627"]
}
```

This matches the field-level example already in
`docs/datapackage-extra-metadata.md`, closing the doc↔code gap.

## Open questions

1. **Observed property vs constituent for a *load*.** NERC P01 parameters are
   concentration-shaped. For a mass *load* (tonnes/yr) the cleanest model is a
   minted local `ObservableProperty` ("mass of total nitrogen discharged") whose
   constituent is the ChEBI substance, rather than reusing a concentration P01
   code. Decision needed: mint under `si:` vs. accept the nearest NERC code.
2. **Population equivalent (PE)** has no off-the-shelf ontology term. Mint
   `si:populationEquivalent` (a Sunstone quantity kind), or leave as described
   text?
3. **Curated lookup.** Worth a small `si:` substance registry (slug → URIs) in
   `data-platform` so analysts annotate with `si:substance: total-nitrogen`
   instead of hand-picking URIs? Could expand at build time.
4. **Per-field `rdfPrefixes`.** Out of scope here; field props inherit the
   dataset prefix map. Add later if a real need appears.

## Rollout

1. **sunstone-py** — implement the `FieldSchema` custom-property pass-through
   above (one PR, behind this spec).
2. **projects** — annotate the nutrient fields in `aquaculture-data`,
   `nutrient_analysis`, and `fishmap-dashboard` `datasets.yaml` (extend the
   already-open enrichment PRs, or follow-up PRs).
3. **data-platform** — confirm the DCAT/JSON-LD builder surfaces field-level
   observed properties from the resulting `datapackage.json`.
