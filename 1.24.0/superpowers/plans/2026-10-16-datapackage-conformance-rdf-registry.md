# Datapackage Conformance (rdf-registry, C11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define `dcat-si:methodology` in `rdf/data.ttl` so `datasets.yaml` can use it as the top-level methodology key and sunstone-py's vocabulary sync (plan `2026-10-16-datapackage-conformance-sunstone-py.md`, Task 1) finds it.

**Architecture:** One object property added to the `https://sunstone.institute/rdf/data#` ontology, validated by the repo's existing riot/SHACL gate and a new rdflib unit test. No build or template changes.

**Tech Stack:** Turtle, rdflib (already a dependency), pytest, Apache Jena `riot` (`brew bundle` from the repo `Brewfile`).

**Spec:** `docs/superpowers/specs/2026-10-15-datapackage-conformance-design.md` in sunstone-py (section "C11. rdf-registry"; the key-migration row `si:methodology` → `dcat-si:methodology`).

## Spec conflicts

None. The spec's C11 axiom table fixes every axiom. It differs from `vocab:methodology` in `rdf/vocab.ttl` (lines 203-209) on purpose: domain `dcat:Resource` instead of `dcat:Dataset`, plus `rdfs:subPropertyOf foaf:page`.

## Global Constraints

- Repo: `~/git/sunstone/rdf-registry`. Start from a fresh `origin/main` (`git fetch origin && git switch -c feat/dcat-si-methodology origin/main`).
- This change lands before sunstone-py Task 1 runs `scripts/sync_vocab.py` (spec Scope order).
- Turtle must pass `uv run validate` (riot syntax + SHACL) and `uv run validate-ontology rdf/data.ttl` with no new errors. Warnings about pre-existing terms are not in scope.
- No N-Triples, 2-space JSON-LD (repo `AGENTS.md`); nothing here touches the build.
- Commit message: conventional prefix, no Co-authored-by lines.

## File map

| File | Responsibility |
|---|---|
| `rdf/data.ttl` | Add `foaf` prefix, bump `owl:versionInfo`, add `:methodology` |
| `tests/test_data_vocab.py` | New: asserts the property, its label, comment, domain and range |

---

### Task 1: Add `dcat-si:methodology` to `rdf/data.ttl`

**Files:**
- Modify: `rdf/data.ttl` (prefix block lines 1-9; ontology header line 23 `owl:versionInfo "0.2"`; object properties section after `:hasSnapshot`, line ~70)
- Create: `tests/test_data_vocab.py`

**Interfaces:**
- Produces: IRI `https://sunstone.institute/rdf/data#methodology`, `a owl:ObjectProperty`, with `rdfs:label "methodology"@en`, an `rdfs:comment`, `rdfs:isDefinedBy`, domain `dcat:Resource`, range `foaf:Document` and `rdfs:subPropertyOf foaf:page`. sunstone-py's sync reads `rdfs:label` for the label and `rdfs:comment` for the definition.

- [ ] **Step 1: Branch from origin/main**

```bash
cd ~/git/sunstone/rdf-registry
git fetch origin
git switch -c feat/dcat-si-methodology origin/main
uv sync
```

- [ ] **Step 2: Write the failing test `tests/test_data_vocab.py`**

```python
"""dcat-si:methodology is defined in rdf/data.ttl (sunstone-py reads it from here)."""

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

DCAT_SI = "https://sunstone.institute/rdf/data#"
METHODOLOGY = URIRef(DCAT_SI + "methodology")
DCAT_RESOURCE = URIRef("http://www.w3.org/ns/dcat#Resource")
FOAF_DOCUMENT = URIRef("http://xmlns.com/foaf/0.1/Document")
FOAF_PAGE = URIRef("http://xmlns.com/foaf/0.1/page")
DATA_ONTOLOGY = URIRef("https://sunstone.institute/rdf/data")


def _graph(repo_root) -> Graph:
    g = Graph()
    g.parse(repo_root / "rdf" / "data.ttl", format="turtle")
    return g


def test_methodology_is_an_object_property(repo_root):
    g = _graph(repo_root)
    assert (METHODOLOGY, RDF.type, OWL.ObjectProperty) in g


def test_methodology_has_english_label_and_comment(repo_root):
    g = _graph(repo_root)
    assert g.value(METHODOLOGY, RDFS.label) == Literal("methodology", lang="en")
    comment = g.value(METHODOLOGY, RDFS.comment)
    assert isinstance(comment, Literal) and comment.language == "en" and len(str(comment)) > 20


def test_methodology_domain_and_range(repo_root):
    g = _graph(repo_root)
    assert g.value(METHODOLOGY, RDFS.domain) == DCAT_RESOURCE
    assert g.value(METHODOLOGY, RDFS.range) == FOAF_DOCUMENT


def test_methodology_is_a_foaf_page(repo_root):
    g = _graph(repo_root)
    assert (METHODOLOGY, RDFS.subPropertyOf, FOAF_PAGE) in g


def test_methodology_is_defined_by_data_ontology(repo_root):
    g = _graph(repo_root)
    assert g.value(METHODOLOGY, RDFS.isDefinedBy) == DATA_ONTOLOGY


def test_methodology_comment_distinguishes_neighbours(repo_root):
    comment = str(_graph(repo_root).value(METHODOLOGY, RDFS.comment))
    assert "prov:hadPlan" in comment and "schema:measurementTechnique" in comment


def test_methodology_not_in_vocab_namespace_of_data_ttl(repo_root):
    """data.ttl must not redeclare vocab:methodology; only the dcat-si term lives here."""
    g = _graph(repo_root)
    assert (URIRef("https://sunstone.institute/rdf/vocab#methodology"), None, None) not in g
```

