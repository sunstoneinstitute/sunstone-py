# Data Package Metadata Extensibility

## Overview

The Data Package standard provides excellent extensibility for augmenting descriptors with custom metadata, including semantic annotations from knowledge graphs, domain-specific properties, and organizational metadata.

## Custom Properties with Namespaces

The Data Package specification supports custom properties using the `namespace:propertyName` convention. This allows you to add any metadata without conflicting with standard properties.

### Basic Example

```json
{
  "name": "my-package",
  "myorg:internal_id": "12345",
  "myorg:department": "research",
  "resources": []
}
```

## Semantic Metadata at Multiple Levels

Custom properties can be added at any level of the descriptor, making it ideal for semantic web integration and knowledge graph alignment.

### 1. Package Level

Add semantic metadata to describe the entire dataset:

```json
{
  "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
  "name": "climate-observations",
  "title": "Climate Observation Dataset",
  "kg:ontology": "http://schema.org/Dataset",
  "kg:subject": [
    "http://dbpedia.org/resource/Climate_change",
    "http://dbpedia.org/resource/Temperature"
  ],
  "kg:spatialCoverage": "http://sws.geonames.org/3144096/",
  "schema:temporalCoverage": "2020-01-01/2024-12-31",
  "resources": [...]
}
```

### 2. Resource Level

Annotate individual data resources with semantic concepts:

```json
{
  "resources": [
    {
      "name": "temperatures",
      "path": "data/temperatures.csv",
      "type": "table",
      "kg:concept": "http://purl.obolibrary.org/obo/ENVO_01000267",
      "kg:methodology": "http://example.org/methodology/automated-sensor",
      "prov:wasGeneratedBy": "http://example.org/activity/sensor-collection-2024",
      "schema": {...}
    }
  ]
}
```

### 3. Field Level (Schema)

Add semantic annotations to individual fields for precise meaning:

```json
{
  "schema": {
    "fields": [
      {
        "name": "temperature",
        "type": "number",
        "title": "Air Temperature",
        "kg:unit": "http://qudt.org/vocab/unit/DEG_C",
        "kg:measuredProperty": "http://purl.obolibrary.org/obo/PATO_0000146",
        "sosa:observedProperty": "http://example.org/property/air-temperature",
        "constraints": {
          "minimum": -50,
          "maximum": 50
        }
      },
      {
        "name": "location_id",
        "type": "string",
        "kg:references": "http://www.geonames.org/",
        "skos:exactMatch": "http://www.w3.org/2003/01/geo/wgs84_pos#SpatialThing"
      },
      {
        "name": "species_code",
        "type": "string",
        "dwc:scientificName": "Taxonomic reference",
        "kg:vocabulary": "http://rs.gbif.org/vocabulary/gbif/taxonomic_status.xml"
      }
    ]
  }
}
```

## Common Use Cases

### 1. Knowledge Graph Integration

Link datasets to ontologies and knowledge graphs:

```json
{
  "name": "biodiversity-survey",
  "kg:alignedOntology": [
    "http://rs.tdwg.org/dwc/terms/",
    "http://purl.obolibrary.org/obo/envo.owl"
  ],
  "schema:isBasedOn": "http://example.org/research/project/12345",
  "resources": [...]
}
```

### 2. Provenance Tracking

Use W3C PROV vocabulary for data lineage:

```json
{
  "name": "processed-data",
  "prov:wasDerivedFrom": "http://example.org/dataset/raw-data",
  "prov:wasGeneratedBy": {
    "prov:activity": "data-cleaning-2024-01",
    "prov:atTime": "2024-01-15T10:00:00Z",
    "prov:wasAssociatedWith": "http://example.org/agent/data-team"
  },
  "resources": [...]
}
```

### 3. Domain-Specific Metadata

Add field-specific vocabularies for specialized domains:

```json
{
  "schema": {
    "fields": [
      {
        "name": "sample_id",
        "type": "string",
        "obi:hasURI": "http://purl.obolibrary.org/obo/OBI_0000066",
        "lab:protocol": "http://example.org/protocols/sampling-v2"
      }
    ]
  }
}
```

### 4. Organizational Metadata

Internal tracking and workflow properties:

```json
{
  "name": "my-dataset",
  "myorg:project_id": "PRJ-2024-001",
  "myorg:status": "approved",
  "myorg:confidentiality": "internal",
  "myorg:retention_period": "P7Y",
  "myorg:owner": "research-team-alpha",
  "resources": [...]
}
```

## Recommended Namespace Prefixes

Consider using established vocabulary prefixes for interoperability:

| Prefix | Namespace | Purpose |
|--------|-----------|---------|
| `kg:` | Custom knowledge graph | Your semantic annotations |
| `schema:` | http://schema.org/ | Schema.org vocabulary |
| `dcat:` | http://www.w3.org/ns/dcat# | Data Catalog Vocabulary |
| `prov:` | http://www.w3.org/ns/prov# | Provenance Ontology |
| `skos:` | http://www.w3.org/2004/02/skos/core# | Simple Knowledge Organization |
| `dwc:` | http://rs.tdwg.org/dwc/terms/ | Darwin Core (biodiversity) |
| `sosa:` | http://www.w3.org/ns/sosa/ | Sensor, Observation, Sample, Actuator |
| `qudt:` | http://qudt.org/schema/qudt/ | Quantities, Units, Dimensions |
| `obi:` | http://purl.obolibrary.org/obo/OBI_ | Ontology for Biomedical Investigations |

