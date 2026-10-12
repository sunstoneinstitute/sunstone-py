# GCS Local Testing with fake-gcs-server

This document describes how to emulate Google Cloud Storage (GCS) locally using `fsouza/fake-gcs-server` for development and testing.

## Why fake-gcs-server

- BSD-2-Clause licensed (permissive)
- Emulates the GCS JSON/XML APIs, allowing use of official GCS client libraries
- Supports bucket provisioning via filesystem mounts
- Works well in docker-compose multi-container setups

**Note**: This is an emulator with known limitations. It's suitable for integration tests, not a perfect GCS replica. Lifecycle policies and object versioning are not emulated—these are infra/ops concerns handled by OpenTofu or GKE Config Connector in staging/prod.

## Docker Compose Setup

```yaml
services:
  gcs:
    image: fsouza/fake-gcs-server:latest
    command: ["-scheme", "http", "-port", "4443", "-public-host", "gcs:4443"]
    ports:
      - "4443:4443"
    volumes:
      - ./local/gcs-data:/data

  # Your app service(s)
  app:
    # ...
    environment:
      GCS_API_ENDPOINT: "http://gcs:4443"
    depends_on:
      - gcs
```

### Key flags

- `-scheme http` — Use HTTP (no TLS for local dev)
- `-port 4443` — Port to listen on
- `-public-host gcs:4443` — The hostname clients use to reach the server (important for signed URLs if you ever need them; otherwise optional)

## Bucket Provisioning

Apps should **not** create buckets—they are provisioned by infrastructure (OpenTofu/Config Connector in staging/prod).

For local dev, create buckets by adding empty directories under the `/data` mount:

```
local/gcs-data/
├── my-bucket/
├── another-bucket/
└── uploads-bucket/
```

Each top-level directory becomes a bucket. You can seed objects by placing files inside.

### Alternative: Init container

If you need dynamic bucket creation, use a one-shot init container:

```yaml
services:
  gcs-init:
    image: google/cloud-sdk:slim
    depends_on:
      - gcs
    environment:
      STORAGE_EMULATOR_HOST: "http://gcs:4443"
    entrypoint: ["/bin/bash", "-c"]
    command:
      - |
        # Wait for fake-gcs-server
        until curl -s http://gcs:4443/storage/v1/b; do sleep 1; done
        # Create buckets
        gsutil mb gs://my-bucket || true
        gsutil mb gs://another-bucket || true
```

## Client Configuration

### Python (google-cloud-storage)

```python
import os
from google.cloud import storage

def get_storage_client():
    endpoint = os.environ.get("GCS_API_ENDPOINT")
    if endpoint:
        # Local dev: use emulator, no auth
        return storage.Client(
            project="local",
            client_options={"api_endpoint": endpoint},
            use_auth_w_custom_endpoint=False,
        )
    else:
        # Staging/prod: use default credentials
        return storage.Client()
```

### Node/TypeScript (@google-cloud/storage)

```typescript
import { Storage } from "@google-cloud/storage";

function getStorageClient(): Storage {
  const endpoint = process.env.GCS_API_ENDPOINT;
  if (endpoint) {
    // Local dev: use emulator, no auth
    return new Storage({
      apiEndpoint: endpoint,
      useAuthWithCustomEndpoint: false,
      projectId: "local",
    });
  } else {
    // Staging/prod: use default credentials
    return new Storage();
  }
}
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GCS_API_ENDPOINT` | fake-gcs-server URL (set only for local dev) | `http://gcs:4443` |

When `GCS_API_ENDPOINT` is unset, clients use real GCS with Application Default Credentials.

## Limitations

- **No lifecycle policies**: Objects won't auto-expire. For local cleanup, either reset volumes or add a janitor script.
- **No object versioning**: If your app relies on GCS versioning, mock it or skip those tests locally.
- **Resumable uploads**: Supported but may have edge-case differences from real GCS.
- **Error semantics**: Error responses may differ slightly from real GCS.

For features you can't emulate locally, validate via:
- Infra review/CI (Terraform plan, Config Connector manifests)
- Integration tests against a real GCS bucket in a dev/staging project

## References

- [fake-gcs-server GitHub](https://github.com/fsouza/fake-gcs-server)
- [Python GCS Client Docs](https://cloud.google.com/python/docs/reference/storage/latest)
- [Node.js GCS Client Docs](https://cloud.google.com/nodejs/docs/reference/storage/latest)
