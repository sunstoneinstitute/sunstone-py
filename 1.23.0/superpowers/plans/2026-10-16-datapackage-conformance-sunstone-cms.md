# Datapackage Conformance (sunstone-cms, C12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The CMS import reads the new IRI keys that sunstone-py 1.20 emits in `datapackage.json` (methodology, field unit/source, structured source parts) while keeping the old keys as fallbacks, stores the source parts on `tableSources`, and renders a source at three levels of detail (compact, standard, full) with the templates from sunstone-cms issue #610.

**Architecture:** Four pure functions already isolate the key matching: `extractSchema` and `extractTableSources` in `src/collections/DataPackages/endpoints/import.ts`, `toSourceRecords` in `src/utilities/datasets/sourcesFromSchemaFields.ts`, and `getMethodology` in `src/services/data/methodology-service.ts`. Each gains the new IRI with the old key as fallback. `toSourceRecords` stores every part of a source (identifier, title, publisher full and short name, creators, year, container, citation, links, license, legacy attribution) as plain keys on a `DatasetSourceRecord`; a new module `renderSource.ts` turns a record into display text at a chosen level, and `normalizeSources` / `resolveDatasetSources` call it, so every existing consumer (`Sources`, `DownloadLink`, the visual embeds) keeps receiving `{ title, url }`. A new exported `methodologyFilenameOf` lifts the package-level methodology lookup out of `runImport` so it is testable. All new values land in existing `json` columns; no DB migration.

**Tech Stack:** TypeScript, Payload CMS 3, Vitest (`npx vitest run <file>`), ESLint (`npm run lint`), `npx tsc --noEmit` for type checking.

**Spec:** `docs/superpowers/specs/2026-10-15-datapackage-conformance-design.md` in sunstone-py (sections "Source references", "C12. sunstone-cms" and "C5. Write hook" for the emitted keys) and sunstone-cms issue #610 (`gh issue view 610 -R sunstoneinstitute/sunstone-cms`) for the render templates. #610 is a draft the author may still edit; this plan follows its text as of 2026-10-16 (field table, three levels, templates, fallbacks). Re-read the issue before Task 3b and apply any edits to the templates there, not to the stored parts.

## Spec conflicts and open questions

- **SC1. No old key exists for source attribution or license.** Spec C12.3 says "each keeping the old key as a fallback", but sunstone-py never emitted an attribution or license key on `datapackage.json` sources (only `title`, `path`, `dcat:*`, `dct:publisher`). Resolution: read the IRIs only; plain `attributedTo`/`license` on a source object stay ignored (the existing test "reads a singular source object with a name and location" pins that).
- **SC2. `MethodologyResponse.sources` shape changes on the public endpoint.** `/api/data/data-package/:slug/methodology` returns `sources` in the old `datasets.yaml` shape (`name`, `location`, `attributedTo`). No frontend component renders it (`DataPackageTabs.tsx` declares the type, uses only `resources`). Resolution: change the response to `DatasetSourceRecord[]` as the spec says, update the frontend type and `context/data-api.md`. A consumer renders the full level with `renderSource(record, 'full')`.
- **SC3. #610 question 3 (store parts, or rendered strings per level) is open.** Resolution: store the parts on `tableSources` (no migration, `jsonb`) and render at display time, which is what C12.3 says. If the author answers "rendered strings", add the three strings next to the parts at import time in Task 3b; nothing else changes. Flagged in the PR.
- **SC4. #610 question 1 (where each level is used) is open, and the CMS has no dataset page.** Pages today: `datapackages/[slug]` (resources list through `DownloadLink`), visual embeds (`Sources` component), the methodology endpoint. Resolution: the resources list and the embeds render compact; the methodology endpoint returns records (full is rendered by whoever displays them); standard is implemented and tested but wired nowhere until a dataset page exists. Flagged in the PR.
- **SC5. `{link}` order in #610 differs from the CMS's `sourceLink`.** #610: `@id`, landing page, download URL, `path`. `sourceLink` today: `url`, landing page, `path`, download URL, `location`. Resolution: records follow #610 (`id`, `landingPage`, `downloadURL`, `path`, then legacy `url`/`location`); field-level sources (`toDatasetSource`, not restructured by sunstone-py) keep today's order. Every existing `normalizeSources` test still passes because its fixtures have `path === downloadURL` or only one of them.

## Global Constraints

- Repo: `~/git/sunstone/sunstone-cms`. Start from a fresh `origin/main` (`ee9bd884` at planning time): `git fetch origin && git switch -c feature/datapackage-iri-keys origin/main && npm install`.
- Lands before sunstone-py 2.0 (spec Scope); independent of sunstone-py 1.20.
- Every IRI is matched literally (no JSON-LD context). Spell them exactly as below.
- Keep old keys as fallbacks: no existing test expectation changes except where this plan says so.
- Per task: `npx vitest run <changed test files>`, `npm run lint`, `npx tsc --noEmit` before commit.
- Commit messages: conventional prefix, no Co-authored-by lines.

## IRIs

| Constant | Value |
|---|---|
| `SI_METHODOLOGY` | `https://sunstone.institute/rdf/vocab#methodology` |
| `DCAT_SI_METHODOLOGY` | `https://sunstone.institute/rdf/data#methodology` |
| `SI_UNIT` | `https://sunstone.institute/rdf/vocab#unit` |
| `SI_SOURCE_FIELD` | `https://sunstone.institute/rdf/vocab#sourceField` |
| `QUDT_HAS_UNIT` | `http://qudt.org/schema/qudt/hasUnit` |
| `PROV_WAS_ATTRIBUTED_TO` | `http://www.w3.org/ns/prov#wasAttributedTo` |
| `RDFS_LABEL` | `http://www.w3.org/2000/01/rdf-schema#label` |
| `SKOS_ALT_LABEL` | `http://www.w3.org/2004/02/skos/core#altLabel` |
| `DC_PUBLISHER` | `http://purl.org/dc/terms/publisher` (exists) |
| `DC_CREATOR` | `http://purl.org/dc/terms/creator` |
| `DC_ISSUED` | `http://purl.org/dc/terms/issued` |
| `DC_IS_PART_OF` | `http://purl.org/dc/terms/isPartOf` |
| `DC_BIBLIOGRAPHIC_CITATION` | `http://purl.org/dc/terms/bibliographicCitation` |
| `DC_LICENSE` | `http://purl.org/dc/terms/license` |
| `DCAT_LANDING_PAGE`, `DCAT_DOWNLOAD_URL` | exist |

## Source record shape (Task 3) and render levels (Task 3b)

`DatasetSourceRecord` after Task 3 (all optional; undefined keys are dropped before storage):

| Key | From `datapackage.json` | #610 part |
|---|---|---|
| `id` | `@id` | Identifier (DOI) |
| `title` | `title`, else `name` | Work title |
| `publisher` | `dct:publisher` node `rdfs:label`; legacy string or `{name|title}` | Publisher full name |
| `publisherShort` | `dct:publisher` node `skos:altLabel` | Publisher short name |
| `publisherId` | `dct:publisher` node `@id` | (kept, not rendered) |
| `creators` | `dct:creator` list, each node's `rdfs:label` (strings accepted) | Authors |
| `issued` | `dct:issued` (string or number, stored as string) | Year |
| `container` | `dct:isPartOf` node `rdfs:label` (string accepted) | Container |
| `citation` | `dct:bibliographicCitation` | Full citation |
| `attribution` | `prov:wasAttributedTo` string, or node `rdfs:label` | Legacy attribution |
| `license` | `dct:license` | License |
| `url`, `path`, `landingPage`, `downloadURL`, `location` | as today | Links |

A record is kept when it has at least one of `title`, `publisher`, `creators`, `attribution`. `toSourceRecords` is idempotent on stored records (it reads its own plain keys first).

