# dcat-si metadata model and Rust core (draft)

Status: draft for review. Not yet approved.

## Goal

Replace the Data Package v2 model in `datasets.yaml` with DCAT 3 + dcat-si, validated by SHACL,
and move all metadata, storage and platform logic out of Python into one Rust crate shared by the
`sunstone` CLI, sunstone-py and data-platform.

## Decisions

- D1: DCAT 3 + dcat-si is the canonical model. `datapackage.json` becomes a generated export that
  validates against the vendored Data Package v2 profiles.
- D2: `datasets.yaml` stays YAML: YAML-LD with an implicit context. Bare keys map to DCAT, dct and
  dcat-si IRIs through a sunstone-owned JSON-LD context. Every other key is `prefix:term` with a
  declared prefix.
- D3: Columns are `dcat-si:Field`, mirroring the Table Schema v2 field properties, attached to
  `dcat-si:Table` as an ordered list (`dcat-si:field`). DCAT 3 has no column model.
- D4: The file name stays `datasets.yaml`. A top-level `context: https://sunstone.institute/rdf/data#`
  or its built-in prefix form `context: "dcat-si:"` selects the new reader. `sunstone migrate`
  rewrites old form in place. Both forms are readable through 2.x. The old form is removed in 3.0.
- D5: rdf-registry `rdf/data.ttl` becomes the full dcat-si vocabulary. SHACL shapes live in
  `rdf/shapes/dcat-si-shapes.ttl`. The JSON-LD context is generated from `data.ttl`.
- D6: A Rust crate `sunstone-core` owns the model, edits, validation, storage, packaging, platform
  access and auth. The `sunstone` CLI is a Rust binary over it. sunstone-py calls it through PyO3.
  Everything ships as one maturin wheel.
- D7: `sunstone_data` (data-platform/src/sunstone_data) merges into sunstone-py, and its logic is
  rewritten in `sunstone-core`. data-platform's Rust services depend on `sunstone-core` directly.

## Example

```yaml
context: "dcat-si:"
id: https://sunstone.institute/projects/norway-population
title: Norway population analysis
inputs:
  - id: ssb-population
    type: dcat-si:Table
    dct:source: https://ssb.no/...
    distribution:
      - path: data/raw/ssb.csv
        format: csv
outputs:
  - id: population
    type: dcat-si:Table
    title: Population by county
    license: CC-BY-4.0
    dct:source: https://ssb.no/...
    distribution:
      - path: data/pop.csv
        format: csv
    fields:
      - name: county
        type: string
      - name: pop
        type: integer
        si:unit: unit:NUM
```

### Context mapping

The document root is the project, a `dcat:Catalog`. Keys map as follows.

| Key | Maps to | Note |
|---|---|---|
| `context` | `@context` | JSON-LD 1.1 forbids aliasing `@context`, so the loader renames it before JSON-LD processing. `"dcat-si:"` resolves to the namespace IRI. |
| `id`, `type` | `@id`, `@type` | Keyword aliases in the context. Relative `id` values resolve against the root `id`. |
| `inputs` | `dcat-si:input` | `rdfs:subPropertyOf dcat:dataset`. |
| `outputs` | `dcat-si:output` | `rdfs:subPropertyOf dcat:dataset`. |
| `title`, `description`, `license` | `dct:title`, `dct:description`, `dct:license` | |
| `distribution`, `path`, `format` | `dcat:distribution`, `dcat:downloadURL`, `dct:format` | |
| `fields` | `dcat-si:field` | `@container: @list`. |

Consumers that apply RDFS see every input and output as a plain `dcat:dataset` of the catalog.
The two subproperties keep the input/output distinction in the graph.

## Components

### rdf-registry

1. `rdf/data.ttl` v0.3: `dcat-si:Field` and its properties (`name`, `title`, `description`, `type`,
   `format`, `constraints`, `categories`, `missingValues`, `example`, `rdfType`, number/boolean
   parsing properties), plus `dcat-si:field`.
2. `rdf/shapes/dcat-si-shapes.ttl`: shapes for `dcat:Catalog` (today's `package`), `dcat-si:Table`,
   `dcat:Distribution` and `dcat-si:Field`. Required properties, datatypes, field-type enum,
   constraints per type, closed key sets.
3. JSON-LD context generated from `data.ttl`, published at the namespace.

### sunstone-core (Rust)

| Area | Replaces | Crates |
|---|---|---|
| Model: load old/new form, context, includes, lock file | `datasets.py`, `aliases.py` | yaml-edit, serde YAML reader, sophia/oxigraph |
| Writes: register output, migrate, resolve | writer parts of `datasets.py`, `migrate.py` | yaml-edit |
| Validation: SHACL, rules, lint, licenses, vocab search, DP v2 export | `conformance.py`, `rules.py`, `lint.py`, `licenses.py`, `datasets_schema.py`, `validation.py`, `vocab_search.py` | rudof, jsonschema |
| Lineage storage and queries | data-model part of `lineage.py`, `queries.py` | |
| Storage: gs://, s3://, r2://, local, http, hashing | URL parts of `handlers*.py` | object_store (+ aws-config credential adapter) |
| Packaging, push, env | `packaging.py`, `push.py`, `env.py` | arrow/parquet schema inference (replaces frictionless) |
| Platform: `sunstone:` resolve, Iceberg, query, import | `sunstone_data` | iceberg, duckdb, calamine, arrow-csv |
| Auth: PKCE, client credentials, step-up, keyring | `sunstone_data.auth` | openidconnect, keyring, reqwest |
| CLI | `cli.py`, `sunstone_data.cli` | clap |

### sunstone-py (Python)

- pandas, polars and geopandas facades, `Asset` and derive policies, session and context (lineage
  capture at runtime, persisted through `sunstone-core`).
- Format handlers. Byte I/O goes through file-like objects from `sunstone-core` (seek as ranged
  GET, writes as multipart upload committed on `close()`).
- Tables from the platform and query results come back as Arrow streams (`pyo3-arrow`, PyCapsule
  interface).
- Zarr uses `zarr.storage.ObjectStore` over obstore, with credentials from `sunstone-core`.
- Units (pint).
- Plugin registry, reduced to format handlers.

Dependencies removed from Python: pyiceberg, s3fs, gcsfs, boto3, google-cloud-storage, frictionless,
fastexcel, httpx.

## Risks

- R1: The context marker is an unversioned namespace IRI. A changed key mapping changes the meaning
  of existing files. Mitigation: version the context with `owl:versionInfo`, pin with
  `min_sunstone_version`.
- R2: object_store cannot read `external_account` ADC (GitHub Actions workload identity federation)
  or AWS profile files. Mitigation: custom credential providers through `with_credentials`.
- R3: `rudof_lib` is 0.3.x with low adoption.
- R4: yaml-edit is 0.3.x. Comment and layout preservation for our edits is unproven.

## Spikes before planning

- S1: yaml-edit against a real `datasets.yaml`: append an output entry, migrate-style rename and
  restructure, remove an entry. Pass: bytes outside the edited spans unchanged, correct indentation.
- S2: rudof validating sample new-form documents against draft shapes. Pass: expected violations
  reported with usable paths.

## Open questions

- Q2: Drop the unprefixed legacy keys (`unit`, `source`, `scheme`, `license`) from
  `datapackage.json` now, or keep them through 2.x and drop in 3.0?
- Q4: Declare plugin field types as data (Turtle or TOML) so Rust validation can read them?
- Q5: Units: keep pint (Python) and QUDT (Rust) checks side by side, or make QUDT the only authority?
- Q7: Keep duckdb for queries, or move to DataFusion?
