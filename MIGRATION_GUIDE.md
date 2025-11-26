# Migration Guide: Switching to GitHub-Hosted sunstone-py

This guide walks you through migrating existing Sunstone projects from the local `file:///` installation to the GitHub-hosted package.

## Overview

**Before:** Projects used a local file reference:
```toml
"sunstone-py @ file:///${PROJECT_ROOT}/../lib"
```

**After:** Projects use the GitHub repository:
```toml
"sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git"
```

## Prerequisites

- Git access to the sunstoneinstitute GitHub organization
- Python 3.10 or newer
- `uv` package manager installed

## Migration Steps

### Step 1: Update pyproject.toml

For each project (e.g., `SchoolCountProject`, `FishFarmingProject`):

1. Open `pyproject.toml`
2. Find the dependencies section
3. Replace the sunstone-py line:

**Before:**
```toml
[project]
dependencies = [
    "pandas>=2.0.0",
    "sunstone-py @ file:///${PROJECT_ROOT}/../lib",
]
```

**After:**
```toml
[project]
dependencies = [
    "pandas>=2.0.0",
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git",
]
```

### Step 2: Clean and Reinstall

Remove the old virtual environment and reinstall:

```bash
cd SchoolCountProject  # or your project name

# Remove old venv
rm -rf .venv

# Create fresh venv
uv venv

# Activate (macOS/Linux)
source .venv/bin/activate

# Or on Windows
# .\.venv\Scripts\activate

# Install dependencies from GitHub
uv sync
```

### Step 3: Verify Installation

Test that sunstone-py is installed correctly:

```bash
# Check installed package
uv pip list | grep sunstone-py

# Run Python to verify import
python -c "from sunstone import pandas as pd; print('Success!')"
```

### Step 4: Test Your Project

Run your project's tests or main scripts to ensure everything works:

```bash
# If you have pytest tests
uv run pytest

# Or run your main script
python your_analysis.py
```

### Step 5: Commit Changes

```bash
git add pyproject.toml uv.lock
git commit -m "Migrate to GitHub-hosted sunstone-py package"
```

## Using Specific Versions

### Pin to a Specific Git Tag

```toml
dependencies = [
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git@v0.1.0",
]
```

### Pin to a Specific Commit

```toml
dependencies = [
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git@abc1234",
]
```

### Use a Specific Branch

```toml
dependencies = [
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git@develop",
]
```

**Recommendation:** Use tagged releases (e.g., `@v0.1.0`) for production projects.

## Updating sunstone-py

### Update to Latest Version

```bash
# Update dependency
uv lock --upgrade-package sunstone-py

# Sync environment
uv sync
```

### Update to Specific Version

Edit `pyproject.toml` to change the tag:

```toml
"sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git@v0.2.0"
```

Then:
```bash
uv sync
```

## Troubleshooting

### Issue: "Could not find a version that satisfies the requirement"

**Solution:** Ensure you have access to the GitHub repository. If it's private, set up SSH keys:

```bash
# Test GitHub access
ssh -T git@github.com

# Should show: "Hi username! You've successfully authenticated..."
```

### Issue: "No module named 'sunstone'"

**Solution:** The package wasn't installed. Try:

```bash
uv sync --reinstall-package sunstone-py
```

### Issue: Import errors or missing features

**Solution:** You might be using an old cached version. Clear uv cache:

```bash
uv cache clean
uv sync
```

### Issue: Installation is slow

**Solution:** GitHub installs can be slower than local. This is normal. To speed up:

1. Use a specific tag instead of `main` branch
2. Ensure you have a good internet connection

### Issue: Want to use local development version

**Solution:** Temporarily switch back to local for development:

```toml
dependencies = [
    "sunstone-py @ file:///${PROJECT_ROOT}/../lib",
]
```

Or install in editable mode:

```bash
cd ../lib  # or path to sunstone-py repo
uv pip install -e .
```

## Migration Checklist for Each Project

Use this checklist when migrating each project:

- [ ] Update `pyproject.toml` with GitHub URL
- [ ] Remove and recreate `.venv`
- [ ] Run `uv sync`
- [ ] Verify import: `python -c "from sunstone import pandas as pd"`
- [ ] Run project tests
- [ ] Run main analysis scripts
- [ ] Commit `pyproject.toml` and `uv.lock`
- [ ] Update project README if it mentions local installation

## Project-Specific Notes

### ExampleProject

```bash
cd ExampleProject
# Follow steps 1-5 above
```

### SchoolCountProject

```bash
cd SchoolCountProject
# Follow steps 1-5 above
# Note: This project has specific datasets in datasets.yaml
```

### FishFarmingProject

```bash
cd FishFarmingProject
# Follow steps 1-5 above
```

## Rollback Plan

If you need to rollback to local installation:

1. Restore old `pyproject.toml`:
   ```bash
   git checkout HEAD -- pyproject.toml uv.lock
   ```

2. Reinstall:
   ```bash
   rm -rf .venv
   uv venv
   uv sync
   ```

## Benefits of GitHub Installation

✅ **No local path dependencies** - Works anywhere, not just in projects repo
✅ **Version control** - Pin to specific releases
✅ **Easier collaboration** - New team members just need `uv sync`
✅ **CI/CD friendly** - GitHub Actions can install directly
✅ **Simpler onboarding** - One command to get started

## Questions?

If you encounter issues during migration:

1. Check the [sunstone-py repository](https://github.com/sunstoneinstitute/sunstone-py) for updates
2. Review the [README](https://github.com/sunstoneinstitute/sunstone-py/blob/main/README.md)
3. Check [GitHub Issues](https://github.com/sunstoneinstitute/sunstone-py/issues)
4. Contact stig@sunstone.institute