Templates (from #610, verbatim), `[ ... ]` is dropped with its punctuation when a placeholder inside is missing:

| Level | Template | Link |
|---|---|---|
| compact | `{attribution}[ ({year})]` | `{link}` |
| standard | `{title}[ · {attribution}][, {year}]` | `{link}` |
| full | `citation` if present, else `{author}.[ ({year}).] {title}.[ {container}.][ {link}]` | none (the link is in the text) |

Placeholders: `{creatorsShort}` surname of one creator, two joined with ` & `, three or more as first surname + ` et al.`; `{creators}` all labels joined with `, `, the last with ` & `; `{publisher}` short name else full name; `{publisherFull}` full name; `{attribution}` `{creatorsShort}` when there are creators, else `{publisher}`; `{author}` `{creators}` when present, else `{publisherFull}`; `{year}` first four characters of `issued`; `{link}` first of `id`, `landingPage`, `downloadURL`, `path`, `url`, `location.web`, `location.data`, `location` (string). Fallbacks: no creators and no publisher, compact uses `title` and standard drops the attribution segment; no title either, every level uses the `attribution` text; full with no author uses the title as the first segment. Segments are joined without doubling a period (`Ytrestoyl, T.` + ` (2022).`, not `Ytrestoyl, T.. (2022).`).

## File map

| File | Responsibility |
|---|---|
| `src/types/data-packages.d.ts` | `DataPackageJSON` gains the `data#methodology` key |
| `src/types/data-transforms.d.ts` | `DatasetSourceRecord` gains the source parts; `SourceDetail` type |
| `src/collections/DataPackages/endpoints/import.ts` | `methodologyFilenameOf`, `extractSchema` IRI mapping + `unitIri` |
| `src/collections/DataPackages/endpoints/import.test.ts` | Unit tests; 1.20 and 2.0 fixtures import identically |
| `src/utilities/datasets/sourcesFromSchemaFields.ts` | `toSourceRecords` stores the parts; `normalizeSources`/`resolveDatasetSources` take a level |
| `src/utilities/datasets/sourcesFromSchemaFields.test.ts` | Tests for the above |
| `src/utilities/datasets/renderSource.ts` | `renderSource(record, level)`, `toDatasetSourceAt`, placeholder helpers |
| `src/utilities/datasets/renderSource.test.ts` | The #610 rendered table as tests |
| `src/services/data/methodology-service.ts` | Package sources as `DatasetSourceRecord[]` |
| `src/services/data/methodology-service.test.ts` | New |
| `src/app/(frontend)/datapackages/[slug]/DataPackageTabs.tsx` | `MethodologyResponse.sources` type |
| `src/collections/Datasets/index.ts` | `schema` and `tableSources` admin descriptions |
| `context/data-api.md` | Methodology endpoint sample |

---

### Task 1: Package methodology under the new IRI

**Files:**
- Modify: `src/types/data-packages.d.ts` (`DataPackageJSON`, line ~15)
- Modify: `src/collections/DataPackages/endpoints/import.ts` (constants after `DC_SOURCE` line ~26; `runImport` line ~154)
- Test: `src/collections/DataPackages/endpoints/import.test.ts`

**Interfaces:**
- Produces: `export function methodologyFilenameOf(json: Pick<DataPackageJSON, typeof SI_METHODOLOGY | typeof DCAT_SI_METHODOLOGY>): string | undefined` in `import.ts`; exported constants `SI_METHODOLOGY`, `DCAT_SI_METHODOLOGY`.

- [ ] **Step 1: Write the failing test**

Append to `src/collections/DataPackages/endpoints/import.test.ts` (extend the import line to `import { extractSchema, extractTableSources, methodologyFilenameOf } from './import'`):

```ts
describe('methodologyFilenameOf', () => {
  const NEW = 'https://sunstone.institute/rdf/data#methodology'
  const OLD = 'https://sunstone.institute/rdf/vocab#methodology'

  it('prefers the dcat-si IRI', () => {
    expect(methodologyFilenameOf({ [NEW]: 'METHODOLOGY.md', [OLD]: 'old.md' })).toBe('METHODOLOGY.md')
  })

  it('falls back to the vocab IRI', () => {
    expect(methodologyFilenameOf({ [OLD]: 'old.md' })).toBe('old.md')
  })

  it('is undefined when neither key is present or both are empty', () => {
    expect(methodologyFilenameOf({})).toBeUndefined()
    expect(methodologyFilenameOf({ [NEW]: '', [OLD]: '' })).toBeUndefined()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/collections/DataPackages/endpoints/import.test.ts`
Expected: FAIL, `methodologyFilenameOf is not a function` (or a TypeScript import error).

- [ ] **Step 3: Add the type key**

In `src/types/data-packages.d.ts`, `DataPackageJSON`, after the existing `'https://sunstone.institute/rdf/vocab#methodology'?: string` line add:

```ts
  'https://sunstone.institute/rdf/data#methodology'?: string
```

- [ ] **Step 4: Implement**

In `import.ts`, after `const DC_SOURCE = ...`:

```ts
export const SI_METHODOLOGY = 'https://sunstone.institute/rdf/vocab#methodology'
export const DCAT_SI_METHODOLOGY = 'https://sunstone.institute/rdf/data#methodology'

/**
 * Package-level methodology path or URL: the dcat-si IRI (sunstone-py >= 1.20),
 * else the older vocab IRI (dropped by sunstone-py 2.0). Empty strings count as absent.
 */
export function methodologyFilenameOf(
  json: Pick<DataPackageJSON, typeof SI_METHODOLOGY | typeof DCAT_SI_METHODOLOGY>,
): string | undefined {
  const value = json[DCAT_SI_METHODOLOGY] || json[SI_METHODOLOGY]
  return value && value.trim() ? value : undefined
}
```

In `runImport`, replace

```ts
    const methodologyFilename = json['https://sunstone.institute/rdf/vocab#methodology']
```

with

```ts
    const methodologyFilename = methodologyFilenameOf(json)
```

- [ ] **Step 5: Run tests, lint, types, commit**

Run: `npx vitest run src/collections/DataPackages/endpoints/import.test.ts && npm run lint && npx tsc --noEmit`
Expected: all pass.

```bash
git add src/types/data-packages.d.ts src/collections/DataPackages/endpoints/import.ts src/collections/DataPackages/endpoints/import.test.ts
git commit -m "feat(import): read package methodology from the dcat-si IRI"
```

---

### Task 2: Field schema reads `si:unit`, `si:sourceField` and `qudt:hasUnit` IRIs

**Files:**
- Modify: `src/collections/DataPackages/endpoints/import.ts` (`extractSchema`, lines ~28-53)
- Modify: `src/collections/Datasets/index.ts` (`schema` field `admin.description`, line ~96)
- Modify: `src/payload-types.ts` (regenerated, or the matching doc comment)
- Test: `src/collections/DataPackages/endpoints/import.test.ts`

**Interfaces:**
- Produces: `extractSchema` output objects may carry `unitIri: string` (QUDT unit IRI). `unit` and `source` come from the IRI keys when present, else the short keys (`source` still falls back to `dct:source`).

- [ ] **Step 1: Write the failing tests**

Add inside the existing `describe('extractSchema', ...)` block:

```ts
  const SI_UNIT = 'https://sunstone.institute/rdf/vocab#unit'
  const SI_SOURCE_FIELD = 'https://sunstone.institute/rdf/vocab#sourceField'
  const QUDT_HAS_UNIT = 'http://qudt.org/schema/qudt/hasUnit'

  it('reads unit and source from the si IRIs, before the short keys', () => {
    const fields = extractSchema({ schema: { fields: [
      { name: 'area', type: 'number', unit: 'old', source: 'old_col', [SI_UNIT]: 'km**2', [SI_SOURCE_FIELD]: 'raw_area' },
    ] } })
    expect(fields).toEqual([{ name: 'area', type: 'number', unit: 'km**2', source: 'raw_area' }])
  })

  it('keeps the short unit and source keys when the IRIs are absent', () => {
    const fields = extractSchema({ schema: { fields: [{ name: 'area', unit: 'km**2', source: 'raw_area' }] } })
    expect(fields).toEqual([{ name: 'area', unit: 'km**2', source: 'raw_area' }])
  })

  it('stores qudt:hasUnit as unitIri when present', () => {
    const fields = extractSchema({ schema: { fields: [
      { name: 'area', [SI_UNIT]: 'km**2', [QUDT_HAS_UNIT]: 'http://qudt.org/vocab/unit/KiloM2' },
      { name: 'count', [QUDT_HAS_UNIT]: '' },
    ] } })
    expect(fields).toEqual([
      { name: 'area', unit: 'km**2', unitIri: 'http://qudt.org/vocab/unit/KiloM2' },
      { name: 'count' },
    ])
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/collections/DataPackages/endpoints/import.test.ts`
Expected: the three new tests FAIL (`unit: 'old'`, no `unitIri`).

- [ ] **Step 3: Implement**

In `import.ts`, after the methodology constants from Task 1:

```ts
const SI_UNIT = 'https://sunstone.institute/rdf/vocab#unit'
const SI_SOURCE_FIELD = 'https://sunstone.institute/rdf/vocab#sourceField'
const QUDT_HAS_UNIT = 'http://qudt.org/schema/qudt/hasUnit'
```

Replace the `extractSchema` doc comment and body with:

```ts
/**
 * Extracts only the allowed schema fields (name, type, description, unit, unitIri,
 * source, label, title) from a Frictionless Data resource schema. `unit` and
 * `source` come from the sunstone IRIs (`vocab#unit`, `vocab#sourceField`,
 * sunstone-py >= 1.20) when present, else the short keys; `source` also falls
 * back to the Dublin Core source. `unitIri` is the QUDT unit (`qudt:hasUnit`).
 * `title` comes from the Dublin Core title when present, else the Frictionless `title`.
 */
