import pytest

from sunstone.rdf import IRI, LangString, TypedLiteral


def test_iri_is_str_subclass():
    iri = IRI("sosa:NDVI")
    assert isinstance(iri, str)
    assert iri == "sosa:NDVI"


def test_iri_repr_distinguishes_from_str():
    iri = IRI("sosa:NDVI")
    assert "IRI" in repr(iri)
    assert "sosa:NDVI" in repr(iri)


def test_iri_distinguishable_via_isinstance():
    assert isinstance(IRI("a:b"), IRI)
    assert not isinstance("a:b", IRI)


def test_lang_string_is_frozen_dataclass():
    ls = LangString("hello", "en")
    assert ls.value == "hello"
    assert ls.lang == "en"
    with pytest.raises((AttributeError, Exception)):
        ls.value = "bye"


def test_lang_string_equality_and_hash():
    a = LangString("hello", "en")
    b = LangString("hello", "en")
    c = LangString("hello", "fr")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


def test_typed_literal_is_frozen_dataclass():
    tl = TypedLiteral("3.14", "xsd:double")
    assert tl.value == "3.14"
    assert tl.datatype == "xsd:double"
    with pytest.raises((AttributeError, Exception)):
        tl.value = "0"