## Best Practices

### 1. Use Consistent Namespaces

Choose a namespace prefix for your organization and use it consistently:

```json
{
  "myorg:property1": "value",
  "myorg:property2": "value"
}
```

### 2. Document Your Extensions

Add a README or separate documentation explaining your custom properties:

```json
{
  "name": "my-dataset",
  "myorg:metadata_version": "1.0",
  "myorg:schema_documentation": "https://example.org/docs/metadata-schema",
  "resources": [...]
}
```

### 3. Preserve Standard Properties

Never override or conflict with standard Data Package properties:

```json
{
  // Good: Custom property with namespace
  "myorg:title": "Internal title",
  "title": "Public title",

  // Bad: Don't redefine standard properties
  // "resources": "something else"
}
```

### 4. Use URIs for Semantic References

When linking to knowledge graphs, use full URIs:

```json
{
  "kg:concept": "http://purl.obolibrary.org/obo/ENVO_01000267",
  // Not: "kg:concept": "ENVO_01000267"
}
```

### 5. Validate with Custom Profiles

For strict validation of your extensions, create a custom profile:

```json
{
  "$schema": "https://example.org/profiles/myorg-datapackage.json",
  "name": "my-dataset",
  "myorg:required_property": "value",
  "resources": [...]
}
```

## Complete Example: Semantic Research Dataset

```json
{
  "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
  "name": "ocean-temperature-study",
  "title": "Ocean Temperature Observations 2020-2024",
  "version": "1.0.0",
  "description": "Multi-year ocean temperature study from coastal monitoring stations",

  // Semantic metadata
  "schema:keywords": ["oceanography", "climate", "temperature"],
  "dcat:theme": ["http://eurovoc.europa.eu/2107"],
  "kg:ontology": "http://www.w3.org/ns/sosa/",
  "kg:spatialCoverage": "http://sws.geonames.org/3144096/",

  // Provenance
  "prov:wasDerivedFrom": "http://example.org/dataset/raw-sensor-data",
  "prov:wasGeneratedBy": {
    "prov:activity": "quality-control-pipeline-v2",
    "prov:atTime": "2024-01-15T10:00:00Z"
  },

  // Organizational
  "myorg:project_id": "OCEAN-2024-001",
  "myorg:funding_source": "NSF Grant #12345",
  "myorg:data_classification": "public",

  "licenses": [{
    "name": "CC-BY-4.0",
    "path": "https://creativecommons.org/licenses/by/4.0/"
  }],

  "resources": [
    {
      "name": "temperature-readings",
      "type": "table",
      "path": "data/temperatures.csv",
      "title": "Temperature Observations",

      // Resource-level semantics
      "sosa:observationType": "http://example.org/observation/sea-surface-temperature",
      "kg:instrumentType": "http://vocab.nerc.ac.uk/collection/L05/current/134/",

      "schema": {
        "fields": [
          {
            "name": "timestamp",
            "type": "datetime",
            "title": "Observation Time",
            "constraints": {"required": true}
          },
          {
            "name": "station_id",
            "type": "string",
            "title": "Monitoring Station ID",
            "kg:references": "http://example.org/stations/",
            "constraints": {"required": true}
          },
          {
            "name": "temperature",
            "type": "number",
            "title": "Sea Surface Temperature",

            // Field-level semantics
            "sosa:observedProperty": "http://vocab.nerc.ac.uk/collection/P07/current/CFSN0381/",
            "qudt:unit": "http://qudt.org/vocab/unit/DEG_C",
            "kg:measuredProperty": "http://purl.obolibrary.org/obo/PATO_0000146",
            "skos:definition": "Temperature measured at 1 meter below sea surface",

            "constraints": {
              "required": true,
              "minimum": -2,
              "maximum": 40
            }
          },
          {
            "name": "depth_meters",
            "type": "number",
            "title": "Measurement Depth",
            "qudt:unit": "http://qudt.org/vocab/unit/M",
            "constraints": {"minimum": 0}
          },
          {
            "name": "quality_flag",
            "type": "integer",
            "title": "QC Flag",
            "myorg:qc_version": "v2.1",
            "categories": [
              {"value": 0, "label": "good"},
              {"value": 1, "label": "suspect"},
              {"value": 2, "label": "bad"}
            ]
          }
        ],
        "primaryKey": ["timestamp", "station_id"]
      }
    }
  ]
}
```

## Key Takeaways

1. **Any level is extensible** - Add custom properties at package, resource, or field level
2. **Use namespaces** - Prefix custom properties to avoid conflicts
3. **JSON flexibility** - Custom properties can be strings, objects, arrays, etc.
4. **Standard tools preserve** - Custom properties pass through standard Data Package tools
5. **Perfect for semantics** - Ideal for linking to knowledge graphs, ontologies, and vocabularies
6. **No validation by default** - Create custom profiles if you need validation of extensions

This extensibility makes Data Package an excellent choice for FAIR data principles and semantic web integration while maintaining simplicity and interoperability.