export function extractSchema(resource: { schema?: { fields?: DataPackageResourceSchemaField[] } }) {
  if (!resource.schema?.fields) return undefined

  const allowedKeys = ['name', 'type', 'description', 'unit', 'source', 'label'] as const
  return resource.schema.fields.map((field) => {
    const picked: Record<string, unknown> = {}
    for (const key of allowedKeys) {
      if (field[key] !== undefined) {
        picked[key] = field[key]
      }
    }
    if (field[SI_UNIT] !== undefined) {
      picked.unit = field[SI_UNIT]
    }
    if (field[SI_SOURCE_FIELD] !== undefined) {
      picked.source = field[SI_SOURCE_FIELD]
    } else if (picked.source === undefined && field[DC_SOURCE] !== undefined) {
      picked.source = field[DC_SOURCE]
    }
    const unitIri = field[QUDT_HAS_UNIT]
    if (typeof unitIri === 'string' && unitIri.trim()) {
      picked.unitIri = unitIri
    }
    const title = field[DC_TITLE] ?? field.title
    if (typeof title === 'string' && title.trim()) {
      picked.title = title
    }
    return picked
  })
}
```

- [ ] **Step 4: Document `unitIri` on the Datasets collection**

In `src/collections/Datasets/index.ts`, the `schema` field: change the description to

```ts
        description: 'Column schema (name, type, description, unit, unitIri, source, label, title) from the data package',
