# Frictionless Data Standard

## Overview

**Frictionless Data** is an open-source toolkit and set of specifications designed to simplify data management, integration, and sharing. It brings simplicity to the data experience by standardizing how data is packaged, described, and distributed.

### Purpose

- Make data **reproducible, processable, and standardizable**
- Handle everything from simple CSV files to complex data pipelines
- Promote FAIR principles: **Findable, Accessible, Interoperable, Reusable**
- Create reliable, repeatable, and automated data integration workflows

### Design Philosophy

- **Approachable**: Minimal core with simple concepts
- **Incrementally Adoptable**: Start small and scale as needed
- **Progressive**: Enhances existing tools and workflows
- **Simplicity**: Easy to understand and implement
- **Extensibility**: Can be extended for specific use cases
- **Cross-technology**: Works across different platforms and languages

### Target Users

- Researchers
- Data Scientists
- Data Engineers
- Anyone working with structured data

---

## Core Concepts

### 1. Data Packaging
Bundle data files with metadata and schemas to provide clarity and context. This makes data self-describing and easier to understand and use.

### 2. Data Transformation
Clean and convert data between formats with standardized processes.

### 3. Data Storage/Integration
Push data into different platforms and applications using consistent formats and metadata.

---

## Main Specifications

The Frictionless Data standard is composed of several modular specifications that work together:

### 1. Data Package
### 2. Data Resource
### 3. Table Schema

Additional specifications include CSV Dialect, Tabular Data Package, Fiscal Data Package, and more.

---

## 1. Data Package

A **Data Package** is a simple container format for describing and distributing a collection of data.

### Structure

A Data Package is centered around a `datapackage.json` descriptor file placed in the top-level directory.

### Required Properties

- **`resources`** (array): List of data resources in the package (REQUIRED)

### Recommended Properties

- **`name`**: Unique, URL-friendly identifier (lowercase, alphanumeric, hyphens, underscores)
- **`id`**: Globally unique identifier (UUID or DOI)
- **`licenses`**: Licensing information
- **`profile`**: Specification profile being used

### Optional Properties

- **`title`**: Human-readable title
- **`description`**: Detailed description (supports Markdown)
- **`version`**: Semantic version string
- **`sources`**: Information about raw data origins
- **`contributors`**: People or organizations involved
- **`keywords`**: Array of tags for searchability
- **`image`**: Representative image URL

### Example: Minimal Data Package

```json
{
  "name": "my-dataset",
  "resources": [
    {
      "path": "data.csv",
      "title": "My Data"
    }
  ]
}
```

### Example: Complete Data Package

```json
{
  "name": "global-temperature-data",
  "title": "Global Temperature Data 1880-2020",
  "version": "1.0.0",
  "description": "Historical global temperature measurements from weather stations worldwide.",
  "licenses": [
    {
      "name": "CC-BY-4.0",
      "path": "https://creativecommons.org/licenses/by/4.0/",
      "title": "Creative Commons Attribution 4.0"
    }
  ],
  "sources": [
    {
      "title": "NOAA Climate Data",
      "path": "https://www.noaa.gov/climate-data"
    }
  ],
  "contributors": [
    {
      "title": "Jane Doe",
      "role": "author",
      "email": "jane@example.com"
    }
  ],
  "keywords": ["climate", "temperature", "weather"],
  "resources": [
    {
      "name": "temperature-readings",
      "path": "data/temperatures.csv",
      "title": "Temperature Readings",
      "schema": {
        "fields": [
          {
            "name": "station_id",
            "type": "string"
          },
          {
            "name": "date",
            "type": "date"
          },
          {
            "name": "temperature",
            "type": "number"
          }
        ]
      }
    }
  ]
}
```

---

## 2. Data Resource

A **Data Resource** describes a single data file or data source (like an individual table or file).

### Required Properties

- **`name`**: Unique identifier (lowercase alphanumeric, periods, hyphens, underscores)

### Data Location (choose one)

