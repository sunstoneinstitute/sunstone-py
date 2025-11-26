# Data Package Standard (v2)

## Overview

**Data Package** is a comprehensive data standard and data definition language (DDL) designed to improve data management, sharing, and interoperability. Version 2 of the standard provides a modernized framework for describing datasets that enhances the **findability, accessibility, interoperability, and reusability (FAIR)** of data.

### Purpose

- Create a standardized framework for describing datasets
- Provide a simple yet extensible data definition language
- Enable structured data packaging and delivery
- Facilitate easier data discovery and integration
- Support comprehensive dataset documentation

### Design Philosophy

- **Simple**: Easy to understand and implement
- **Extensible**: Can be customized for specific use cases
- **Language-agnostic**: Works across different programming languages
- **Interoperable**: Compatible with existing data standards
- **FAIR-focused**: Promotes best practices in data management

### Adoption

The Data Package standard is used by major organizations including:
- European Commission
- GitHub
- GBIF (Global Biodiversity Information Facility)
- Dryad
- And many research institutions worldwide

### Software Support

Open-source tools and libraries are available for multiple languages including Python, JavaScript, R, and more.

---

## Architecture

The Data Package v2 standard consists of four core specifications that work together:

1. **Data Package**: Container format for describing a coherent collection of data
2. **Data Resource**: Format for describing individual data files or sources
3. **Table Schema**: Detailed description of tabular data structure
4. **Table Dialect**: Specification for how tabular data is physically stored

---

## Key Concepts

### Descriptor

A **descriptor** is a JSON object that contains metadata about a data package, resource, or schema. Descriptors can:
- Be stored in JSON files (e.g., `datapackage.json`)
- Include custom properties using `namespace:propertyName` convention
- Reference profiles for validation

### Profile

A **profile** is a URL that:
- Resolves to a valid JSON Schema descriptor
- Is versioned and immutable
- Serves as a metadata version identifier
- Enables validation of descriptors

### Tabular Data

**Tabular data** consists of:
- Rows with consistent fields
- Optional header row defining field names
- Multiple possible formats (CSV, Excel, JSON, databases, etc.)

### Data Representation

- **Physical representation**: How data appears in files (text, binary, etc.)
- **Logical representation**: "Ideal" data with defined types and structures

---

## 1. Data Package Specification

A **Data Package** is a simple container format for describing a coherent collection of data in a single package.

### Requirements

- **MUST** have a descriptor file (preferably named `datapackage.json`)
- **MUST** include at least one resource
- Descriptor contains metadata about the package and its resources

### Required Properties

- **`resources`** (array): List of data resources (REQUIRED)

### Recommended Properties

- **`name`**: Unique, human-readable identifier (lowercase alphanumeric)
- **`id`**: Globally unique identifier (UUID, DOI, etc.)
- **`licenses`**: Licensing information
- **`profile`**: Profile URL for validation

### Standard Properties

| Property | Type | Description |
|----------|------|-------------|
| `$schema` | string | Profile URL (default: `https://datapackage.org/profiles/2.0/datapackage.json`) |
| `name` | string | Unique identifier, invariant across updates |
| `id` | string | Globally unique identifier |
| `title` | string | Human-readable title |
| `description` | string | Detailed description (supports Markdown) |
| `version` | string | Semantic version |
| `created` | string | Creation datetime (ISO 8601) |
| `homepage` | string | URL to package homepage |
| `licenses` | array | License objects |
| `sources` | array | Raw data source objects |
| `contributors` | array | Contributor objects |
| `keywords` | array | Search keywords |
| `image` | string | Representative image URL |
| `resources` | array | Data resource objects (REQUIRED) |

### Example: Minimal Data Package

```json
{
  "name": "my-package",
  "resources": [
    {
      "name": "my-data",
      "path": "data.csv"
    }
  ]
}
```

### Example: Complete Data Package

