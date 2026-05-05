# Quick Start

Get started with sunstone-py in minutes.

## 1. Set Up Your Project with datasets.yaml

Create a `datasets.yaml` file in your project directory:

```yaml
publish:
  enabled: true
  to: gs://my-bucket/datasets/schools/

inputs:
  - name: School Data
    slug: school-data
    location: data/schools.csv
    source:
      name: Ministry of Education
      location:
        data: https://example.com/schools.csv
      attributedTo: Ministry of Education
      acquiredAt: 2025-01-15
      acquisitionMethod: manual-download
      license: CC-BY-4.0
    fields:
      - name: school_id
        type: string
      - name: enrollment
        type: integer

outputs: []
```

## 2. Use Pandas-Like API with Lineage Tracking

```python
from sunstone import pandas as pd
from pathlib import Path

# Set project path (where datasets.yaml lives)
PROJECT_PATH = Path.cwd()

# Read data - lineage automatically tracked
df = pd.read_csv('data/schools.csv', project_path=PROJECT_PATH)

# Transform using familiar pandas operations
result = df[df['enrollment'] > 100].groupby('district').sum()

# Save with automatic lineage tracking and dataset registration
result.to_csv(
    'outputs/summary.csv',
    slug='school-summary',
    name='School Enrollment Summary',
    index=False
)
```

## 3. Check Lineage Metadata

```python
# View lineage information (via metadata container)
print(result.metadata.lineage.sources)      # Source datasets
print(result.metadata.lineage.get_licenses())  # All source licenses

# Check field-level provenance
for fd in result.metadata.lineage.field_derivations:
    print(f"  {fd.output_field} <- {fd.source_entity}")
```

## 4. Annotate Columns (Optional)

```python
# Add descriptions and units to columns
result.set_field_metadata('enrollment', description='Total enrolled students', unit='students')

# Save as Parquet instead of CSV
result.to_parquet(
    'outputs/summary.parquet',
    slug='school-summary',
    name='School Enrollment Summary'
)
```

## Next Steps

- Learn about the [CLI tools](cli.md) for dataset management
- Understand [core concepts](concepts.md) like strict mode and lineage tracking
- Browse the [API reference](api.md) for detailed documentation
- Check out [examples](examples.md) for real-world usage patterns
