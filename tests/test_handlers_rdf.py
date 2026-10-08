import io

import pytest


def test_rdf_handler_resolution():
    from sunstone.asset import AssetKind
    from sunstone.handlers_rdf import RdfFormatHandler

    h = RdfFormatHandler()
    assert h.can_read("g.ttl", None)
    assert h.can_read("g.nt", None)
    assert h.can_read("g.jsonld", None)
    assert h.can_read("g.txt", "turtle")
    assert h.can_read("g.json", "json-ld")
    assert not h.can_read("g.json", None)
    assert not h.can_read("g.csv", None)
    assert h.supported_kinds() == (AssetKind.GRAPH,)
    assert h.extensions() == (".ttl", ".nt", ".jsonld")


_TTL = b"""@prefix ex: <http://example.org/> .
ex:a ex:knows ex:b .
"""


def test_read_turtle_returns_graph_asset():
    from sunstone.asset import AssetKind
    from sunstone.handlers_rdf import RdfFormatHandler

    asset = RdfFormatHandler().read(io.BytesIO(_TTL), path="g.ttl")
    assert asset.kind is AssetKind.GRAPH
    assert len(asset.as_graph()) == 1
    assert asset.extras["media_type"] == "text/turtle"


@pytest.mark.parametrize("ext", ["ttl", "nt", "jsonld"])
def test_write_round_trips(ext):
    import rdflib.compare

    from sunstone.handlers_rdf import RdfFormatHandler

    h = RdfFormatHandler()
    asset = h.read(io.BytesIO(_TTL), path="g.ttl")
    out = io.BytesIO()
    h.write(asset, out, path=f"g.{ext}")
    again = h.read(io.BytesIO(out.getvalue()), path=f"g.{ext}")
    assert rdflib.compare.isomorphic(asset.as_graph(), again.as_graph())


def test_registry_resolves_ttl_to_rdf_handler(tmp_path):
    from sunstone.handlers_rdf import RdfFormatHandler
    from sunstone.plugins import PluginRegistry

    registry = PluginRegistry(tmp_path)
    registry._discover()
    assert isinstance(registry.find_format_reader("g.ttl", None), RdfFormatHandler)
