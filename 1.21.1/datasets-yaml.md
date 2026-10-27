# Validating datasets.yaml

The allowed keys at every level are listed in the generated
[datasets.yaml key reference](datasets-yaml-reference.md). This page covers
what the validators check.

## `sunstone dataset validate`

Always checked: required keys (`title`, `name`, `path`, and `schema.fields`
for `type: table`), field types, duplicate names, SPDX license identifiers and
YAML structure. Old key names are normalized first (see the alias table in the
key reference), so old and new files are checked the same way.

`--strict` adds two checks, both on the normalized document:

1. Keys: lint rules R301 (unknown key), R302 (undeclared prefix) and R303
   (term not in a shipped vocabulary).
2. Values of Data Package properties against the official v2 JSON Schemas
   (vendored in `sunstone/profiles/`): package and resource properties,
   `schema.primaryKey` and the other Table Schema properties, and each
   `schema.fields[]` entry against the sub-schema of its `type`.
   Constraints are checked against the type: `minLength` on an `integer`
   field is an error, as is `maxLength: "ten"`.

Each message names the path, for example
`outputs[2].schema.fields[0].bogus: [R301] unknown key 'bogus' at level 'field'`
or `package.version: 1.0 is not of type 'string'` (quote the version).
`--strict` checks only the main `datasets.yaml`, not files merged via
`include:`; `sunstone lint` covers those. With `--dataset` or positional
names, only those datasets are checked. Run `--strict` in CI.

## Field types

`type` must be a Table Schema type (`any`, `array`, `boolean`, `date`,
`datetime`, `duration`, `geojson`, `geopoint`, `integer`, `number`, `object`,
`string`, `time`, `year`, `yearmonth`) or a type registered by a plugin.
Geometry columns use `type: geojson` with `rdfType: geo:Geometry`.

## `dialect` and `publish.dialect`

Only the delimited-text subset of Table Dialect is accepted: `commentChar`,
`commentRows`, `delimiter`, `doubleQuote`, `escapeChar`, `header`,
`headerJoin`, `headerRows`, `lineTerminator`, `nullSequence`, `quoteChar`,
`skipInitialSpace`. Prefixed keys are rejected too. `publish.dialect` is
checked when the file loads, a dataset `dialect` only under `--strict`.

## Generated `datapackage.json`

`sunstone package build` validates the descriptor it generates against the
Data Package profile and prints a warning when it fails. `sunstone package
push` refuses to upload a descriptor (or, for `sunstone:` namespaces, a
resource) that fails the profile. Both also run the conformance rules on the
descriptor and warn on MUST violations.
