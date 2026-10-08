# datasets.yaml reference

`sunstone dataset validate --strict` enforces one rule: every property key in `datasets.yaml` must be

1. a property of the [Data Package v2](https://datapackage.org/standard/data-package/) profile that matches its level (`package` and `packages[]` use Data Package, `inputs[]` and `outputs[]` use Data Resource, `fields[]` uses Table Schema field, `dialect` uses Table Dialect), or
2. a sunstone key from the tables below.

Keys containing `:` (`si:category`, `dcat:theme`, full URIs) are RDF/custom properties and are never checked, except in `dialect` blocks, which allow only the keys listed there. Values of Data Package properties are validated against the official v2 JSON Schemas (vendored in `sunstone/profiles/`).

Loading a file never applies this rule (`DatasetsManager` ignores unknown keys), except `publish.dialect`, which is checked on load. Run `--strict` in CI. `--strict` checks only the main `datasets.yaml`, not files merged via `include:`. Each message names the path, for example `outputs[2].fields[0]: unknown key 'bogus' (...)` or `package.version: 1.0 is not of type 'string'` (quote the version).

## Top level

Only sunstone keys and `:` keys. No Data Package properties here (`package:` holds those).

| Key | Meaning |
|---|---|
| `inputs`, `outputs` | Dataset lists (Data Resource level). |
| `package` | Single package metadata (Data Package level). |
| `packages` | List of package entries (Data Package level plus `datasets`). |
| `publish` | Publish block (see below). |
| `defaults` | `rdfPrefixes` and `:` keys applied to every dataset. |
| `rdfPrefixes` | Prefix to namespace map. |
| `include` | Files whose `inputs`/`outputs`/`packages` are merged in. |
| `lint` | `sunstone lint` configuration (`disable`). |
| `plugins` | Plugin configuration, keyed by plugin name. |
| `min_sunstone_version` | Managed by sunstone-py. |

## `package:` and `packages[]`

Data Package profile properties (`name`, `title`, `description`, `version`, `keywords`, `homepage`, `id`, `image`, `contributors`, `created`, `licenses`, `sources`, `$schema`) plus:

| Key | Meaning |
|---|---|
| `license` | SPDX identifier, emitted to `datapackage.json`. |
| `publish` | Publish block for this package. |
| `datasets` | `packages[]` only: slugs included in the package. |

Profile properties are emitted to `datapackage.json` as written. `name` on a singular `package:` names the data package (the project slug is the fallback). `resources` is generated and not accepted. `$schema` is accepted, but the generated descriptor always carries `https://datapackage.org/profiles/2.0/datapackage.json`. Contributor entries accept `title`, `givenName`, `familyName`, `path`, `email`, `roles`, `organization`.

## `inputs[]` and `outputs[]`

Data Resource profile properties (`description`, `format`, `title`, `encoding`, `mediatype`, `homepage`, `licenses`, `sources`, `schema`, `bytes`, `hash`, `$schema`) plus:

| Key | Meaning |
|---|---|
| `name` | Human-readable name (becomes the resource `title`). |
| `slug` | Identifier (becomes the resource `name`). |
| `location` | Path or URL of the data (becomes `path`). |
| `type` | Sunstone resource kind: `table`, `file`, `geojson`, ... Only `table` becomes the resource `type`. |
| `fields` | Table Schema fields. |
| `primaryKey` | Column(s) that identify a row, checked against the Table Schema `primaryKey` property. |
| `source` | Provenance block (see below). |
| `license` | SPDX identifier. |
| `strict` | Strict-mode flag. |
| `lineage` | Deprecated inline lineage; migrate with `sunstone dataset migrate`. |
| `rdfPrefixes` | Dataset-level prefix map. |
| `publish` | Dataset publish block. |
| `dialect` | CSV dialect (see below). |

`path` and `data` are generated from `location` and not accepted. Profile properties other than `name` and `type` pass through to the resource in `datapackage.json`.

### `source`

`name`, `location` (`data`, `metadata`, `about`), `attributedTo` (string, or `id`, `type`, `label`, `version`), `acquiredAt`, `acquisitionMethod`, `license`, `updated`, `notes`.

### `fields[]`

Table Schema field properties (`name`, `type`, `title`, `description`, `format`, `example`, `constraints`, `missingValues`, `categories`, `categoriesOrdered`, `rdfType`, `trueValues`, `falseValues`, `bareNumber`, `decimalChar`, `groupChar`; which apply depends on `type`) plus:

| Key | Meaning |
|---|---|
| `unit` | Unit of measure (Pint or QUDT). |
| `source` | Slug of the input the field comes from. |

Field properties pass through to `datapackage.json` verbatim. Only `:`-keyed RDF keys and the `rdfType` value are prefix-expanded.

`type` must be a Table Schema type (`any`, `array`, `boolean`, `date`, `datetime`, `duration`, `geojson`, `geopoint`, `integer`, `number`, `object`, `string`, `time`, `year`, `yearmonth`) or a type registered by a plugin. Geometry columns use `type: geojson` with `rdfType: geo:Geometry`. Constraints are checked against the type: `minLength` on an `integer` field is an error, as is `maxLength: "ten"`.

### `dialect` and `publish.dialect`

Only the delimited-text subset of Table Dialect: `commentChar`, `commentRows`, `delimiter`, `doubleQuote`, `escapeChar`, `header`, `headerJoin`, `headerRows`, `lineTerminator`, `nullSequence`, `quoteChar`, `skipInitialSpace`. Values follow the profile (`headerRows` is a list of integers of at least 1). `publish.dialect` is checked when the file loads; a dataset `dialect` only under `--strict`. The dataset reader uses `delimiter`, `quoteChar` and `header`.

## `publish`

At top level, on a package, or on a dataset: `true`/`false`, or a mapping with `enabled`, `to`, `flatten`, `as`, `as_name` (dataset level only), `public`, `dialect`.

## Generated `datapackage.json`

`sunstone package build` validates the descriptor it generates against the Data Package profile and prints a warning when it fails. `sunstone package push` refuses to upload a descriptor (or, for `sunstone:` namespaces, a resource) that fails the profile.
