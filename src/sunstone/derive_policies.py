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


def _payload_shape(asset: Asset) -> tuple[int, ...] | None:
    p = asset.payload
    return tuple(p.shape) if hasattr(p, "shape") else None


def _payload_dtype(asset: Asset) -> str | None:
    p = asset.payload
    return str(p.dtype) if hasattr(p, "dtype") else None


def raster_invalidate_stale_profile(parent: Asset, child: Asset) -> Asset:
    """Drop `profile["count"]`, `profile["dtype"]`, `profile["nodata"]` when the
    child's payload shape or dtype differs from the parent's.

    Geographic fields (`crs`, `transform`) are preserved by default since most
    derivations preserve spatial reference. Handlers that change CRS must
    update extras explicitly via `derive(extras_updates=...)`.
    """
    profile = child.extras.get("profile")
    if not isinstance(profile, dict):
        return child

    shape_changed = _payload_shape(parent) != _payload_shape(child)
    dtype_changed = _payload_dtype(parent) != _payload_dtype(child)

    if shape_changed or dtype_changed:
        for stale_key in ("count", "dtype", "nodata"):
            profile.pop(stale_key, None)

    return child


KIND_DERIVE_POLICIES[AssetKind.RASTER] = raster_invalidate_stale_profile
