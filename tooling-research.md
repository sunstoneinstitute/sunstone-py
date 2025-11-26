# Data Science Tooling and Scaffolding Research

This document summarizes research into practical approaches used by data science teams to scale efforts, improve developer experience (DX), and ensure reproducibility and data quality.

## Executive Summary

Scaling data science teams requires shifting from ad-hoc "notebook-first" workflows to engineering-disciplined "production-first" mindsets. The industry standard for reducing toil involves **standardized project templates** (scaffolding), **rigorous environment management**, and **specialized tooling** for data versioning and experiment tracking. The goal is to make the "right way" the "easy way" for data scientists.

## 1. Project Scaffolding & Standardization

Standardization is the highest-leverage activity for scaling teams. It reduces context switching and allows tooling to assume a fixed structure.

### Practical Approaches
*   **Cookiecutter Data Science:** The de facto standard for directory structure. It separates raw data from processed data, and notebooks from source code.
    *   *Key Concept:* "Data is immutable." `data/raw` is never edited manually.
*   **Modern Templating Tools:**
    *   **Copier:** Superior to Cookiecutter for long-term maintenance. It allows applying template updates to existing projects (e.g., if the team upgrades the linter configuration, old projects can be updated automatically).
    *   **Kedro:** A more opinionated framework that enforces a specific pipeline structure. It treats data catalogs and pipelines as first-class citizens, abstracting away file paths.
*   **Sunstone Relevance:** The existing `UNMembersProject` structure aligns well with these standards. Adopting **Copier** for the Sunstone scaffold would allow you to push updates (like new CI workflows) to all downstream projects.

## 2. Core Developer Experience (DX) Tooling

The "Modern Data Stack" for Python has evolved significantly in the last 2-3 years to focus on speed and reliability.

### Environment Management
*   **uv (Astral):** Emerging as the fastest Python package installer and resolver. It replaces `pip`, `pip-tools`, and `virtualenv`.
    *   *Note:* Your project already uses `uv.lock`, which places you at the cutting edge here. This is a huge DX win for speed.
*   **Docker (Dev Containers):** defining a `.devcontainer` allows the entire team to develop in an identical OS environment (VS Code integration), eliminating "it works on my machine" issues regarding system libraries (like GDAL or pyodbc).

### Code Quality & Linting
*   **Ruff:** An extremely fast Python linter and formatter (written in Rust) that replaces Flake8, Black, and isort. Its speed allows it to run on "save" without interrupting flow.
*   **Pre-commit Hooks:** Automatically running checks (trailing whitespace, large file checks, linting) before a git commit prevents low-quality code from entering the repo.

## 3. Data Quality & Validation

Moving beyond "eye-balling" CSVs is critical for scale.

*   **Great Expectations (GX):** The heavy-weight standard. It allows defining "Expectations" (e.g., "column 'age' must not be null", "column 'iso_code' values must match set {...}"). It generates HTML data docs automatically.
*   **Pandera:** A lighter-weight, code-centric alternative that defines validation schemas as Python decorators on pandas DataFrames. It integrates well with type hints.
*   **Pydantic:** While primarily for general Python, it is increasingly used for strictly typed data ingestion schemas.

## 4. Reproducibility & Lineage

### Data Version Control (DVC)
*   Git is poor at handling large binary files. **DVC** solves this by tracking metadata (MD5 hashes) in Git, while storing the actual files in S3/GCS/Azure Blob.
*   *DX Benefit:* A new team member can clone the repo and run `dvc pull` to get the exact dataset version used for the analysis, without asking around for "v2_final.csv".

### Experiment Tracking
*   **MLflow / Weights & Biases:** These tools track parameters, metrics, and model artifacts. They are essential when research moves from data processing to modeling, allowing teams to compare runs visually.

## 5. Recommendations for Sunstone

Based on the `UNMembersProject` and current industry trends, here are specific recommendations:

1.  **Formalize the Template:** Move the `tests/testdata/UNMembersProject` structure into a formal **Copier** template. This supports future updates better than a static folder copy.
2.  **Integrate Data Validation:** Add a lightweight validation step (like `pandera`) to the pipeline. The `create_un_members_dataset.py` script currently has good logic but implicit schemas. Explicit schemas serve as documentation and safety.
3.  **Lineage Tracking:** Consider how to track that `outputs/current.csv` was derived from `inputs/raw.csv` using `script.py` v1.0. Simple metadata logging (which you have started with `datasets.yaml`) is a good start, but automating this via a lightweight dag (like `dagster` or just strict DVC stages) adds robustness.
4.  **Makefile / Task Runner:** Abstract complex commands. A `Makefile` or `Justfile` with commands like `make data` or `make validate` simplifies the entry point for new scientists.