```

Run `npm run generate:types`. If it fails because no database or env is available, instead edit the matching doc comment above `schema?:` in `src/payload-types.ts` (search for `Column schema (name, type, description, unit, source, label)`) to the new text by hand. Either way `src/payload-types.ts` ends up with the new description and no other diff.

- [ ] **Step 5: Run tests, lint, types, commit**

Run: `npx vitest run src/collections/DataPackages/endpoints/import.test.ts && npm run lint && npx tsc --noEmit`
Expected: all pass (the five pre-existing `extractSchema` tests still pass).

```bash
git add src/collections/DataPackages/endpoints/import.ts src/collections/DataPackages/endpoints/import.test.ts src/collections/Datasets/index.ts src/payload-types.ts
git commit -m "feat(import): read field unit and source from sunstone IRIs, store qudt:hasUnit as unitIri"
```

---

### Task 3: Source records store the structured parts

**Files:**
- Modify: `src/types/data-transforms.d.ts` (`DatasetSourceRecord`, lines ~17-27)
- Modify: `src/utilities/datasets/sourcesFromSchemaFields.ts` (constants lines ~11-13; `sourcePublisher` lines ~15-30; `toSourceRecords` lines ~99-120)
- Modify: `src/collections/Datasets/index.ts` (`tableSources` field `admin.description`, line ~113) and the matching comment in `src/payload-types.ts`
- Test: `src/utilities/datasets/sourcesFromSchemaFields.test.ts`

**Interfaces:**
- Produces: `DatasetSourceRecord` with the keys in "Source record shape" above; `toSourceRecords(input: unknown): DatasetSourceRecord[]` stores them and is idempotent on its own output. `normalizeSources` and display are unchanged in this task (Task 3b wires the renderer).

- [ ] **Step 1: Write the failing tests**

Append to `sourcesFromSchemaFields.test.ts`:

```ts
describe('structured source parts (sunstone-py >= 1.20, sunstone-cms#610)', () => {
  const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
  const SKOS_ALT_LABEL = 'http://www.w3.org/2004/02/skos/core#altLabel'
  const DCT = 'http://purl.org/dc/terms/'
  const PROV_WAS_ATTRIBUTED_TO = 'http://www.w3.org/ns/prov#wasAttributedTo'
  const DOI = 'https://doi.org/10.1016/j.aqrep.2022.101316'

  const paper = {
    '@id': DOI,
    title: 'Utilization of feed resources in the production of Atlantic salmon (Salmo salar) in Norway: An update for 2020',
    path: DOI,
    [`${DCT}publisher`]: { [RDFS_LABEL]: 'Elsevier' },
    [`${DCT}creator`]: [{ [RDFS_LABEL]: 'Aas, T. S.' }, { [RDFS_LABEL]: 'Asgard, T. E.' }, { [RDFS_LABEL]: 'Ytrestoyl, T.' }],
    [`${DCT}issued`]: '2022',
    [`${DCT}isPartOf`]: { [RDFS_LABEL]: 'Aquaculture Reports 26, 101316' },
    [`${DCT}license`]: 'CC-BY-NC-ND-4.0',
  }

  const fao = {
    title: 'FAOSTAT QCL Crops and livestock products',
    path: 'https://www.fao.org/faostat/en/#data/QCL',
    'http://www.w3.org/ns/dcat#landingPage': 'https://www.fao.org/faostat/en/#data/QCL',
    [`${DCT}publisher`]: {
      '@id': 'https://www.wikidata.org/entity/Q82151',
      [RDFS_LABEL]: 'Food and Agriculture Organization of the United Nations',
      [SKOS_ALT_LABEL]: 'FAO',
    },
  }

  it('stores every part of a journal article', () => {
    expect(toSourceRecords([paper])).toEqual([{
      id: DOI,
      title: paper.title,
      path: DOI,
      publisher: 'Elsevier',
      creators: ['Aas, T. S.', 'Asgard, T. E.', 'Ytrestoyl, T.'],
      issued: '2022',
      container: 'Aquaculture Reports 26, 101316',
      license: 'CC-BY-NC-ND-4.0',
    }])
  })

  it('stores the publisher full name, short name and IRI', () => {
    expect(toSourceRecords([fao])).toEqual([{
      title: 'FAOSTAT QCL Crops and livestock products',
      path: 'https://www.fao.org/faostat/en/#data/QCL',
      landingPage: 'https://www.fao.org/faostat/en/#data/QCL',
      publisher: 'Food and Agriculture Organization of the United Nations',
      publisherShort: 'FAO',
      publisherId: 'https://www.wikidata.org/entity/Q82151',
    }])
  })

  it('keeps the legacy attribution text and a citation', () => {
    expect(toSourceRecords([{
      title: 'X',
      [PROV_WAS_ATTRIBUTED_TO]: 'Aas, T. S.; Asgard, T. E. (Nofima); published by Elsevier in Aquaculture Reports',
      [`${DCT}bibliographicCitation`]: 'Aas, T. S. & Asgard, T. E. (2022). X. Aquaculture Reports 26.',
    }])).toEqual([{
      title: 'X',
      attribution: 'Aas, T. S.; Asgard, T. E. (Nofima); published by Elsevier in Aquaculture Reports',
      citation: 'Aas, T. S. & Asgard, T. E. (2022). X. Aquaculture Reports 26.',
    }])
  })

  it('reads the rdfs:label of a prov:wasAttributedTo node object', () => {
    expect(toSourceRecords([{
      title: 'Census',
      [PROV_WAS_ATTRIBUTED_TO]: { '@id': 'https://www.ons.gov.uk', '@type': 'http://www.w3.org/ns/prov#Organization', [RDFS_LABEL]: 'ONS' },
    }])).toEqual([{ title: 'Census', attribution: 'ONS' }])
  })

  it('keeps a source that only has an attribution, and drops one with nothing to show', () => {
    expect(toSourceRecords([{ [PROV_WAS_ATTRIBUTED_TO]: 'FAO' }])).toEqual([{ attribution: 'FAO' }])
    expect(toSourceRecords([{ path: 'https://x', [`${DCT}license`]: 'CC0-1.0' }])).toEqual([])
  })

  it('accepts creators and a container as plain strings, and a numeric year', () => {
    expect(toSourceRecords([{ title: 'X', [`${DCT}creator`]: 'Aas, T. S.', [`${DCT}isPartOf`]: 'Journal 1', [`${DCT}issued`]: 2022 }]))
      .toEqual([{ title: 'X', creators: ['Aas, T. S.'], container: 'Journal 1', issued: '2022' }])
  })

  it('ignores a publisher node without a label, an unlabeled creator and an empty license', () => {
    expect(toSourceRecords([{ title: 'X', [`${DCT}publisher`]: { '@id': 'https://e.org' }, [`${DCT}creator`]: [{ '@id': 'https://p' }], [`${DCT}license`]: '' }]))
      .toEqual([{ title: 'X' }])
  })

  it('is idempotent on stored records', () => {
    const stored = toSourceRecords([paper, fao, { title: 'X', [PROV_WAS_ATTRIBUTED_TO]: 'FAO' }])
    expect(toSourceRecords(stored)).toEqual(stored)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/utilities/datasets/sourcesFromSchemaFields.test.ts`
Expected: the eight new tests FAIL (no `id`/`creators`/`attribution` keys; the attribution-only case returns `[]`).

- [ ] **Step 3: Extend the record type**

In `src/types/data-transforms.d.ts`, replace the `DatasetSourceRecord` interface and its doc comment with:

```ts
/** Level of detail for rendering a source (sunstone-cms#610). */
export type SourceDetail = 'compact' | 'standard' | 'full'

/**
 * A table-level source as stored on a dataset (`tableSources`): the structured
 * parts sunstone-py emits (sunstone-cms#610) plus every link. Rendered at
 * display time by `renderSource`; `url`/`location` are legacy link keys.
 */
export interface DatasetSourceRecord {
  /** `@id`: DOI as https://doi.org/<doi>, or another persistent IRI. */
  id?: string
  title?: string
  /** Publisher full name (`rdfs:label` of `dct:publisher`). */
  publisher?: string
  /** Publisher short name (`skos:altLabel`), e.g. FAO. */
  publisherShort?: string
  /** Publisher IRI (`@id` of `dct:publisher`). */
  publisherId?: string
  /** Author labels (`rdfs:label` of each `dct:creator`). */
  creators?: string[]
  /** `dct:issued`: a year or a full date, as a string. */
  issued?: string
  /** Container label (`dct:isPartOf`), e.g. "Aquaculture Reports 26, 101316". */
  container?: string
  /** `dct:bibliographicCitation`. */
  citation?: string
  /** `prov:wasAttributedTo` free text, kept so unstructured sources are not lost. */
  attribution?: string
  /** `dct:license` SPDX id. */
  license?: string
  url?: string
  path?: string
  landingPage?: string
  downloadURL?: string
  location?: string | { web?: string; data?: string }
}
```

- [ ] **Step 4: Implement**

In `sourcesFromSchemaFields.ts`, replace the three constants and `sourcePublisher` with:

```ts
const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
const SKOS_ALT_LABEL = 'http://www.w3.org/2004/02/skos/core#altLabel'
const DC_PUBLISHER = 'http://purl.org/dc/terms/publisher'
const DC_CREATOR = 'http://purl.org/dc/terms/creator'
const DC_ISSUED = 'http://purl.org/dc/terms/issued'
const DC_IS_PART_OF = 'http://purl.org/dc/terms/isPartOf'
const DC_BIBLIOGRAPHIC_CITATION = 'http://purl.org/dc/terms/bibliographicCitation'
const DC_LICENSE = 'http://purl.org/dc/terms/license'
const PROV_WAS_ATTRIBUTED_TO = 'http://www.w3.org/ns/prov#wasAttributedTo'
const DCAT_LANDING_PAGE = 'http://www.w3.org/ns/dcat#landingPage'
const DCAT_DOWNLOAD_URL = 'http://www.w3.org/ns/dcat#downloadURL'

const isNode = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

/**
 * A label from a string, or from a JSON-LD node's `rdfs:label` (legacy
 * objects: `name`, then `title`).
 */
function labelOf(value: unknown): string | undefined {
  if (nonEmptyString(value)) return value
  if (isNode(value)) {
    for (const key of [RDFS_LABEL, 'name', 'title']) {
      const candidate = value[key]
      if (nonEmptyString(candidate)) return candidate
    }
  }
  return undefined
}

const nodeString = (value: unknown, key: string): string | undefined =>
  isNode(value) && nonEmptyString(value[key]) ? value[key] : undefined

const scalarString = (value: unknown): string | undefined =>
  nonEmptyString(value) ? value : typeof value === 'number' ? String(value) : undefined

/** Reads a source's publisher label (Dublin Core `publisher`, else a plain `publisher`). */
function sourcePublisher(source: Record<string, unknown>): string | undefined {
  return labelOf(source[DC_PUBLISHER] ?? source.publisher)
}
```

(`sourceLink`, `toDatasetSource`, `dedupeByTitle`, `normalizeSources`, `sourcesFromSchemaFields`, `resolveDatasetSources` are unchanged in this task.) Replace `toSourceRecords` with:

```ts
/**
 * Converts a table-level (Frictionless resource) source value — a string, an
 * object, or an array of either — into records for storage: the structured
 * parts sunstone-py emits (identifier, title, publisher full and short name,
 * creators, year, container, citation, legacy attribution, license) and every
 * link, read from the Dublin Core / DCAT / PROV IRIs into plain keys. Reads its
 * own plain keys first, so stored records pass through unchanged. Entries with
 * no title, publisher, creators or attribution are dropped.
 */
export function toSourceRecords(input: unknown): DatasetSourceRecord[] {
  const items = Array.isArray(input) ? input : [input]
  return items.flatMap((item): DatasetSourceRecord[] => {
    if (nonEmptyString(item)) return [{ title: item }]
    if (!isNode(item)) return []
    const source = item
    const { location } = source
    const publisher = source[DC_PUBLISHER] ?? source.publisher
    const publisherLabel = labelOf(publisher)
    const creatorsRaw = source.creators ?? source[DC_CREATOR]
    const creators = (Array.isArray(creatorsRaw) ? creatorsRaw : creatorsRaw === undefined ? [] : [creatorsRaw])
      .map(labelOf)
      .filter(nonEmptyString)
    const record: DatasetSourceRecord = {
      id: [source.id, source['@id']].find(nonEmptyString),
      title: [source.title, source.name].find(nonEmptyString),
      publisher: publisherLabel,
      // Short name and IRI only make sense next to a label; a node without rdfs:label is ignored whole.
      publisherShort: publisherLabel ? [source.publisherShort, nodeString(publisher, SKOS_ALT_LABEL)].find(nonEmptyString) : undefined,
      publisherId: publisherLabel ? [source.publisherId, nodeString(publisher, '@id')].find(nonEmptyString) : undefined,
      creators: creators.length > 0 ? creators : undefined,
      issued: [source.issued, source[DC_ISSUED]].map(scalarString).find(nonEmptyString),
      container: [source.container, labelOf(source[DC_IS_PART_OF])].find(nonEmptyString),
      citation: [source.citation, source[DC_BIBLIOGRAPHIC_CITATION]].find(nonEmptyString),
      attribution: [source.attribution, labelOf(source[PROV_WAS_ATTRIBUTED_TO])].find(nonEmptyString),
      license: [source.license, source[DC_LICENSE]].find(nonEmptyString),
      url: [source.url].find(nonEmptyString),
      path: [source.path].find(nonEmptyString),
      landingPage: [source[DCAT_LANDING_PAGE], source.landingPage].find(nonEmptyString),
      downloadURL: [source[DCAT_DOWNLOAD_URL], source.downloadURL].find(nonEmptyString),
      location: nonEmptyString(location) || isNode(location) ? (location as DatasetSourceRecord['location']) : undefined,
    }
    if (!record.title && !record.publisher && !record.creators && !record.attribution) return []
    return [Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined)) as DatasetSourceRecord]
  })
}
```

- [ ] **Step 5: Admin description**

In `src/collections/Datasets/index.ts`, the `tableSources` field description becomes:

```ts
        description: 'Table-level source(s), synced from the data package resource\'s `sources` on import, as structured parts: id (DOI), title, publisher, publisherShort, creators, issued, container, citation, attribution, license, path, landingPage, downloadURL. Rendered compact (e.g. "Aas et al. (2022)", "FAO") in lists; used for schema fields that have no source of their own.',
```

Run `npm run generate:types`, or edit the matching doc comment above `tableSources?:` in `src/payload-types.ts` by hand (same rule as Task 2 Step 4).

- [ ] **Step 6: Run tests, lint, types, commit**

Run: `npx vitest run src/utilities/datasets/sourcesFromSchemaFields.test.ts src/collections/DataPackages/endpoints/import.test.ts && npm run lint && npx tsc --noEmit`
Expected: all pass, including every pre-existing test in both files (the stored-records display test still shows `USDA NASS` because `normalizeSources` still reads `publisher`).

```bash
git add src/types/data-transforms.d.ts src/utilities/datasets/sourcesFromSchemaFields.ts src/utilities/datasets/sourcesFromSchemaFields.test.ts src/collections/Datasets/index.ts src/payload-types.ts
git commit -m "feat(sources): store structured source parts on tableSources"
```

---

### Task 3b: Render a source at compact, standard or full detail (#610 templates)

**Files:**
- Create: `src/utilities/datasets/renderSource.ts`, `src/utilities/datasets/renderSource.test.ts`
- Modify: `src/utilities/datasets/sourcesFromSchemaFields.ts` (`normalizeSources`, `resolveDatasetSources`)
- Test: `src/utilities/datasets/sourcesFromSchemaFields.test.ts`

**Interfaces:**
- Consumes: Task 3 `DatasetSourceRecord`, `SourceDetail`, `toSourceRecords`.
- Produces (`renderSource.ts`):
  ```ts
  export interface RenderedSource { text: string; link?: string }
  export function surname(label: string): string                 // "Aas, T. S." -> "Aas"; "Tor Aas" -> "Aas"; "FAO" -> "FAO"
  export function creatorsShort(creators: string[]): string      // "Aas" | "Aas & Asgard" | "Aas et al."
  export function creatorsLong(creators: string[]): string       // "A, B & C"
  export function recordLink(record: DatasetSourceRecord): string | undefined
  export function renderSource(record: DatasetSourceRecord, level: SourceDetail): RenderedSource
  export function toDatasetSourceAt(record: DatasetSourceRecord, level: SourceDetail): DatasetSource   // { title: text, url?: link }
  ```
  and in `sourcesFromSchemaFields.ts`: `normalizeSources(input: unknown, level: SourceDetail = 'compact')`, `resolveDatasetSources({ override, tableSources, fields, level = 'compact' })`.

Before writing code, re-read #610 (`gh issue view 610 -R sunstoneinstitute/sunstone-cms`). If its templates or placeholders differ from the "Source record shape and render levels" section above, follow the issue and adjust the expected strings below to match; do not change which parts are stored.

- [ ] **Step 1: Write the failing tests `src/utilities/datasets/renderSource.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import type { DatasetSourceRecord } from '@/types/data-transforms'
import { creatorsLong, creatorsShort, recordLink, renderSource, surname, toDatasetSourceAt } from './renderSource'

const DOI = 'https://doi.org/10.1016/j.aqrep.2022.101316'
const TITLE = 'Utilization of feed resources in the production of Atlantic salmon (Salmo salar) in Norway: An update for 2020'

// The two sources rendered in sunstone-cms#610.
const paper: DatasetSourceRecord = {
  id: DOI,
  title: TITLE,
  publisher: 'Elsevier',
  creators: ['Aas, T. S.', 'Asgard, T. E.', 'Ytrestoyl, T.'],
  issued: '2022',
  container: 'Aquaculture Reports 26, 101316',
  license: 'CC-BY-NC-ND-4.0',
}
const fao: DatasetSourceRecord = {
  title: 'FAOSTAT QCL Crops and livestock products',
  publisher: 'Food and Agriculture Organization of the United Nations',
  publisherShort: 'FAO',
  path: 'https://www.fao.org/faostat/en/#data/QCL',
  landingPage: 'https://www.fao.org/faostat/en/#data/QCL',
}

describe('placeholders', () => {
  it('surname', () => {
    expect(surname('Aas, T. S.')).toBe('Aas')
    expect(surname('Tor Aas')).toBe('Aas')
    expect(surname('FAO')).toBe('FAO')
  })
  it('creatorsShort', () => {
    expect(creatorsShort(['Aas, T. S.'])).toBe('Aas')
    expect(creatorsShort(['Aas, T. S.', 'Asgard, T. E.'])).toBe('Aas & Asgard')
    expect(creatorsShort(paper.creators!)).toBe('Aas et al.')
  })
  it('creatorsLong', () => {
    expect(creatorsLong(['Aas, T. S.'])).toBe('Aas, T. S.')
    expect(creatorsLong(paper.creators!)).toBe('Aas, T. S., Asgard, T. E. & Ytrestoyl, T.')
  })
  it('recordLink prefers @id, then landing page, download URL, path, legacy url and location', () => {
    expect(recordLink(paper)).toBe(DOI)
    expect(recordLink(fao)).toBe('https://www.fao.org/faostat/en/#data/QCL')
    expect(recordLink({ downloadURL: 'https://d', path: 'https://p' })).toBe('https://d')
    expect(recordLink({ path: 'https://p', url: 'https://u' })).toBe('https://p')
    expect(recordLink({ location: { web: 'https://w', data: 'https://d' } })).toBe('https://w')
    expect(recordLink({ title: 'X' })).toBeUndefined()
  })
})

describe('renderSource', () => {
  it('compact', () => {
    expect(renderSource(paper, 'compact')).toEqual({ text: 'Aas et al. (2022)', link: DOI })
    expect(renderSource(fao, 'compact')).toEqual({ text: 'FAO', link: 'https://www.fao.org/faostat/en/#data/QCL' })
  })

  it('standard', () => {
    expect(renderSource(paper, 'standard')).toEqual({ text: `${TITLE} · Aas et al., 2022`, link: DOI })
    expect(renderSource(fao, 'standard')).toEqual({ text: 'FAOSTAT QCL Crops and livestock products · FAO', link: 'https://www.fao.org/faostat/en/#data/QCL' })
  })

  it('full', () => {
    expect(renderSource(paper, 'full')).toEqual({
      text: `Aas, T. S., Asgard, T. E. & Ytrestoyl, T. (2022). ${TITLE}. Aquaculture Reports 26, 101316. ${DOI}`,
    })
    expect(renderSource(fao, 'full')).toEqual({
      text: 'Food and Agriculture Organization of the United Nations. FAOSTAT QCL Crops and livestock products. https://www.fao.org/faostat/en/#data/QCL',
    })
  })

  it('full uses the citation when present', () => {
    expect(renderSource({ ...paper, citation: 'Aas et al. (2022). Feed. AR 26.' }, 'full')).toEqual({ text: 'Aas et al. (2022). Feed. AR 26.' })
  })

  it('credits a publisher-only source to the publisher, long name when there is no short name', () => {
    const record = { title: 'Census 2021', publisher: 'Office for National Statistics', issued: '2021-06-30' }
    expect(renderSource(record, 'compact').text).toBe('Office for National Statistics (2021)')
    expect(renderSource(record, 'standard').text).toBe('Census 2021 · Office for National Statistics, 2021')
    expect(renderSource(record, 'full').text).toBe('Office for National Statistics. (2021). Census 2021.')
  })

  it('falls back to the title when there are no creators and no publisher', () => {
    expect(renderSource({ title: 'Quick Stats', path: 'https://q' }, 'compact')).toEqual({ text: 'Quick Stats', link: 'https://q' })
    expect(renderSource({ title: 'Quick Stats', issued: '2020' }, 'standard').text).toBe('Quick Stats, 2020')
    expect(renderSource({ title: 'Quick Stats' }, 'full').text).toBe('Quick Stats.')
  })

  it('falls back to the attribution text when there is no title either', () => {
    const record = { attribution: 'Aas, T. S.; Asgard, T. E. (Nofima); published by Elsevier' }
    expect(renderSource(record, 'compact').text).toBe(record.attribution)
    expect(renderSource(record, 'standard').text).toBe(record.attribution)
    expect(renderSource(record, 'full').text).toBe(`${record.attribution}.`)
  })

  it('never doubles a period and drops empty segments with their punctuation', () => {
    expect(renderSource({ title: 'A title.', creators: ['Ytrestoyl, T.'] }, 'full').text).toBe('Ytrestoyl, T. A title.')
    expect(renderSource({ creators: ['Aas, T. S.'] }, 'compact').text).toBe('Aas')
  })

  it('toDatasetSourceAt gives the shape the Sources component reads', () => {
    expect(toDatasetSourceAt(paper, 'compact')).toEqual({ title: 'Aas et al. (2022)', url: DOI })
    expect(toDatasetSourceAt({ title: 'X' }, 'compact')).toEqual({ title: 'X' })
    expect(toDatasetSourceAt(fao, 'full')).toEqual({ title: renderSource(fao, 'full').text })
  })
})
```

Then append to `sourcesFromSchemaFields.test.ts`:

```ts
describe('stored records render by level', () => {
  const DCT = 'http://purl.org/dc/terms/'
  const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
  const stored = toSourceRecords([{
    '@id': 'https://doi.org/10.1016/j.aqrep.2022.101316',
    title: 'Utilization of feed resources',
    [`${DCT}publisher`]: { [RDFS_LABEL]: 'Elsevier' },
    [`${DCT}creator`]: [{ [RDFS_LABEL]: 'Aas, T. S.' }, { [RDFS_LABEL]: 'Asgard, T. E.' }],
    [`${DCT}issued`]: '2022',
  }])

  it('compact by default', () => {
    expect(resolveDatasetSources({ tableSources: stored, fields: [{ name: 'a' }] }))
      .toEqual([{ title: 'Aas & Asgard (2022)', url: 'https://doi.org/10.1016/j.aqrep.2022.101316' }])
  })

  it('standard and full on request', () => {
    expect(normalizeSources(stored, 'standard')[0]?.title).toBe('Utilization of feed resources · Aas & Asgard, 2022')
    expect(normalizeSources(stored, 'full')).toEqual([{ title: 'Aas, T. S. & Asgard, T. E. (2022). Utilization of feed resources. https://doi.org/10.1016/j.aqrep.2022.101316' }])
  })

  it('an override is passed through untouched at any level', () => {
    expect(resolveDatasetSources({ override: [{ title: 'Manual', url: 'https://m' }], tableSources: stored, fields: [], level: 'full' }))
      .toEqual([{ title: 'Manual', url: 'https://m' }])
  })

  it('de-duplicates by rendered text', () => {
    expect(normalizeSources([...stored, ...stored])).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/utilities/datasets/renderSource.test.ts src/utilities/datasets/sourcesFromSchemaFields.test.ts`
Expected: `renderSource.test.ts` fails to import; the new `sourcesFromSchemaFields` block fails (`title: 'Elsevier'` today, `level` unknown).

- [ ] **Step 3: Write `src/utilities/datasets/renderSource.ts`**

```ts
import type { DatasetSource, DatasetSourceRecord, SourceDetail } from '@/types/data-transforms'

/**
 * Renders a stored source record at one of the three levels of detail from
 * sunstone-cms#610:
 *
 *   compact   {attribution}[ ({year})]                         datasets list
 *   standard  {title}[ · {attribution}][, {year}]              dataset page, linked
 *   full      citation, else {author}.[ ({year}).] {title}.[ {container}.][ {link}]
 *
 * A paper is credited to its authors, a statistics release to its publisher.
 * Optional segments are dropped with their punctuation when a placeholder is
 * missing. Fallbacks for sources that have not been restructured: no creators
 * and no publisher, use the title; no title either, use the attribution text.
 */

export interface RenderedSource {
  text: string
  link?: string
}

const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0

/** "Aas, T. S." -> "Aas"; "Tor Aas" -> "Aas"; a single word stays as is. */
export function surname(label: string): string {
  const trimmed = label.trim()
  const comma = trimmed.indexOf(',')
  if (comma > 0) return trimmed.slice(0, comma).trim()
  const words = trimmed.split(/\s+/)
  return words[words.length - 1] ?? trimmed
}

/** One surname, two with " & ", three or more as the first plus " et al.". */
export function creatorsShort(creators: string[]): string {
  const names = creators.map(surname)
  if (names.length === 1) return names[0]!
  if (names.length === 2) return `${names[0]} & ${names[1]}`
  return `${names[0]} et al.`
}

/** All labels joined with ", ", the last with " & ". */
export function creatorsLong(creators: string[]): string {
  if (creators.length <= 1) return creators[0] ?? ''
  return `${creators.slice(0, -1).join(', ')} & ${creators[creators.length - 1]}`
}

/** First of @id, landing page, download URL, path, then the legacy url / location keys. */
export function recordLink(record: DatasetSourceRecord): string | undefined {
  const { location } = record
  const candidates = [
    record.id,
    record.landingPage,
    record.downloadURL,
    record.path,
    record.url,
    typeof location === 'object' && location ? location.web : undefined,
    typeof location === 'object' && location ? location.data : undefined,
    typeof location === 'string' ? location : undefined,
  ]
  return candidates.find(nonEmpty)
}

const year = (record: DatasetSourceRecord): string | undefined =>
  nonEmpty(record.issued) ? record.issued.trim().slice(0, 4) : undefined

const publisher = (record: DatasetSourceRecord): string | undefined =>
  [record.publisherShort, record.publisher].find(nonEmpty)

/** {attribution}: authors (short) when present, else the publisher. */
const attribution = (record: DatasetSourceRecord): string | undefined =>
  record.creators && record.creators.length > 0 ? creatorsShort(record.creators) : publisher(record)

/** {author}: all authors when present, else the publisher's full name. */
const author = (record: DatasetSourceRecord): string | undefined =>
  record.creators && record.creators.length > 0 ? creatorsLong(record.creators) : [record.publisher].find(nonEmpty)

/** Adds a trailing period unless the segment already ends with one. */
const sentence = (segment: string): string => (segment.trim().endsWith('.') ? segment.trim() : `${segment.trim()}.`)

function compact(record: DatasetSourceRecord): string {
  const who = attribution(record) ?? [record.title, record.attribution].find(nonEmpty) ?? ''
  const y = year(record)
  return y ? `${who} (${y})` : who
}

function standard(record: DatasetSourceRecord): string {
  const who = attribution(record)
  const title = [record.title].find(nonEmpty)
  if (!title && !who) return [record.attribution].find(nonEmpty) ?? ''
  const head = title ?? who ?? ''
  const withWho = title && who ? `${head} · ${who}` : head
  const y = year(record)
  return y ? `${withWho}, ${y}` : withWho
}

function full(record: DatasetSourceRecord): string {
  if (nonEmpty(record.citation)) return record.citation.trim()
  const who = author(record)
  const title = [record.title, record.attribution].find(nonEmpty)
  const y = year(record)
  const segments = [
    who ? sentence(who) : undefined,
    y ? `(${y}).` : undefined,
    title ? sentence(title) : undefined,
    nonEmpty(record.container) ? sentence(record.container) : undefined,
    recordLink(record),
  ]
  return segments.filter(nonEmpty).join(' ')
}

export function renderSource(record: DatasetSourceRecord, level: SourceDetail): RenderedSource {
  const link = recordLink(record)
  switch (level) {
    case 'compact':
      return link ? { text: compact(record), link } : { text: compact(record) }
    case 'standard':
      return link ? { text: standard(record), link } : { text: standard(record) }
    case 'full':
      return { text: full(record) }
  }
}

/** The `{ title, url? }` shape the `Sources` and `DownloadLink` components read. */
export function toDatasetSourceAt(record: DatasetSourceRecord, level: SourceDetail): DatasetSource {
  const { text, link } = renderSource(record, level)
  return link ? { title: text, url: link } : { title: text }
}
```

- [ ] **Step 4: Wire the renderer into `normalizeSources` and `resolveDatasetSources`**

In `sourcesFromSchemaFields.ts`, add `import { toDatasetSourceAt } from './renderSource'` and `SourceDetail` to the type import. Replace `normalizeSources` and `resolveDatasetSources` with:

```ts
/**
 * Normalises a table-level (Frictionless resource) source value — a string,
 * an object, an array of either, or stored `DatasetSourceRecord`s — into a
 * de-duplicated list of `{ title, url? }` entries rendered at `level`
 * (sunstone-cms#610; compact by default).
 */
export function normalizeSources(input: unknown, level: SourceDetail = 'compact'): DatasetSource[] {
  return dedupeByTitle(toSourceRecords(input).map((record) => toDatasetSourceAt(record, level)))
}

/**
 * Resolves the sources to show for a dataset: an explicit `sources` override
 * wins (returned as-is); otherwise sources are derived from the referenced
 * schema fields, with table-level sources (rendered at `level`) filling in
 * for fields that have no source of their own.
 */
export function resolveDatasetSources({
  override,
  tableSources,
  fields,
  level = 'compact',
}: {
  override?: unknown
  tableSources?: unknown
  fields: SchemaFieldWithSource[] | null | undefined
  level?: SourceDetail
}): DatasetSource[] {
  if (Array.isArray(override) && override.length > 0) return override as DatasetSource[]
  return sourcesFromSchemaFields(fields, normalizeSources(tableSources, level))
}
```

`toDatasetSource` (field-level sources) and `sourceLink` stay for `sourcesFromSchemaFields`; `toDatasetSource`'s `allowTitle` parameter is now unused by `normalizeSources`, so remove the parameter and the `allowTitle ? record.title : undefined` branch (fields never carry a Frictionless `title`). Pre-existing `normalizeSources` tests keep passing: a string source becomes `{ title }` (compact uses the title when there is no publisher), the herbicide fixture renders its publisher label with the landing page link, and the no-landing-page case links to `path` (which equals its download URL).

- [ ] **Step 5: Run tests, lint, types, commit**

Run: `npx vitest run src/utilities/datasets && npm run lint && npx tsc --noEmit`
Expected: all pass. The two services that call `resolveDatasetSources` (`dataset-service.ts`, `metadata-service.ts`) and `data-visualisation-service.ts` need no change: they get compact by default.

```bash
git add src/utilities/datasets/renderSource.ts src/utilities/datasets/renderSource.test.ts src/utilities/datasets/sourcesFromSchemaFields.ts src/utilities/datasets/sourcesFromSchemaFields.test.ts
git commit -m "feat(sources): render stored sources at compact, standard or full detail"
```

---

### Task 4: Methodology service returns package sources as `DatasetSourceRecord[]`

**Files:**
- Modify: `src/services/data/methodology-service.ts` (whole file; the trailing "final output" comment block goes)
- Modify: `src/app/(frontend)/datapackages/[slug]/DataPackageTabs.tsx` (`MethodologyResponse.sources`, lines ~31-45)
- Modify: `context/data-api.md` (methodology endpoint sample, lines ~55-70)
- Create: `src/services/data/methodology-service.test.ts`

**Interfaces:**
- Consumes: Task 3 `toSourceRecords`, `DatasetSourceRecord`.
- Produces: `export interface MethodologyResponse { methodology: string; sources: DatasetSourceRecord[] }` from `methodology-service.ts`; `getMethodology` signature unchanged. A consumer renders a record with `renderSource(record, 'full')` (Task 3b).

- [ ] **Step 1: Write the failing test `src/services/data/methodology-service.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../lib/api/gcs-storage', () => ({
  readFileFromGCS: vi.fn().mockResolvedValue('# Methodology\n\nText.'),
  readJSONFromGCS: vi.fn(),
}))
vi.mock('@/utilities/datasets/resolveDatasetPath', () => ({
  resolveDatasetPath: (path: string) => path,
}))

import { readJSONFromGCS } from '../../lib/api/gcs-storage'
import { getMethodology } from './methodology-service'

const DC_PUBLISHER = 'http://purl.org/dc/terms/publisher'
const DC_LICENSE = 'http://purl.org/dc/terms/license'
const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
const SKOS_ALT_LABEL = 'http://www.w3.org/2004/02/skos/core#altLabel'

describe('getMethodology', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns the methodology text and package sources as records', async () => {
    vi.mocked(readJSONFromGCS).mockResolvedValue({
      sources: [{
        title: 'FAO Fisheries',
        path: 'https://fao.org/data',
        [DC_PUBLISHER]: { [RDFS_LABEL]: 'Food and Agriculture Organization of the United Nations', [SKOS_ALT_LABEL]: 'FAO' },
        [DC_LICENSE]: 'CC-BY-4.0',
      }],
    })
    await expect(getMethodology('projects/p/METHODOLOGY.md', 'projects/p/datapackage.json')).resolves.toEqual({
      methodology: '# Methodology\n\nText.',
      sources: [{
        title: 'FAO Fisheries',
        publisher: 'Food and Agriculture Organization of the United Nations',
        publisherShort: 'FAO',
        path: 'https://fao.org/data',
        license: 'CC-BY-4.0',
      }],
    })
  })

  it('returns an empty methodology and no sources when neither exists', async () => {
    vi.mocked(readJSONFromGCS).mockResolvedValue({ title: 'P' })
    await expect(getMethodology(null, 'projects/p/datapackage.json')).resolves.toEqual({ methodology: '', sources: [] })
  })

  it('rejects without a metadataUrl', async () => {
    await expect(getMethodology(null, '')).rejects.toThrow('metadataUrl is required')
  })
})
```

If `tsc` rejects `mockResolvedValue({...})` because `readJSONFromGCS` has a narrower return type, cast the fixture to that return type (`as Awaited<ReturnType<typeof readJSONFromGCS>>`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/services/data/methodology-service.test.ts`
Expected: the first test FAILS (sources returned raw, with the IRI keys), the other two pass.

