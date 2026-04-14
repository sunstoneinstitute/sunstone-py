# Examples

Real-world examples of using sunstone-py for data science workflows.

## Basic Data Pipeline

Complete example of reading, transforming, and saving data with lineage tracking.

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

# Read input data
schools = pd.read_csv('data/schools.csv', project_path=PROJECT_PATH)
teachers = pd.read_csv('data/teachers.csv', project_path=PROJECT_PATH)

# Transform and merge
schools_summary = schools.groupby('district')['enrollment'].agg(['sum', 'mean'])
teacher_counts = teachers.groupby('school_id').size().rename('teacher_count')

# Join datasets
result = schools.join(teacher_counts, on='school_id')
result = result.merge(schools_summary, left_on='district', right_index=True)

# Calculate student-teacher ratio
result['student_teacher_ratio'] = result['enrollment'] / result['teacher_count']

# Save with lineage
result.to_csv(
    'outputs/school_analysis.csv',
    slug='school-analysis',
    name='School Analysis with Teacher Ratios',
    publish=True,
    index=False
)

# Check lineage
print(f"Sources: {[s.name for s in result.metadata.lineage.sources]}")
print(f"Licenses: {result.metadata.lineage.get_licenses()}")
```

## Working with Multiple Data Sources

Combining data from various sources with proper attribution.

**datasets.yaml:**

```yaml
publish:
  enabled: true
  to: gs://my-bucket/datasets/economic-indicators/

inputs:
  - name: Population Data
    slug: population
    location: data/population.csv
    source:
      name: World Bank
      location:
        data: https://data.worldbank.org/indicator/SP.POP.TOTL
      license: CC-BY-4.0
      attributedTo: World Bank
      acquiredAt: '2025-01-15'
      acquisitionMethod: api
    fields:
      - name: country
        type: string
      - name: year
        type: integer
      - name: population
        type: integer

  - name: GDP Data
    slug: gdp
    location: data/gdp.csv
    source:
      name: IMF
      location:
        data: https://www.imf.org/external/datamapper/NGDP
      license: Custom
      attributedTo: International Monetary Fund
      acquiredAt: '2025-01-15'
      acquisitionMethod: manual-download
    fields:
      - name: country
        type: string
      - name: year
        type: integer
      - name: gdp_usd
        type: number
```

**Script:**

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

# Read both datasets
pop = pd.read_csv('data/population.csv', project_path=PROJECT_PATH)
gdp = pd.read_csv('data/gdp.csv', project_path=PROJECT_PATH)

# Merge on country and year
combined = pd.merge(pop, gdp, on=['country', 'year'])

# Calculate GDP per capita
combined['gdp_per_capita'] = combined['gdp_usd'] / combined['population']

# Save with lineage
combined.to_csv(
    'outputs/gdp_per_capita.csv',
    slug='gdp-per-capita',
    name='GDP Per Capita Analysis',
    publish=True,
    index=False
)

# Lineage automatically tracks both sources
print("Data sources:")
for source in combined.metadata.lineage.sources:
    print(f"  - {source.name} ({source.license})")
```

## Strict Mode Workflow

Production pipeline with strict mode enabled.

**Step 1: Setup datasets.yaml**

```yaml
publish:
  enabled: true
  to: gs://my-bucket/datasets/sales/

inputs:
  - name: Raw Sales Data
    slug: raw-sales
    location: data/raw_sales.csv
    strict: true
    fields:
      - name: transaction_id
        type: string
      - name: date
        type: date
      - name: amount
        type: number
      - name: customer_id
        type: string

outputs:
  - name: Daily Sales Summary
    slug: daily-summary
    location: outputs/daily_summary.csv
    strict: true
    fields:
      - name: date
        type: date
      - name: total_sales
        type: number
      - name: transaction_count
        type: integer
```

**Step 2: Lock datasets via CLI**

```bash
sunstone dataset lock
```

**Step 3: Run production script**

```python
from sunstone import pandas as pd
from pathlib import Path
import sys

PROJECT_PATH = Path.cwd()

try:
    # In strict mode, this will fail if dataset not registered
    sales = pd.read_csv('data/raw_sales.csv', project_path=PROJECT_PATH)

    # Transform
    daily = sales.groupby('date').agg({
        'amount': 'sum',
        'transaction_id': 'count'
    }).rename(columns={
        'amount': 'total_sales',
        'transaction_id': 'transaction_count'
    })

    # In strict mode, this will fail if schema doesn't match
    daily.to_csv(
        'outputs/daily_summary.csv',
        slug='daily-summary',
        name='Daily Sales Summary'
    )

except Exception as e:
    print(f"Pipeline failed: {e}", file=sys.stderr)
    sys.exit(1)

print("✓ Pipeline completed successfully")
```