```json
{
  "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
  "name": "gdp-data",
  "title": "A nice title",
  "version": "1.0.0",
  "created": "1985-04-12T23:20:50.52Z",
  "licenses": [
    {
      "name": "ODC-PDDL-1.0",
      "path": "http://opendatacommons.org/licenses/pddl/",
      "title": "Open Data Commons Public Domain Dedication and License v1.0"
    }
  ],
  "sources": [
    {
      "title": "World Bank and OECD",
      "path": "http://data.worldbank.org/indicator/NY.GDP.MKTP.CD"
    }
  ],
  "contributors": [
    {
      "title": "Joe Bloggs",
      "email": "[email protected]",
      "path": "http://www.bloggs.com",
      "roles": ["creator"]
    }
  ],
  "resources": [
    {
      "name": "gdp",
      "path": "data/gdp.csv",
      "type": "table",
      "schema": {
        "fields": [
          {
            "name": "country",
            "type": "string"
          },
          {
            "name": "year",
            "type": "integer"
          },
          {
            "name": "gdp",
            "type": "number"
          }
        ]
      }
    }
  ]
}
```

### File Structure

A typical Data Package directory structure:

```
my-package/
├── datapackage.json
├── README.md
├── data/
│   ├── mydata.csv
│   └── otherdata.csv
└── scripts/
    └── process.py
```

---

## 2. Data Resource Specification

A **Data Resource** describes and packages a single data resource, such as an individual table or file.

### Purpose

Provide a locator for data with optional rich metadata.

### Required Properties

- **`name`**: Unique identifier within the package (lowercase alphanumeric)

### Data Location (one required)

- **`path`**: URL or file system path to data file(s)
- **`data`**: Inline data representation

### Recommended Properties

- **`type`**: Resource type (e.g., `table` for tabular data)
- **`title`**: Human-readable label
- **`description`**: Detailed description
- **`format`**: File extension (e.g., `csv`, `json`, `xlsx`)
- **`mediatype`**: MIME type (e.g., `text/csv`)
- **`encoding`**: Character encoding (e.g., `utf-8`)

### Tabular Data Properties

When `type` is `table`:
- **`schema`**: Table Schema describing structure
- **`dialect`**: Table Dialect describing physical format

### Path Property

The `path` property can be:
- A single file: `"path": "data.csv"`
- Multiple files: `"path": ["data1.csv", "data2.csv"]`
- A URL: `"path": "http://example.com/data.csv"`
- A relative POSIX path: `"path": "data/myfile.csv"`

**Security restrictions:**
- Cannot use absolute paths (`/path/to/file`)
- Cannot use parent paths (`../file`)
- Cannot reference hidden folders

### Example: Basic Resource

```json
{
  "name": "solar-system",
  "path": "http://example.com/solar-system.csv",
  "title": "The Solar System",
  "format": "csv",
  "mediatype": "text/csv",
  "encoding": "utf-8"
}
```

### Example: Tabular Resource with Schema

```json
{
  "name": "population",
  "type": "table",
  "path": "data/population.csv",
  "title": "Population Data",
  "format": "csv",
  "schema": {
    "fields": [
      {
        "name": "country",
        "type": "string"
      },
      {
        "name": "population",
        "type": "integer"
      }
    ]
  }
}
```

### Example: Inline Data

```json
{
  "name": "countries",
  "data": [
    {"code": "US", "name": "United States"},
    {"code": "GB", "name": "United Kingdom"},
    {"code": "NO", "name": "Norway"}
  ]
}
```

### Example: Multiple Files

```json
{
  "name": "annual-reports",
  "path": [
    "data/2020.csv",
    "data/2021.csv",
    "data/2022.csv"
  ],
  "format": "csv"
}
```

---

## 3. Table Schema Specification

**Table Schema** is a format for declaring schemas for tabular data, providing type checking and validation capabilities.

### Core Properties

| Property | Type | Description |
|----------|------|-------------|
| `fields` | array | Field descriptors (REQUIRED) |
| `$schema` | string | Profile URL |
| `missingValues` | array | Defines how missing values are represented |
| `primaryKey` | string/array | Unique row identifier(s) |
| `foreignKeys` | array | Links between tables |

### Field Properties

Each field in the `fields` array has:

| Property | Type | Description |
|----------|------|-------------|
| `name` | string | Field name (REQUIRED) |
| `type` | string | Data type (recommended) |
| `format` | string | Specific format for the type |
| `title` | string | Human-readable title |
| `description` | string | Field description |
| `example` | any | Example value |
| `constraints` | object | Validation rules |
| `categories` | array | Categorical values with labels |
| `categoriesOrdered` | boolean | Whether categories have order |