- [ ] **Step 3: Rewrite `src/services/data/methodology-service.ts`**

```ts
import { readFileFromGCS, readJSONFromGCS } from '../../lib/api/gcs-storage'
import { resolveDatasetPath } from '@/utilities/datasets/resolveDatasetPath'
import { toSourceRecords } from '@/utilities/datasets/sourcesFromSchemaFields'
import type { DatasetSourceRecord } from '@/types/data-transforms'
import { logger } from '@/lib/logger'

interface Datapackage {
  sources?: unknown
  [key: string]: unknown
}

// Methodology text + package-level sources only. The downloadable resources are
// fetched separately from the Datasets collection (see the methodology endpoint).
// Sources use the same record shape as dataset `tableSources` (structured parts);
// render them with `renderSource(record, 'full')` for a references list.
export interface MethodologyResponse {
  methodology: string
  sources: DatasetSourceRecord[]
}

export async function getMethodology(
  methodologyUrl: string | null, // path to the METHODOLOGY.md (null if not defined)
  metadataUrl: string, // path to datapackage.json
): Promise<MethodologyResponse> {
  if (!metadataUrl) {
    throw new Error('metadataUrl is required')
  }

  try {
    const methodologyContent = methodologyUrl
      ? await readFileFromGCS(resolveDatasetPath(methodologyUrl))
      : ''
    const datapackage = (await readJSONFromGCS(resolveDatasetPath(metadataUrl))) as Datapackage

    return {
      methodology: methodologyContent,
      sources: datapackage.sources === undefined ? [] : toSourceRecords(datapackage.sources),
    }
  } catch (error) {
    logger.error('Error fetching methodology', error)
    throw new Error(
      `Failed to fetch methodology: ${error instanceof Error ? error.message : 'Unknown error'}`,
    )
  }
}
```

