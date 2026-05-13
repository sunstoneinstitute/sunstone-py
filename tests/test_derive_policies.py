import pandas as pd

from sunstone.asset import Asset, AssetKind
from sunstone.derive_policies import (
    apply_kind_derive_policy,
    no_op_policy,
)
from sunstone.lineage import Metadata


def test_registry_has_no_op_default_for_all_kinds():
    for kind in AssetKind:
        # apply must succeed for every kind even without a registered policy.
        parent = Asset(payload=None, kind=kind, metadata=Metadata())
        child = Asset(payload=None, kind=kind, metadata=Metadata())
        result = apply_kind_derive_policy(parent, child)
        assert result is child


def test_no_op_policy_returns_child_unchanged():
    parent = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata())
    child = Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=AssetKind.TABULAR,
        metadata=Metadata(),
        extras={"k": "v"},
    )
    out = no_op_policy(parent, child)
    assert out is child
    assert out.extras == {"k": "v"}
