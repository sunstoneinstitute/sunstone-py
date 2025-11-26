# Repository Setup Checklist

This document outlines the steps to extract the sunstone-py library from the projects repository and set it up as a standalone public repository.

## Pre-Extraction Checklist

- [x] Verify lib/ is self-contained with no external dependencies
- [x] Create LICENSE file (MIT)
- [x] Create CHANGELOG.md
- [x] Create CONTRIBUTING.md
- [x] Draft new README.md for standalone repo
- [x] Update templates/README.md to remove parent repo references
- [x] Create GitHub Actions workflow for CI/CD
- [x] Run tests to ensure everything works: `cd lib && uv run pytest`
- [x] Verify package builds: `cd lib && uv build`

## GitHub Repository Creation

### 1. Create New Repository

1. Go to https://github.com/organizations/sunstoneinstitute/repositories/new
2. Repository name: `sunstone-py`
3. Description: "Python library for managing datasets with lineage tracking in data science projects"
4. Visibility: **Public**
5. Do NOT initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

### 2. Initial Push

From the `lib/` directory:

```bash
# Initialize git in lib directory
cd lib
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Extract sunstone-py library

- Core lineage tracking functionality
- DatasetsManager for datasets.yaml integration
- Pandas-compatible API
- Validation tools
- Documentation and examples
"

# Add remote
git remote add origin git@github.com:sunstoneinstitute/sunstone-py.git

# Push to GitHub
git branch -M main
git push -u origin main
```

### 3. Configure Repository Settings

#### About Section
- Description: "Python library for managing datasets with lineage tracking in data science projects"
- Website: https://sunstoneinstitute.ai
- Topics: `python`, `data-science`, `lineage-tracking`, `pandas`, `datasets`

#### Branch Protection (Optional for now, enable when ready)
- Protect `main` branch
- Require pull request reviews
- Require status checks to pass

#### GitHub Pages (Optional - for documentation)
- Source: Deploy from a branch
- Branch: `gh-pages` (create later for documentation)

## Post-Creation Tasks

### 1. Verify GitHub Actions Work

- Navigate to Actions tab
- Ensure workflows run successfully on the initial commit
- Fix any failing tests or CI issues

### 2. Create Initial Release (v0.1.0)

```bash
# Tag the initial release
git tag -a v0.1.0 -m "Initial public release

- DataFrame wrapper with lineage tracking
- datasets.yaml integration
- Pandas-compatible API
- Validation tools
"

# Push the tag
git push origin v0.1.0
```

Then on GitHub:
1. Go to Releases → Draft a new release
2. Choose tag `v0.1.0`
3. Title: `v0.1.0 - Initial Public Release`
4. Description: Copy from CHANGELOG.md
5. Click "Publish release"

### 3. Update README.md in Projects Repo

Replace `lib/README.md` with pointer to new repository:

```markdown
# sunstone-py

This library has been extracted to its own repository:

**https://github.com/sunstoneinstitute/sunstone-py**

For installation and usage, see the main repository.

## Quick Install

```bash
pip install git+https://github.com/sunstoneinstitute/sunstone-py.git
```

## Development

To work on this library, clone the standalone repository:

```bash
git clone https://github.com/sunstoneinstitute/sunstone-py.git
```
```

### 4. Update Project Dependencies

Update all project `pyproject.toml` files to use the new GitHub URL:

**Old:**
```toml
dependencies = [
    "sunstone-py @ file:///${PROJECT_ROOT}/../lib",
]
```

**New:**
```toml
dependencies = [
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git",
]
```

See MIGRATION_GUIDE.md for detailed migration steps.

### 5. Optional: Archive lib/ in Projects Repo

After successful migration:

```bash
# From projects repo root
mv lib lib-archived

# Update .gitignore
echo "lib-archived/" >> .gitignore

# Commit
git add .
git commit -m "Archive lib/ directory after extraction to sunstone-py repo"
```

## Repository Maintenance

### Regular Tasks

1. **Keep dependencies updated**
   ```bash
   uv lock --upgrade
   ```

2. **Monitor GitHub Actions**
   - Check for failing tests
   - Keep workflows up to date

3. **Review and merge PRs**
   - Ensure tests pass
   - Review code quality
   - Update CHANGELOG.md

4. **Create releases**
   - Follow semantic versioning
   - Update CHANGELOG.md
   - Create GitHub release with notes

### Version Release Process

When ready to release a new version:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md` with new version and date
3. Commit changes: `git commit -m "Bump version to X.Y.Z"`
4. Create and push tag: `git tag -a vX.Y.Z -m "Release X.Y.Z" && git push origin vX.Y.Z`
5. Create GitHub release from tag

## Rollback Plan

If issues arise after extraction:

1. Projects can temporarily use local path:
   ```toml
   dependencies = [
       "sunstone-py @ file:///${PROJECT_ROOT}/../lib-archived",
   ]
   ```

2. Fix issues in standalone repo
3. Update projects to use GitHub URL again

## Success Criteria

- [x] Repository created and public
- [ ] GitHub Actions running successfully
- [ ] Initial release (v0.1.0) published
- [ ] At least one project successfully migrated to use GitHub URL
- [ ] Documentation is clear and complete
- [ ] All tests passing