- **`path`**: Path to file (local relative path or remote URL)
- **`data`**: Inline data within the descriptor

### Optional Properties

- **`title`**: Human-readable name
- **`description`**: Detailed description
- **`format`**: File format (e.g., 'csv', 'json', 'xlsx')
- **`mediatype`**: MIME type (e.g., 'text/csv')
- **`encoding`**: Character encoding (e.g., 'utf-8')
- **`schema`**: Data structure description (often a Table Schema)

### Example: Resource with Path

```json
{
  "name": "sales-data",
  "title": "Sales Data Q1 2024",
  "path": "data/sales-q1-2024.csv",
  "format": "csv",
  "mediatype": "text/csv",
  "encoding": "utf-8",
  "description": "Quarterly sales data including revenue, units sold, and region."
}
```

### Example: Resource with Inline Data

```json
{
  "name": "countries",
  "title": "Country Codes",
  "data": [
    {"code": "US", "name": "United States"},
    {"code": "GB", "name": "United Kingdom"},
    {"code": "NO", "name": "Norway"}
  ]
}
```

### Example: Resource with Remote URL

```json
{
  "name": "population-data",
  "path": "https://example.com/data/population-2024.csv",
  "format": "csv",
  "schema": {
    "fields": [
      {"name": "country", "type": "string"},
      {"name": "year", "type": "integer"},
      {"name": "population", "type": "integer"}
    ]
  }
}
```

---

## 3. Table Schema

**Table Schema** is a language-agnostic specification for defining the structure of tabular data. It provides detailed descriptions of fields, types, and constraints.

### Structure

```json
{
  "fields": [ ... ],
  "primaryKey": "field_name" or ["field1", "field2"],
  "foreignKeys": [ ... ],
  "missingValues": [""]
}
```

### Field Properties

Each field in the `fields` array has:

- **`name`** (required): Field name
- **`type`** (recommended): Data type
- **`format`**: Specific format for the type
- **`title`**: Human-readable title
- **`description`**: Field description
- **`constraints`**: Validation rules

### Field Types

| Type | Description | Example |
|------|-------------|---------|
| `string` | Text data | "Hello World" |
| `number` | Numeric data (int or float) | 3.14, 42 |
| `integer` | Whole numbers | 42 |
| `boolean` | True/false values | true, false |
| `date` | Date values | 2024-01-15 |
| `datetime` | Date and time | 2024-01-15T10:30:00Z |
| `time` | Time values | 10:30:00 |
| `year` | Year values | 2024 |
| `object` | JSON object | {"key": "value"} |
| `array` | JSON array | [1, 2, 3] |
| `geopoint` | Geographic coordinates | [45.5231, -122.6765] |
| `geojson` | GeoJSON data | {...} |

### Field Constraints

- **`required`** (boolean): Field cannot be null/missing
- **`unique`** (boolean): All values must be unique
- **`minLength`** / **`maxLength`** (integer): String length constraints
- **`minimum`** / **`maximum`** (number): Numeric range constraints
- **`pattern`** (string): Regular expression validation
- **`enum`** (array): Restrict to specific allowed values

### Example: Basic Table Schema

```json
{
  "fields": [
    {
      "name": "id",
      "type": "integer",
      "title": "User ID",
      "constraints": {
        "required": true,
        "unique": true
      }
    },
    {
      "name": "name",
      "type": "string",
      "title": "Full Name",
      "constraints": {
        "required": true,
        "minLength": 2,
        "maxLength": 100
      }
    },
    {
      "name": "age",
      "type": "integer",
      "title": "Age",
      "constraints": {
        "minimum": 0,
        "maximum": 120
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
      "name": "status",
      "type": "string",
      "constraints": {
        "enum": ["active", "inactive", "pending"]
      }
    }
  ],
  "primaryKey": "id",
  "missingValues": ["", "N/A", "null"]
}
```

### Example: Advanced Table Schema with Foreign Keys