- [ ] **Step 4: Update the frontend type and the docs**

In `src/app/(frontend)/datapackages/[slug]/DataPackageTabs.tsx`, replace the `sources: Array<{ name: string ... license?: string }>` member of `MethodologyResponse` with

```ts
  sources: DatasetSourceRecord[]
```

and add `DatasetSourceRecord` to the existing `import type { ... } from '@/types/data-transforms'` line.

In `context/data-api.md`, replace the `"sources"` array in the `GET /api/data/dataset/:slug/methodology` sample with:

```json
  "sources": [
    {
      "id": "https://doi.org/10.1016/j.aqrep.2022.101316",
      "title": "Utilization of feed resources in the production of Atlantic salmon (Salmo salar) in Norway: An update for 2020",
      "publisher": "Elsevier",
      "creators": ["Aas, T. S.", "Asgard, T. E.", "Ytrestoyl, T."],
      "issued": "2022",
      "container": "Aquaculture Reports 26, 101316",
      "license": "CC-BY-NC-ND-4.0"
    }
  ]
```

and add one sentence under it: "Sources are the structured parts from the data package (sunstone-cms#610); render a reference with `renderSource(record, 'full')` from `src/utilities/datasets/renderSource.ts`."

- [ ] **Step 5: Run tests, lint, types, commit**