**Step 4: Validate and push**

```bash
# Validate first
sunstone dataset validate

# Push to production
sunstone package push --env prod
```

## Exploratory Analysis with Auto-Registration

Interactive notebook workflow with relaxed mode.

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

# Read data (must be in datasets.yaml)
df = pd.read_csv('data/survey_responses.csv', project_path=PROJECT_PATH)

# Explore the data
print(df.describe())
print(df.groupby('category').size())

# Create derived dataset
age_groups = df.groupby('age_group')['satisfaction'].mean()

# Save - this auto-registers in datasets.yaml
age_groups.to_csv(
    'outputs/satisfaction_by_age.csv',
    slug='satisfaction-by-age',
    name='Satisfaction Scores by Age Group',
    index=True
)

# Create another view
by_region = df.groupby(['region', 'category']).agg({
    'satisfaction': 'mean',
    'response_id': 'count'
})

# Auto-register this too
by_region.to_csv(
    'outputs/satisfaction_by_region.csv',
    slug='satisfaction-by-region',
    name='Satisfaction Scores by Region and Category'
)

# Now review datasets.yaml and adjust as needed
# Then lock for production:
# sunstone dataset lock satisfaction-by-age satisfaction-by-region
```

## Custom Operations with Lineage

Track custom transformations in lineage.

```python
from sunstone import pandas as pd, DataFrame
from pathlib import Path
import numpy as np

PROJECT_PATH = Path.cwd()

df = pd.read_csv('data/measurements.csv', project_path=PROJECT_PATH)

# Define custom operation
def remove_outliers(data):
    """Remove values beyond 3 standard deviations."""
    mean = data['value'].mean()
    std = data['value'].std()
    mask = np.abs(data['value'] - mean) <= 3 * std
    return data[mask]

# Apply with lineage tracking
cleaned = df.apply_operation(
    remove_outliers,
    description="Remove outliers (>3 std dev)"
)

# Define another operation
def normalize_values(data):
    """Normalize values to 0-1 range."""
    min_val = data['value'].min()
    max_val = data['value'].max()
    data['value'] = (data['value'] - min_val) / (max_val - min_val)
    return data

# Chain operations
normalized = cleaned.apply_operation(
    normalize_values,
    description="Normalize values to [0,1] range"
)

# Save final result
normalized.to_csv(
    'outputs/processed_measurements.csv',
    slug='processed-measurements',
    name='Processed Measurements',
    index=False
)

# Check operations in lineage
print("Operations performed:")
for op in normalized.metadata.lineage.operations:
    print(f"  - {op}")
```

## Programmatic Dataset Management

Manage datasets.yaml via Python API.

```python
from sunstone import DatasetsManager, FieldSchema
from pathlib import Path

manager = DatasetsManager(Path.cwd())

# Add a new output dataset
manager.add_output_dataset(
    name='Weekly Aggregated Sales',
    slug='weekly-sales',
    location='outputs/weekly_sales.csv',
    fields=[
        FieldSchema(name='week_start', type='date'),
        FieldSchema(name='week_end', type='date'),
        FieldSchema(name='total_revenue', type='number'),
        FieldSchema(name='order_count', type='integer'),
        FieldSchema(name='avg_order_value', type='number')
    ]
)

# Enable strict mode for specific datasets
manager.set_dataset_strict('weekly-sales', strict=True)
manager.set_dataset_strict('daily-summary', strict=True)

# Check publish configuration
publish_config = manager.get_publish_config()
if publish_config and publish_config.enabled:
    print(f"Publishing enabled to: {publish_config.to}")
    print(f"Flatten: {publish_config.flatten}")

# Query datasets
all_outputs = manager.get_all_outputs()

print(f"Total outputs: {len(all_outputs)}")
print("\nOutput datasets:")
for ds in all_outputs:
    strict_flag = " [strict]" if ds.strict else ""
    print(f"  - {ds.slug}: {ds.location}{strict_flag}")
```

## Validation in CI/CD

Integrate validation into your CI pipeline.

**validate.py:**

```python
#!/usr/bin/env python3
"""Validate all datasets and notebooks in the project."""

import sys
from pathlib import Path
from sunstone import validate_project_notebooks
from sunstone.datasets import DatasetsManager

PROJECT_PATH = Path(__file__).parent
errors = []

# Validate datasets.yaml structure
print("Validating datasets.yaml...")
try:
    manager = DatasetsManager(PROJECT_PATH)
    inputs = manager.get_all_inputs()
    outputs = manager.get_all_outputs()
    print(f"✓ Found {len(inputs)} inputs, {len(outputs)} outputs")