### Field Types

| Type | Description | Example |
|------|-------------|---------|
| `string` | Text data | "Hello World" |
| `number` | Decimal numbers | 3.14, -42.5 |
| `integer` | Whole numbers | 42, -17 |
| `boolean` | True/false | true, false |
| `date` | Calendar date | 2024-01-15 |
| `datetime` | Date and time | 2024-01-15T10:30:00Z |
| `time` | Time of day | 10:30:00 |
| `year` | Year | 2024 |
| `yearmonth` | Year and month | 2024-01 |
| `duration` | Time duration | P1Y2M (ISO 8601) |
| `geopoint` | Geographic coordinates | [45.5231, -122.6765] |
| `geojson` | GeoJSON geometry | {...} |
| `object` | JSON object | {"key": "value"} |
| `array` | JSON array | [1, 2, 3] |
| `any` | Unspecified/mixed type | any value |

### Field Constraints

| Constraint | Type | Description |
|------------|------|-------------|
| `required` | boolean | Field cannot be null |
| `unique` | boolean | All values must be unique |
| `minLength` | integer | Minimum string length |
| `maxLength` | integer | Maximum string length |
| `minimum` | number | Minimum value |
| `maximum` | number | Maximum value |
| `pattern` | string | Regular expression validation |
| `enum` | array | Restrict to specific values |

### Example: Basic Table Schema

```json
{
  "fields": [
    {
      "name": "id",
      "type": "integer"
    },
    {
      "name": "name",
      "type": "string"
    },
    {
      "name": "price",
      "type": "number"
    }
  ]
}
```

### Example: Schema with Constraints

```json
{
  "fields": [
    {
      "name": "id",
      "type": "integer",
      "constraints": {
        "required": true,
        "unique": true
      }
    },
    {
      "name": "email",
      "type": "string",
      "format": "email",
      "constraints": {
        "required": true
      }
    },
    {
      "name": "price",
      "type": "integer",
      "constraints": {
        "minimum": 100,
        "maximum": 150,
        "required": true
      }
    }
  ],
  "primaryKey": "id"
}
```

### Example: Categories

Categories allow you to define labeled values, useful for coded data:

```json
{
  "fields": [
    {
      "name": "fruit",
      "type": "integer",
      "categories": [
        {"value": 0, "label": "apple"},
        {"value": 1, "label": "orange"},
        {"value": 2, "label": "banana"}
      ],
      "categoriesOrdered": true
    }
  ]
}
```

### Example: Foreign Keys

Foreign keys create relationships between tables:

```json
{
  "resources": [
    {
      "name": "population-by-state",
      "schema": {
        "fields": [
          {"name": "state-code", "type": "string"},
          {"name": "population", "type": "integer"}
        ],
        "foreignKeys": [
          {
            "fields": ["state-code"],
            "reference": {
              "resource": "state-codes",
              "fields": ["code"]
            }
          }
        ]
      }
    },
    {
      "name": "state-codes",
      "schema": {
        "fields": [
          {"name": "code", "type": "string"},
          {"name": "name", "type": "string"}
        ],
        "primaryKey": "code"
      }
    }
  ]
}
```

### Example: Missing Values

Define how missing or null values are represented:

```json
{
  "fields": [
    {"name": "temperature", "type": "number"},
    {"name": "notes", "type": "string"}
  ],
  "missingValues": [
    {"value": "", "label": "OMITTED"},
    {"value": "-99", "label": "REFUSED"},
    {"value": "N/A", "label": "NOT_APPLICABLE"}
  ]
}
```

---

## 4. Table Dialect Specification

**Table Dialect** describes how tabular data is physically stored in a file, supporting various formats like CSV, TSV, JSON, Excel, and databases.

### Purpose

- Define parsing rules for tabular data files
- Ensure data interoperability across different formats
- Provide configuration for delimiters, quotes, line terminators, etc.

