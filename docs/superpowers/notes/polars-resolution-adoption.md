# Polars adoption of shared path resolution

When `feat/polars-spec` rebases onto the path-driven-resolution work, adopt the
shared resolver so polars matches pandas/geopandas exactly:

- Replace the inline `is_slug = "/" not in loc and ...` heuristic in
  `src/sunstone/polars/io.py::_read_path_or_slug` with
  `from sunstone.resolution import looks_like_slug` and route the path branch
  through `sunstone.resolution.resolve_to_dataset(loc, manager)`.
- In the polars write helper (`src/sunstone/polars/write.py::_write`), after the
  `find_dataset_by_location(location, "output")` lookup, call
  `sunstone.resolution.check_slug_conflict(dataset, slug)` and store the
  auto-register `location=` via `sunstone.resolution.portable_location(...)`.
  Note: resolve a RELATIVE write path against `manager.project_path` before
  calling `portable_location` (mirror the pandas `to_csv`/`to_parquet` `_abs_loc`
  handling), so the stored location matches where the file is physically written.
- No changes to `find_dataset_by_location` are needed — polars already calls it
  and inherits the cwd-aware, cached behavior.
- Add polars equivalents of the cwd-relative read test and the slug-conflict
  write test.