except Exception as e:
    errors.append(f"datasets.yaml validation failed: {e}")

# Validate notebook imports
print("\nValidating notebook imports...")
results = validate_project_notebooks(PROJECT_PATH)
for path, result in results.items():
    if result.is_valid:
        print(f"✓ {path.name}")
    else:
        print(f"✗ {path.name}")
        errors.append(result.summary())

# Exit with error if any validation failed
if errors:
    print("\n❌ Validation failed:")
    for error in errors:
        print(f"\n{error}")
    sys.exit(1)
else:
    print("\n✅ All validations passed")
    sys.exit(0)
```

**.github/workflows/validate.yml:**

```yaml
name: Validate Data Pipeline

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v1

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync

      - name: Validate datasets
        run: uv run sunstone dataset validate

      - name: Validate notebooks
        run: uv run python validate.py
```

## Publishing Data Packages

Build and publish data packages to GCS.

**Makefile:**

```makefile
.PHONY: validate build push-dev push-prod

validate:
	uv run sunstone dataset validate

build: validate
	uv run sunstone package build

push-dev: build
	uv run sunstone package push --env dev

push-prod: build
	@echo "Pushing to production..."
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		uv run sunstone package push --env prod; \
	fi

clean:
	rm -f datapackage.json
```

**Usage:**

```bash
# Development workflow
make push-dev

# Production release
make push-prod
```

## Writing Parquet Files

Save DataFrames in Parquet format with lineage tracking.

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

df = pd.read_csv('data/measurements.csv', project_path=PROJECT_PATH)

# Filter and save as Parquet
result = df[df['value'] > 0]
result.to_parquet(
    'outputs/measurements.parquet',
    slug='filtered-measurements',
    name='Filtered Measurements'
)
```

## Using Field Metadata

Annotate columns with descriptions, units, and source tracking.

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

pop = pd.read_csv('data/population.csv', project_path=PROJECT_PATH)
area = pd.read_csv('data/area.csv', project_path=PROJECT_PATH)

# Set field metadata with method chaining
combined = pd.merge(pop, area, on='country')
combined.set_field_metadata('population', description='Total population', unit='people')
combined.set_field_metadata('area_km2', description='Land area', unit='km^2')

# Compute derived column
combined['density'] = combined['population'] / combined['area_km2']
combined.set_field_metadata('density', description='Population density', unit='people / km^2')

# Save — field metadata flows to datasets.yaml
combined.to_csv(
    'outputs/density.csv',
    slug='population-density',
    name='Population Density by Country',
    index=False
)
```

## Reading Datasets by Slug

Use `read_dataset()` for format-agnostic reading by slug.

```python
from sunstone import pandas as pd

# Auto-detects format from file extension in datasets.yaml
df = pd.read_dataset('official-un-member-states')

# Explicit format override
df = pd.read_dataset('my-data', format='json')
```

## Checking Field-Level Provenance

Inspect which columns came from which source datasets.

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

schools = pd.read_csv('data/schools.csv', project_path=PROJECT_PATH)
teachers = pd.read_csv('data/teachers.csv', project_path=PROJECT_PATH)

merged = pd.merge(schools, teachers, on='school_id')

# Each column knows its source
for fd in merged.metadata.lineage.field_derivations:
    print(f"  {fd.output_field} <- {fd.source_entity}.{fd.source_field}")
```

## Advanced: Multi-Stage Pipeline

Complex pipeline with multiple intermediate steps.

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

# Stage 1: Load raw data
raw = pd.read_csv('data/raw_data.csv', project_path=PROJECT_PATH)

# Stage 2: Clean
cleaned = raw.apply_operation(
    lambda df: df.dropna(),
    description="Remove missing values"
)

cleaned.to_csv(
    'intermediate/cleaned.csv',
    slug='cleaned-data',
    name='Cleaned Data'
)

# Stage 3: Transform
transformed = cleaned.apply_operation(
    lambda df: df.assign(
        normalized=df['value'] / df['value'].max()
    ),
    description="Normalize values"
)

transformed.to_csv(
    'intermediate/transformed.csv',
    slug='transformed-data',
    name='Transformed Data'
)

# Stage 4: Aggregate
final = transformed.groupby('category').agg({
    'normalized': ['mean', 'std', 'count']
})

final.to_csv(
    'outputs/final_analysis.csv',
    slug='final-analysis',
    name='Final Analysis Results',
    publish=True
)

# Complete lineage is preserved
print("\nLineage chain:")
print(f"Sources: {len(final.metadata.lineage.sources)}")
print(f"Operations: {len(final.metadata.lineage.operations)}")
for op in final.metadata.lineage.operations:
    print(f"  → {op}")
```