### Standard Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `$schema` | string | - | Profile URL |
| `header` | boolean | `true` | Whether first row contains field names |
| `headerRows` | array | `[1]` | Row numbers containing headers |
| `delimiter` | string | `,` | Field delimiter character |
| `lineTerminator` | string | `\r\n` | Row separator |
| `quoteChar` | string | `"` | Quote character |
| `doubleQuote` | boolean | `true` | Whether quotes are escaped by doubling |
| `escapeChar` | string | - | Escape character (alternative to doubleQuote) |
| `skipInitialSpace` | boolean | `false` | Ignore whitespace after delimiter |
| `commentChar` | string | - | Comment line prefix |
| `caseSensitiveHeader` | boolean | `false` | Whether header names are case-sensitive |

### Supported Formats

The Table Dialect specification supports:
- **Delimited formats**: CSV, TSV, pipe-delimited
- **Structured formats**: JSON, YAML
- **Spreadsheets**: Excel (.xlsx, .xls), OpenOffice (.ods)
- **Databases**: SQL tables, query results

### Example: Semicolon-Delimited CSV

```json
{
  "delimiter": ";",
  "quoteChar": "'",
  "header": true
}
```

### Example: Tab-Delimited with Comments

```json
{
  "delimiter": "\t",
  "lineTerminator": "\n",
  "commentChar": "#",
  "header": true
}
```

### Example: No Header Row

```json
{
  "header": false,
  "delimiter": ",",
  "quoteChar": "\""
}
```

### Example: Custom Quote Escaping

```json
{
  "delimiter": ",",
  "quoteChar": "\"",
  "doubleQuote": false,
  "escapeChar": "\\"
}
```

### Example: Multiline Headers

```json
{
  "headerRows": [1, 2],
  "delimiter": ","
}
```

### Important Notes

- Table Dialect focuses on **formatting**, not data types or schema
- Character encoding is handled separately (not part of dialect)
- Backward compatible with the older "CSV Dialect" specification
- Orthogonal to Table Schema (they work together but are independent)

---

## Complete Example: Multi-Resource Package

Here's a comprehensive example showing all specifications working together:

**datapackage.json:**

```json
{
  "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
  "name": "population-and-cities",
  "title": "Country Population and Major Cities",
  "version": "1.0.0",
  "description": "Population data by country with major cities information",
  "created": "2024-01-15T10:00:00Z",
  "licenses": [
    {
      "name": "CC-BY-4.0",
      "title": "Creative Commons Attribution 4.0",
      "path": "https://creativecommons.org/licenses/by/4.0/"
    }
  ],
  "contributors": [
    {
      "title": "Data Team",
      "email": "[email protected]",
      "roles": ["author", "maintainer"]
    }
  ],
  "keywords": ["population", "demographics", "cities"],
  "resources": [
    {
      "name": "countries",
      "type": "table",
      "path": "data/countries.csv",
      "title": "Country Population Data",
      "format": "csv",
      "mediatype": "text/csv",
      "encoding": "utf-8",
      "dialect": {
        "delimiter": ",",
        "header": true,
        "quoteChar": "\""
      },
      "schema": {
        "fields": [
          {
            "name": "country_code",
            "type": "string",
            "title": "ISO Country Code",
            "constraints": {
              "required": true,
              "unique": true,
              "pattern": "^[A-Z]{2}$"
            }
          },
          {
            "name": "country_name",
            "type": "string",
            "title": "Country Name",
            "constraints": {
              "required": true
            }
          },
          {
            "name": "population",
            "type": "integer",
            "title": "Total Population",
            "constraints": {
              "minimum": 0
            }
          },
          {
            "name": "area_km2",
            "type": "number",
            "title": "Area in km²"
          },
          {
            "name": "last_updated",
            "type": "date"
          }
        ],
        "primaryKey": "country_code",
        "missingValues": [
          {"value": "", "label": "NOT_PROVIDED"},
          {"value": "N/A", "label": "NOT_APPLICABLE"}
        ]
      }
    },
    {
      "name": "cities",
      "type": "table",
      "path": "data/cities.csv",
      "title": "Major Cities",
      "format": "csv",
      "schema": {
        "fields": [
          {
            "name": "city_id",
            "type": "integer",
            "constraints": {
              "required": true,
              "unique": true
            }
          },
          {
            "name": "city_name",
            "type": "string",
            "constraints": {
              "required": true
            }
          },
          {
            "name": "country_code",
            "type": "string",
            "constraints": {
              "required": true,
              "pattern": "^[A-Z]{2}$"
            }
          },
          {
            "name": "population",
            "type": "integer",
            "constraints": {
              "minimum": 0
            }
          },
          {
            "name": "coordinates",
            "type": "geopoint",
            "title": "City Coordinates"
          }
        ],
        "primaryKey": "city_id",
        "foreignKeys": [
          {
            "fields": ["country_code"],
            "reference": {
              "resource": "countries",
              "fields": ["country_code"]
            }
          }
        ]
      }
    },
    {
      "name": "regions",
      "title": "World Regions Lookup",
      "data": [
        {"code": "EU", "name": "Europe"},
        {"code": "AS", "name": "Asia"},
        {"code": "AF", "name": "Africa"},
        {"code": "NA", "name": "North America"},
        {"code": "SA", "name": "South America"},
        {"code": "OC", "name": "Oceania"}
      ],
      "schema": {
        "fields": [
          {"name": "code", "type": "string"},
          {"name": "name", "type": "string"}
        ],
        "primaryKey": "code"
      }
    }
  ]
}
```