```json
{
  "fields": [
    {
      "name": "order_id",
      "type": "integer",
      "constraints": {
        "required": true,
        "unique": true
      }
    },
    {
      "name": "customer_id",
      "type": "integer",
      "constraints": {
        "required": true
      }
    },
    {
      "name": "order_date",
      "type": "date",
      "format": "default",
      "constraints": {
        "required": true
      }
    },
    {
      "name": "total_amount",
      "type": "number",
      "constraints": {
        "minimum": 0
      }
    }
  ],
  "primaryKey": "order_id",
  "foreignKeys": [
    {
      "fields": "customer_id",
      "reference": {
        "resource": "customers",
        "fields": "id"
      }
    }
  ]
}
```

---

## Complete Example: Multi-Resource Data Package

Here's a complete example showing how all the specifications work together:

**datapackage.json:**

```json
{
  "name": "ecommerce-sample-data",
  "title": "E-commerce Sample Dataset",
  "version": "1.0.0",
  "description": "Sample e-commerce data including customers, orders, and products",
  "licenses": [
    {
      "name": "CC-BY-4.0",
      "title": "Creative Commons Attribution 4.0"
    }
  ],
  "resources": [
    {
      "name": "customers",
      "path": "data/customers.csv",
      "format": "csv",
      "schema": {
        "fields": [
          {
            "name": "id",
            "type": "integer",
            "constraints": {"required": true, "unique": true}
          },
          {
            "name": "name",
            "type": "string",
            "constraints": {"required": true}
          },
          {
            "name": "email",
            "type": "string",
            "format": "email",
            "constraints": {"required": true, "unique": true}
          },
          {
            "name": "created_at",
            "type": "datetime"
          }
        ],
        "primaryKey": "id"
      }
    },
    {
      "name": "orders",
      "path": "data/orders.csv",
      "format": "csv",
      "schema": {
        "fields": [
          {
            "name": "order_id",
            "type": "integer",
            "constraints": {"required": true, "unique": true}
          },
          {
            "name": "customer_id",
            "type": "integer",
            "constraints": {"required": true}
          },
          {
            "name": "order_date",
            "type": "date"
          },
          {
            "name": "total",
            "type": "number",
            "constraints": {"minimum": 0}
          }
        ],
        "primaryKey": "order_id",
        "foreignKeys": [
          {
            "fields": "customer_id",
            "reference": {
              "resource": "customers",
              "fields": "id"
            }
          }
        ]
      }
    },
    {
      "name": "product_categories",
      "title": "Product Categories Lookup",
      "data": [
        {"id": 1, "name": "Electronics"},
        {"id": 2, "name": "Clothing"},
        {"id": 3, "name": "Books"}
      ],
      "schema": {
        "fields": [
          {"name": "id", "type": "integer"},
          {"name": "name", "type": "string"}
        ],
        "primaryKey": "id"
      }
    }
  ]
}
```

---

## Benefits and Use Cases

### Benefits

1. **Self-describing data**: Metadata travels with the data
2. **Validation**: Schemas enable automatic data validation
3. **Interoperability**: Standard format works across tools and platforms
4. **Documentation**: Built-in documentation through descriptions
5. **Versioning**: Track changes with version numbers
6. **Reproducibility**: Clear provenance and structure

### Use Cases

- **Research Data Management**: Package research datasets with complete metadata
- **Open Data Publishing**: Share government or public data with clear schemas
- **Data Pipelines**: Standardize data flowing through ETL processes
- **API Documentation**: Describe API response structures
- **Data Catalogs**: Build searchable data repositories
- **Data Quality**: Validate data against defined schemas

---

## Tools and Ecosystem

The Frictionless Data ecosystem includes:

- **Frictionless Framework** (Python): Create, validate, and transform data packages
- **Data Package Creator**: Web-based tool for creating data packages
- **Goodtables**: Data validation tool
- **Libraries**: Available in Python, JavaScript, R, and other languages

---

## References

- Official Website: https://frictionlessdata.io/
- Specifications: https://specs.frictionlessdata.io/
- GitHub: https://github.com/frictionlessdata