Run: `npx vitest run src/services/data/methodology-service.test.ts src/endpoints/methodology.test.ts && npm run lint && npx tsc --noEmit`
Expected: all pass.

```bash
git add src/services/data/methodology-service.ts src/services/data/methodology-service.test.ts "src/app/(frontend)/datapackages/[slug]/DataPackageTabs.tsx" context/data-api.md
git commit -m "feat(methodology): return package sources as DatasetSourceRecord"
```

---

### Task 5: 1.20 and 2.0 fixtures import identically

**Files:**
- Test: `src/collections/DataPackages/endpoints/import.test.ts`

**Interfaces:**
- Consumes: Task 1 `methodologyFilenameOf`, Task 2 `extractSchema`, Task 3 (through `extractTableSources`).

- [ ] **Step 1: Write the test**

Append to `import.test.ts`:

```ts
describe('sunstone-py 1.20 and 2.0 descriptors import identically', () => {
  const PROV = 'http://www.w3.org/ns/prov#'
  const DCT = 'http://purl.org/dc/terms/'
  const DCAT = 'http://www.w3.org/ns/dcat#'
  const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
  const SKOS_ALT_LABEL = 'http://www.w3.org/2004/02/skos/core#altLabel'
  const SI = 'https://sunstone.institute/rdf/vocab#'
  const QUDT = 'http://qudt.org/schema/qudt/'
  const DOWNLOAD = 'https://digitallibrary.un.org/record/4082085/files/member_states.csv'

  // New keys only (sunstone-py 2.0 output).
  const v2 = {
    $schema: 'https://datapackage.org/profiles/2.0/datapackage.json',
    name: 'un-members',
    title: 'UN Member States Dataset',
    licenses: [{ name: 'CC-BY-NC-3.0-IGO' }],
    'https://sunstone.institute/rdf/data#methodology': 'https://data.example.com/METHODOLOGY.md',
    resources: [{
      name: 'current-un-member-states',
      title: 'Current UN Member States',
      path: 'https://data.example.com/outputs/current.csv',
      format: 'csv',
      mediatype: 'text/csv',
      schema: { fields: [
        { name: 'country', type: 'string', description: 'Country name.' },
        {
          name: 'area_km2', type: 'number', description: 'Land area.',
          [`${SI}unit`]: 'km**2', [`${QUDT}hasUnit`]: 'http://qudt.org/vocab/unit/KiloM2', [`${SI}sourceField`]: 'raw_area',
        },
      ] },
      sources: [{
        title: 'UN Member States Authority File',
        path: DOWNLOAD,
        [`${DCAT}downloadURL`]: DOWNLOAD,
        [`${DCAT}landingPage`]: 'https://digitallibrary.un.org/record/4082085',
        [`${DCT}publisher`]: { [RDFS_LABEL]: 'United Nations Dag Hammarskjöld Library', [SKOS_ALT_LABEL]: 'UN Library' },
        [`${DCT}issued`]: '2025',
        [`${PROV}wasAttributedTo`]: 'United Nations Dag Hammarskjöld Library',
        [`${DCT}license`]: 'CC-BY-NC-3.0-IGO',
      }],
    }],
  }

  // Same descriptor as sunstone-py 1.20 emits it: old keys kept alongside the new ones.
  const v119 = {
    ...v2,
    license: 'CC-BY-NC-3.0-IGO',
    'https://sunstone.institute/rdf/vocab#methodology': 'https://data.example.com/METHODOLOGY.md',
    resources: [{
      ...v2.resources[0],
      scheme: 'file',
      schema: { fields: [
        v2.resources[0].schema.fields[0],
        { ...v2.resources[0].schema.fields[1], unit: 'km**2', source: 'raw_area' },
      ] },
    }],
  }

  it('methodologyFilenameOf', () => {
    expect(methodologyFilenameOf(v119)).toBe('https://data.example.com/METHODOLOGY.md')
    expect(methodologyFilenameOf(v2)).toEqual(methodologyFilenameOf(v119))
  })

  it('extractSchema', () => {
    const expected = [
      { name: 'country', type: 'string', description: 'Country name.' },
      { name: 'area_km2', type: 'number', description: 'Land area.', unit: 'km**2', unitIri: 'http://qudt.org/vocab/unit/KiloM2', source: 'raw_area' },
    ]
    expect(extractSchema(v119.resources[0])).toEqual(expected)
    expect(extractSchema(v2.resources[0])).toEqual(expected)
  })

  it('extractTableSources', () => {
    const expected = [{
      title: 'UN Member States Authority File',
      publisher: 'United Nations Dag Hammarskjöld Library',
      publisherShort: 'UN Library',
      issued: '2025',
      attribution: 'United Nations Dag Hammarskjöld Library',
      path: DOWNLOAD,
      downloadURL: DOWNLOAD,
      landingPage: 'https://digitallibrary.un.org/record/4082085',
      license: 'CC-BY-NC-3.0-IGO',
    }]
    expect(extractTableSources(v119.resources[0])).toEqual(expected)
    expect(extractTableSources(v2.resources[0])).toEqual(expected)
  })
})
```