(`repo_root` is the session fixture in `tests/conftest.py`.)

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_data_vocab.py -q`
Expected: 6 failures (every test except `test_methodology_not_in_vocab_namespace_of_data_ttl`, which passes).

- [ ] **Step 4: Edit `rdf/data.ttl`**

Add the `foaf` prefix to the prefix block (alphabetical, after `dct:`):

```turtle
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
```

Change the ontology header line `owl:versionInfo "0.2" ;` to `owl:versionInfo "0.3" ;`.

Append to the "Object properties" section, after the `:hasSnapshot` block:

```turtle
:methodology a owl:ObjectProperty ;
    rdfs:label "methodology"@en ;
    rdfs:comment "The document describing the method actually applied to produce a dataset or data package: sources, acquisition, processing and limitations. Unlike prov:hadPlan, it is documentation of what was done, not a plan of intent attached to an activity. Unlike schema:measurementTechnique, it covers the whole resource, not the measurement of one variable."@en ;
    rdfs:isDefinedBy <https://sunstone.institute/rdf/data> ;
    rdfs:subPropertyOf foaf:page ;
    rdfs:seeAlso <https://sunstone.institute/rdf/vocab#methodology> ;
    rdfs:domain dcat:Resource ;
    rdfs:range foaf:Document .
```

- [ ] **Step 5: Run the test and the validators**

Run: `uv run pytest tests/test_data_vocab.py -q`
Expected: 7 passed.

Run: `uv run validate`
Expected: `✓ ALL VALIDATIONS PASSED`. If `riot` is missing: `brew bundle` (installs `jena`), then rerun.

Run: `uv run validate-ontology rdf/data.ttl`
Expected: `Object properties: 4` (was 3), no `❌` lines. The "Namespaces used but not declared" check must not list `http://xmlns.com/foaf/0.1/`.

Run: `uv run pytest -q -m "not integration"` then `uv run pytest -q`
Expected: all pass (the integration suite loads every `rdf/*.ttl` into the store).

- [ ] **Step 6: Build once and spot-check the rendered ontology**

Run: `uv run build && grep -c "data#methodology" dist/rdf/data.ttl dist/rdf/data.jsonld`
Expected: a count of at least 1 for each file. `dist/` is build output; do not commit it unless the repo already tracks it (check `git status`).

- [ ] **Step 7: Commit and open the PR**

```bash
git add rdf/data.ttl tests/test_data_vocab.py
git commit -m "feat(data): define dcat-si:methodology"
git push -u origin feat/dcat-si-methodology
gh pr create --title "Define dcat-si:methodology" --body "Adds dcat-si:methodology (object property, domain dcat:Resource, range foaf:Document, subproperty of foaf:page) to rdf/data.ttl. sunstone-py's vocabulary sync reads it from here (datapackage conformance, C11)."
```

Report the PR URL. sunstone-py Task 1 needs this merged (or at least fetched into `~/git/sunstone/rdf-registry` at `origin/main`) before it runs the sync.

---

## Self-review notes

- Spec coverage: C11 fully in Task 1 (object property, label, comment); alias row `si:methodology` → `dcat-si:methodology` consumes this IRI.
- Placeholder scan: none.
- Type consistency: the test's IRIs match the Turtle (`https://sunstone.institute/rdf/data#methodology`, `dcat:Resource`, `foaf:Document`, `foaf:page`, ontology IRI `https://sunstone.institute/rdf/data`).