This example demonstrates:
- Multiple resources (CSV files and inline data)
- Complete metadata (licenses, contributors, keywords)
- Detailed table schemas with various field types
- Constraints and validation rules
- Primary and foreign keys for referential integrity
- Table dialect specification for CSV parsing
- Missing value definitions

---

## Advanced Features

### Custom Properties

Descriptors can include custom properties using namespace conventions:

```json
{
  "name": "my-package",
  "myorg:internal_id": "12345",
  "myorg:department": "research",
  "resources": [ ]
}
```

### Resource Caching

The `_cache` property provides fallback locations when primary data sources are unavailable:

```json
{
  "name": "remote-data",
  "path": "https://example.com/data.csv",
  "_cache": "cache/data.csv"
}
```

### Profiles

Specify custom profiles for validation:

```json
{
  "profile": "https://example.com/profiles/custom-package.json",
  "name": "my-package",
  "resources": [ ]
}
```

---

## Benefits and Use Cases

### Benefits

1. **FAIR Data Principles**: Enhances findability, accessibility, interoperability, and reusability
2. **Self-Describing**: Metadata travels with data
3. **Validation**: Schemas enable automatic validation
4. **Standardization**: Consistent format across organizations
5. **Documentation**: Built-in comprehensive metadata
6. **Versioning**: Track changes and evolution
7. **Relationships**: Foreign keys enable data linking
8. **Type Safety**: Strong typing for data fields

### Use Cases

- **Research Data Management**: Package research datasets with complete provenance
- **Open Data Publishing**: Government and public sector data sharing
- **Data Integration**: ETL pipelines with standardized formats
- **Data Catalogs**: Build searchable data repositories
- **Data Quality**: Validate data against schemas
- **Collaborative Projects**: Share data with clear documentation
- **Archival**: Long-term data preservation with metadata

---

## Tools and Software

The Data Package ecosystem includes:

- **Open Data Editor**: Visual tool for creating and editing data packages
- **Frictionless Framework** (Python): Create, validate, and transform packages
- **JavaScript libraries**: Browser and Node.js support
- **R packages**: Integration with R workflows
- **Command-line tools**: Automation and scripting

---

## Comparison with v1

Data Package v2 builds on v1 with improvements including:

- Enhanced Table Schema with categories and ordered categories
- More flexible missing values with labels
- Table Dialect specification (evolved from CSV Dialect)
- Better profile system for validation
- Improved foreign key definitions
- Extended metadata properties

---

## References

- **Official Website**: https://datapackage.org/
- **Specifications**:
  - Data Package: https://datapackage.org/standard/data-package/
  - Data Resource: https://datapackage.org/standard/data-resource/
  - Table Schema: https://datapackage.org/standard/table-schema/
  - Table Dialect: https://datapackage.org/standard/table-dialect/
- **GitHub**: https://github.com/frictionlessdata
- **Open Knowledge Foundation**: https://okfn.org/

---

## Related Standards

Data Package v2 is inspired by and compatible with:
- DataCite
- Zenodo
- DCAT (Data Catalog Vocabulary)
- CKAN
- Schema.org