- [ ] **Step 2: Run the test**

Run: `npx vitest run src/collections/DataPackages/endpoints/import.test.ts`
Expected: PASS without code changes (Tasks 1-3 did the work). If a case fails, the earlier task is incomplete; fix it there, not in the fixture.

- [ ] **Step 3: Full suite, lint, types, commit, PR**

Run: `npx vitest run && npm run lint && npx tsc --noEmit`
Expected: all pass.

```bash
git add src/collections/DataPackages/endpoints/import.test.ts
git commit -m "test(import): 1.20 and 2.0 data package descriptors import identically"
git push -u origin feature/datapackage-iri-keys
gh pr create --title "Read sunstone-py 1.20 IRI keys and structured sources from datapackage.json" --body "$(cat <<'EOF'
Reads data#methodology, vocab#unit / vocab#sourceField (+ qudt:hasUnit as unitIri), and the structured source parts (@id, dct:publisher, dct:creator, dct:issued, dct:isPartOf, dct:bibliographicCitation, dct:license, prov:wasAttributedTo), keeping the old keys as fallbacks. Source parts are stored on tableSources (jsonb, no migration) and rendered at display time with the compact / standard / full templates from #610. Methodology endpoint returns package sources as DatasetSourceRecord.

Open points from #610, decided here and easy to change:
- Q3: parts are stored, strings are rendered at display time (not at import).
- Q1: compact is used in the resources list and visual embeds; full is available for the methodology references; standard is implemented but wired nowhere because the CMS has no dataset page.

Spec: sunstone-py docs/superpowers/specs/2026-10-15-datapackage-conformance-design.md, C12. Closes #610 once the author confirms the templates.
EOF
)"
```

Report the PR URL. sunstone-py 2.0 (which drops the old output keys) waits for this to be deployed.

---

## Self-review notes

- Spec coverage: C12.1 Task 1; C12.2 Task 2; C12.3 Tasks 3 and 3b (parts stored, templates from #610, `prov:wasAttributedTo` fallback so unstructured sources are not dropped); C12.4 Task 4; C12.5 Task 5; "no DB migration" holds (only `json` columns `schema`, `tableSources` receive new keys).
- #610 coverage: field table (Task 3 record shape), three levels and templates (Task 3b `renderSource`), placeholders (`surname`, `creatorsShort`, `creatorsLong`, `recordLink`, `{attribution}`, `{author}`, `{year}`), fallbacks (title, then attribution text), the two rendered examples as tests. Open questions 1 and 3 are decided in SC3/SC4 and flagged in the PR body.
- Placeholder scan: none.
- Type consistency: `DatasetSourceRecord` (Task 3) is what Task 3b renders, Task 4's service returns and Task 5's expectations rely on; `SourceDetail` is declared in Task 3 and used by Task 3b; `unitIri` is produced by Task 2 and asserted in Task 5; `methodologyFilenameOf` (Task 1) is used by Task 5.
- Nothing needs Opus: every step has its code and expected output. The one judgment call (templates may change in #610) is handled by re-reading the issue at the start of Task 3b.
