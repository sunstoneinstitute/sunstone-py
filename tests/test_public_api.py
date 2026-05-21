def test_public_api_exports_asset_types():
    import sunstone

    assert hasattr(sunstone, "Asset")
    assert hasattr(sunstone, "AssetKind")
    assert hasattr(sunstone, "IRI")
    assert hasattr(sunstone, "LangString")
    assert hasattr(sunstone, "TypedLiteral")
    assert hasattr(sunstone, "IncompatibleAssetKindError")
    assert hasattr(sunstone, "ComponentSchema")
