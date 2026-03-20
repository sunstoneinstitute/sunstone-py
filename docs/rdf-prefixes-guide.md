# RDF Prefixes in datasets.yaml

This guide covers how to use RDF (Resource Description Framework) prefixes in `datasets.yaml` to add semantic metadata to your datasets. For the full specification including datapackage.json output and advanced use cases, see [Data Package Metadata Extensibility](datapackage-extra-metadata.md).

## Standard Prefixes

Sunstone includes these built-in prefixes that are always available (no need to declare them):

| Prefix | Namespace | Purpose |
|--------|-----------|---------|
| `rdf:` | `http://www.w3.org/1999/02/22-rdf-syntax-ns#` | RDF syntax |
| `dcat:` | `http://www.w3.org/ns/dcat#` | Data Catalog Vocabulary |
| `si:` | `https://sunstone.institute/rdf/vocab#` | Sunstone-specific properties |
| `si30:` | `https://sunstone.institute/rdf/threat/` | Sunstone threat references |

Additional common prefixes you may want to declare:

| Prefix | Namespace | Purpose |
|--------|-----------|---------|
| `schema:` | `http://schema.org/` | Schema.org vocabulary |
| `prov:` | `http://www.w3.org/ns/prov#` | W3C Provenance Ontology |
| `skos:` | `http://www.w3.org/2004/02/skos/core#` | Simple Knowledge Organization |
| `dwc:` | `http://rs.tdwg.org/dwc/terms/` | Darwin Core (biodiversity) |
| `sosa:` | `http://www.w3.org/ns/sosa/` | Sensor, Observation, Sample, Actuator |
| `qudt:` | `http://qudt.org/schema/qudt/` | Quantities, Units, Dimensions |

## Defining Prefixes

Prefixes can be defined at three levels, with this precedence order (highest first):

1. **Dataset-level** — on an individual input or output
2. **Top-level** — at the root of `datasets.yaml`
3. **Defaults section** — in the `defaults:` block

### Using the defaults section (recommended)

Define prefixes once and they apply to all datasets:

```yaml
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"
    si30: "https://sunstone.institute/rdf/threat/"
    dcat: "http://www.w3.org/ns/dcat#"

outputs:
  - name: Climate Dataset
    slug: climate-dataset
    location: outputs/climate.csv
    si:monitorsThreat: si30:27
    si:category: environmental
    dcat:theme: climate
    fields:
      - name: year
        type: integer
```

### Top-level prefixes

```yaml
rdfPrefixes:
  si: "https://sunstone.institute/rdf/vocab#"
  si30: "https://sunstone.institute/rdf/threat/"

outputs:
  - name: Climate Dataset
    slug: climate-dataset
    location: outputs/climate.csv
    si:monitorsThreat: si30:27
    fields:
      - name: year
        type: integer
```

### Per-dataset override

A dataset can override inherited prefixes:

```yaml
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"

outputs:
  - name: Special Dataset
    slug: special-dataset
    location: outputs/special.csv
    rdfPrefixes:
      si: "https://other.example.com/vocab#"  # overrides default
    si:customProp: value
    fields:
      - name: id
        type: integer
```

## Adding RDF Properties

Any key containing `:` (or starting with `http://`/`https://`) on a dataset entry is treated as a custom RDF property. Standard dataset fields (`name`, `slug`, `location`, `fields`, `source`, `strict`, `lineage`, `rdfPrefixes`, `publish`) are excluded.

### Using prefixed names

```yaml
outputs:
  - name: Climate Dataset
    slug: climate-dataset
    location: outputs/climate.csv
    si:monitorsThreat: si30:27      # both key and value use prefixes
    si:category: environmental       # value is a plain string
    dcat:theme: climate
    fields:
      - name: year
        type: integer
```

### Using full URIs

You can also use full URIs directly without defining prefixes:

```yaml
outputs:
  - name: My Dataset
    slug: my-dataset
    location: outputs/data.csv
    https://sunstone.institute/rdf/vocab#datasetType: observational
    fields:
      - name: id
        type: integer
```

## Default Properties

RDF properties in the `defaults:` section are inherited by all datasets:

```yaml
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"
  si:organization: "Sunstone Institute"
  si:license: "CC-BY-4.0"

outputs:
  - name: Dataset 1
    slug: dataset-1
    location: outputs/data1.csv
    si:theme: climate
    fields:
      - name: id
        type: integer

  - name: Dataset 2
    slug: dataset-2
    location: outputs/data2.csv
    si:theme: biodiversity
    fields:
      - name: id
        type: integer
```

Both datasets inherit `si:organization` and `si:license` from defaults. Dataset-level properties override defaults when they share the same key.

## Prefix Expansion

When building a datapackage (`sunstone package build`), prefixes in both keys and values are expanded to full URIs:

```yaml
# In datasets.yaml
si:monitorsThreat: si30:27
```

Becomes in `datapackage.json`:

```json
"https://sunstone.institute/rdf/vocab#monitorsThreat": "https://sunstone.institute/rdf/threat/27"
```

Non-string values (numbers, booleans, lists) are preserved as-is without expansion.

## Automatic Type Properties

Every generated `datapackage.json` automatically includes DCAT type annotations:

- **Package level**: `rdf:type` -> `dcat:Dataset`
- **Resource level**: `rdf:type` -> `dcat:Distribution`

No configuration needed — this makes all generated packages compatible with DCAT-based data catalogs.

## Methodology Property

The `si:methodology` property has special handling. When its value is a local file path, it is resolved as a relative URI against `publish.as` during publishing:

```yaml
publish:
  enabled: true
  to: gs://my-bucket/datasets/project/
  as: https://cdn.example.com/datasets/project/

defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"
  si:methodology: docs/default-methodology.md

outputs:
  - name: Climate Dataset
    slug: climate-dataset
    location: outputs/climate.csv
    si:methodology: docs/climate-methodology.md  # per-dataset override
    fields:
      - name: year
        type: integer
```

On publish, the value becomes `https://cdn.example.com/datasets/project/docs/climate-methodology.md` and the file is uploaded alongside the data.

## Further Reading

- Full specification with datapackage.json examples: [Data Package Metadata Extensibility](datapackage-extra-metadata.md)
- Datapackage standard: https://datapackage.org/
- DCAT vocabulary: https://www.w3.org/TR/vocab-dcat-3/
