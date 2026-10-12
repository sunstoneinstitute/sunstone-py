# Pushing packages to `sunstone:` namespaces

Status: designed, not yet built. This page covers the sunstone-py side.
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

- `PushPackage`: the resolved resources (path, `AssetKind`, sha256, size,
  metadata) and package-level metadata.
- `PushOptions`: `env`, `branch`, `yes`, `force`, `replace`.
- `PushResult`: push ID, per-dataset status and the resulting https IRIs.

`sunstone package push` asks the registry for a handler that claims the
destination. If none does, it falls back to `packaging.push_group`, which stays
the blob-store path (GCS, S3, R2). Plugins take priority over built-ins.

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
backed by rdflib, installed through an optional extra (`sunstone-py[rdf]`).
The base install gains no rdflib dependency.

Reconciliation with [ADR 0001](adr/0001-lance-for-vector-and-multimodal-assets.md)
(Lance): embeddings stay vector columns on a TABULAR asset. There is no vector
kind, so the new kind set is the existing six plus GRAPH.

## datasets.yaml

`datasets.yaml` stays branch-free and environment-free. Namespaced URIs are
mapped to a URL by the active environment.

```yaml
publish:
  to: sunstone:projects/my-study
  public: true
  dialect:
    delimiter: ","
    quoting: minimal
```

| Field | Meaning |
|---|---|
| `publish.to` | `sunstone:<ns>` names the target namespace. Each resource becomes `<ns>/<slug>` with a sanitized slug. |
| `publish.as_name` | Overrides the slug for a resource. |
| `publish.public` | `true` makes the package public. Non-public packages need a Keycloak token to read. |
| `publish.dialect` | Package defaults for CSV and TSV output, using Frictionless Table Dialect properties plus a Sunstone `quoting` property. |

Push refuses the `ext/` zone, which is written only by `sunstone data import`.

## CLI

```
sunstone package push [--env ENV] [--branch BRANCH] [--yes] [--force] [--replace]
```

- `--env` selects the environment through the existing `sunstone env` config.
  The default is `prod`. dev and prod are separate deployments.
- `--branch` defaults to the current git branch, normalized by the
  data-platform rule: characters outside `[A-Za-z0-9_.-]` become `-`.
  In CI the default comes from `GITHUB_HEAD_REF`, then `GITHUB_REF_NAME`. If
  neither is set, push fails and asks for `--branch`. It never guesses `main`.
- `--yes` is required for manual pushes to a protected ref. The server also
  requires the `protected-write` role and an auth step-up, which the CLI
  triggers through its PKCE flow (`acr_values`, `max_age`).
- `--force` allows the operations the server protects by branch pattern:
  incompatible schema change, overwriting a named version, deleting removed
  datasets, `--replace` retraction and snapshot expiry. Protected refs
  reject it without the elevated role.

### Blob-store fallback

The `push_group` path (`push_group_to_gcs` in `cli.py`) can no longer assume
GCS. Rename it and its messages to blob-store terms. The default `--env`
changes to `prod`, so a GCS push with `--env prod` needs `--yes` and a
step-up with the `protected-write` role. The CLI enforces this itself because
GCS cannot. The default change goes under Changed in CHANGELOG.md when built.

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
