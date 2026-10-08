# Pushing packages to `sunstone:` namespaces

Status: the sunstone-py side is built. The push API and the `sunstone_data` plugin are not.
This page covers the sunstone-py side.
The data-platform side (push API, storage layout, auth rules, serving
formats) is specified in data-platform `docs/specs2`.

## Model

A `sunstone:<ns>/<name>` URL identifies a logical dataset. The storage engine
is a property of the dataset and is not encoded in the URL. `sunstone:` is a
host-free scheme. A reference that names a host uses `https:`.

`sunstone package push` creates one dataset per resource plus a package node
for the namespace. data-platform owns the push logic. sunstone-py is a client:
it holds no Iceberg or S3 write credentials and calls the data-platform push
API through a plugin.

## Package-push plugin protocol

New protocol in `plugins.py`, discovered through the `sunstone.plugins` entry
point group like the other protocols:

```python
@runtime_checkable
class PackagePushHandler(Protocol):
    def can_handle(self, destination: str) -> bool:
        """True if this plugin claims the destination URL."""
        ...

    def push(self, package: PushPackage, options: PushOptions) -> PushResult:
        """Upload resources and metadata, then wait for the server result."""
        ...
```

- `PushResource`: `slug`, `name`, `path` (Parquet for TABULAR), `kind`
  (`AssetKind`), `media_type`, `sha256`, `size`, `metadata`.
- `PushPackage`: `destination`, `namespace`, `resources`, `metadata`,
  `public`, `dialect`.
- `PushOptions`: `env`, `branch`, `yes`, `force`, `replace`.
- `DatasetPushStatus`: `name`, `status`, `iri`, `message`.
- `PushResult`: `push_id`, `ok`, `datasets` (tuple of `DatasetPushStatus`).

`sunstone package push` asks the registry for a handler that claims the
destination. If none does, a `sunstone:` destination is an error, not a
blob-store fallback. Other destinations use `packaging.push_group`, the
blob-store path (GCS, S3, R2). Plugins take priority over built-ins.

Directory stores (Zarr) and methodology files are not pushed to namespaces.

## Asset kinds and engines

Push picks the engine from the resource's `AssetKind`, not from its file
extension.

| AssetKind | Engine |
|---|---|
| TABULAR | Iceberg |
| GRAPH | graph server (named graph) |
| RASTER, ARRAY, TILES, BLOB, GEOFEATURES | object storage |

GEOFEATURES moves to Iceberg once pyiceberg supports geometry.

TABULAR resources are written to Parquet on the client before upload. The
server appends the files to Iceberg. Schema checks run against the Parquet
schema.

### AssetKind.GRAPH

`AssetKind.GRAPH` is a first-class RDF payload (`.ttl`, `.jsonld`, `.nt`),
stored server-side as a named graph. sunstone-py adds an RDF format handler
backed by rdflib, which is a base dependency.

Reconciliation with [ADR 0001](adr/0001-lance-for-vector-and-multimodal-assets.md)
(Lance): embeddings stay vector columns on a TABULAR asset. There is no vector
kind, so the new kind set is the existing six plus GRAPH.

## datasets.yaml

`datasets.yaml` stays branch-free and environment-free. Namespaced URIs are
mapped to a URL by the active environment.

```yaml
publish:
  to: sunstone:projects/my_study
  public: true
  dialect:
    delimiter: ","
    header: true

outputs:
  - slug: result
    publish:
      as_name: result_v2
```

| Field | Meaning |
|---|---|
| `publish.to` | `sunstone:<ns>` names the target namespace. Each resource becomes `<ns>/<slug>` with a sanitized slug. |
| `publish.as_name` | Overrides the slug for a resource. Allowed only on a dataset's own `publish:` block. |
| `publish.public` | `true` makes the package public. Non-public packages need a Keycloak token to read. |
| `publish.dialect` | Package defaults for CSV and TSV output, using the delimited-text properties of [Frictionless Table Dialect](https://datapackage.org/standard/table-dialect/): `delimiter`, `lineTerminator`, `quoteChar`, `doubleQuote`, `escapeChar`, `nullSequence`, `skipInitialSpace`, `header`, `headerRows`, `headerJoin`, `commentRows`, `commentChar`. Unknown keys and wrong value types are rejected when the file loads. |

Push refuses the `ext/` zone, which is written only by `sunstone data import`.

Push also refuses a generated `datapackage.json` or resource that fails the Data Package v2 profiles. A multi-package push validates each package just before pushing it, so an invalid later package can leave earlier ones published (as with LFS and path-traversal refusals). Run `sunstone package build` (which warns) or `sunstone dataset validate --strict` before pushing several packages.

## CLI

```
sunstone package push [--env ENV] [--branch BRANCH] [--yes] [--force] [--replace]
```

- `--env` selects the environment through the existing `sunstone env` config.
  The default is `prod`. dev and prod are separate deployments. For namespace
  pushes the CLI sets `SUNSTONE_DATA_ENV` to the value before calling the
  plugin.
- `--branch` is used if given. Otherwise the default is `GITHUB_HEAD_REF`,
  then `GITHUB_REF_NAME`, then the current git branch. If none is available,
  push fails and asks for `--branch`. It never guesses `main`. The name is
  normalized by the data-platform rule: characters outside `[A-Za-z0-9_.-]`
  become `-`, runs of `-` collapse to one, a name not starting with a letter
  or `_` gets a `_` prefix, and the result is cut to 128 characters.
- `--yes` is required for manual pushes to a protected ref. The server also
  requires the `protected-write` role and an auth step-up, which the push
  plugin performs (`acr_values`, `max_age`).
- `--force` allows the operations the server protects by branch pattern:
  incompatible schema change, overwriting a named version, deleting removed
  datasets, `--replace` retraction and snapshot expiry. Protected refs
  reject it without the elevated role.

### Blob-store fallback

Destinations no plugin claims (`gs://`, `s3://`, `r2://`) use the blob-store
path (`push_group_to_blob_store` in `cli.py`). A blob-store push with
`--env prod` needs `--yes`. sunstone-py has no Keycloak client, so it does not
step up for blob-store pushes.

## Upload flow (client view)

1. The plugin builds a manifest (sha256, size, package metadata) and calls
   `POST /pushes`. The server returns presigned staging URLs only for hashes
   it lacks.
2. The plugin uploads those files, then calls `POST /pushes/{id}/commit`.
3. Commit is async. It returns 202 with the push ID. The plugin polls
   `GET /pushes/{id}` for per-dataset progress and the result.
4. A retry with the same push ID resumes. Re-push is idempotent.

## URL resolution

The data-platform plugin claims https URLs whose host is a configured env host
(`data.sunstone.institute`, `data.dev.sunstone.internal`), so they resolve
like `sunstone:` URLs. Other hosts go through `HttpURLHandler`.
