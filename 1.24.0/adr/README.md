# Architecture Decision Records

ADRs for decisions about sunstone-py's Asset model and storage layer that
constrain how downstream packages (data-platform, research-stack) persist and
query assets — new asset kinds, storage handlers, the metadata/lineage contract,
column-type conventions, and format defaults.

**Filename:** `NNNN-short-title.md` (zero-padded, monotonically increasing).

**Suggested structure:** Status · Context · Decision · Alternatives · Consequences.
Keep them as short as the decision allows.

Related ADRs in sibling repos:

- **data-platform** `docs/adr/` — catalog, Iceberg/Nessie, graph-as-canonical
  metadata store, the non-tabular sidecar/pointer design.
- **research-stack** `docs/adr/` — ontology profile, concept canonicalization,
  and the concept-embeddings catalog contract (ADR 0003).
