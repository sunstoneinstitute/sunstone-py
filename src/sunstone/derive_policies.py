"""Per-kind policies that run during `Asset.derive()` to invalidate stale
kind-specific extras when the payload changes shape, dtype, or other relevant
invariants."""

from __future__ import annotations

from typing import Protocol

from .asset import Asset, AssetKind


class KindDerivePolicy(Protocol):
    """Hook called from `Asset.derive()` after extras have been deep-copied
    and `extras_updates` applied. Receives the parent asset and the
    already-constructed child; returns the (possibly mutated) child."""

    def __call__(self, parent: Asset, child: Asset) -> Asset: ...


def no_op_policy(parent: Asset, child: Asset) -> Asset:
    """Default policy: leave the child as-is."""
    return child


KIND_DERIVE_POLICIES: dict[AssetKind, KindDerivePolicy] = {}


def apply_kind_derive_policy(parent: Asset, child: Asset) -> Asset:
    """Apply the registered policy for `child.kind`, falling back to no-op."""
    policy = KIND_DERIVE_POLICIES.get(child.kind, no_op_policy)
    return policy(parent, child)
