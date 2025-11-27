"""Data Analysis Template - Marimo Notebook

This template provides the correct setup for using Sunstone's lineage tracking
in a Marimo notebook.

**Important**: Always use `from sunstone import pandas as pd` instead of
`import pandas as pd` to enable lineage tracking.

To run this notebook:
    marimo edit analysis_notebook.py

To run non-interactively:
    marimo run analysis_notebook.py
"""

import marimo

__generated_with = "0.9.14"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        # Data Analysis Template

        This template provides the correct setup for using Sunstone's lineage tracking.

        **Important**: Always use `from sunstone import pandas as pd` instead of
        `import pandas as pd` to enable lineage tracking.
        """
    )
    return


@app.cell
def _():
    # Standard imports for Sunstone projects
    from pathlib import Path
    from sunstone import pandas as pd
    import sunstone
    import marimo as mo

    # Set project path (update this to your actual project directory)
    PROJECT_PATH = Path.cwd()
    mo.md(f"**Project path:** `{PROJECT_PATH}`")
    return PROJECT_PATH, pd, sunstone, mo, Path


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## Load Data

        Load datasets that are registered in `datasets.yaml`. All reads are
        automatically tracked in lineage.
        """
    )
    return


@app.cell
def _(pd, PROJECT_PATH, mo):
    # Read a dataset (must be in datasets.yaml inputs)
    # Update the filename to match your actual input dataset
    df = pd.read_csv("input_data.csv", project_path=PROJECT_PATH)

    # Display the data
    mo.ui.table(df.data.head())

    # Show lineage info
    lineage_info = mo.md(
        f"""
        **Lineage:** {len(df.lineage.sources)} source(s),
        {len(df.lineage.operations)} operation(s)
        """
    )
    return df, lineage_info


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## Transform Data

        All pandas operations work as normal. The underlying data is accessed
        via `.data` when needed.
        """
    )
    return


@app.cell
def _(df, mo):
    # Filter data - update column_name to match your data
    # filtered_df = df[df['column_name'] > 0]

    # Or use apply_operation for complex transformations
    # result_df = df.apply_operation(
    #     lambda data: data[data['column_name'] > 100],
    #     description="Filter rows where column_name > 100"
    # )

    # mo.ui.table(result_df.data.head())

    mo.md("*Uncomment the transformation code above to process your data*")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## Combine Datasets

        Use pandas-like functions to merge, join, or concatenate datasets
        while preserving lineage.
        """
    )
    return


@app.cell
def _(pd, PROJECT_PATH, mo):
    # Example: Load another dataset
    # df2 = pd.read_csv('other_data.csv', project_path=PROJECT_PATH)

    # Merge datasets
    # merged_df = pd.merge(df, df2, on='key_column', how='inner')

    # Concatenate datasets
    # combined_df = pd.concat([df, df2], ignore_index=True)

    # Check combined lineage
    # lineage_msg = mo.md(
    #     f"**Combined lineage:** {len(merged_df.lineage.sources)} source(s)"
    # )

    mo.md("*Uncomment the combination code above to merge datasets*")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## Save Results

        Save your results to create output datasets. In relaxed mode, outputs
        are auto-registered in `datasets.yaml`.
        """
    )
    return


@app.cell
def _(mo):
    # Save the result
    # result_df.to_csv(
    #     'output_data.csv',
    #     slug='output-data',
    #     name='Output Data',
    #     publish=False,  # Set to True when ready to publish
    #     index=False
    # )

    # mo.md("✓ Data saved successfully with full lineage tracking!")

    mo.md("*Uncomment the save code above to write your results*")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## Validate Imports

        Use this cell to check if your notebook is using the correct imports.
        """
    )
    return


@app.cell
def _(sunstone, mo):
    # Check if this notebook uses correct imports
    # Note: You'll need to save this file first before validating
    # result = sunstone.check_notebook_imports('analysis_notebook.py')
    # mo.md(result.summary())

    mo.md(
        """
        *Save this notebook and uncomment the validation code above to check imports*

        For Marimo notebooks, ensure all pandas imports use:
        ```python
        from sunstone import pandas as pd
        ```
        """
    )
    return


if __name__ == "__main__":
    app.run()
