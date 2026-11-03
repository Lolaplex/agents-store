"""MORe kernel violation metadata enforced by the in-tree domain provider.

Kernel ids are reserved in the open registrar (``agents_store.violation_ids``).
The MORe provider keeps its own registry for product-management kernel ids it
projects and may surface on ``WriteRefusal`` / relation checks.
"""
from __future__ import annotations

from agents_store.contracts import DomainViolationId
from agents_store.registry import MORE_FRAMEWORK_PIN, MORE_FRAMEWORK_REPLAY_REPO

_PROVENANCE = f"{MORE_FRAMEWORK_REPLAY_REPO}@{MORE_FRAMEWORK_PIN}"

_REFINES_REGISTRY: tuple[DomainViolationId, ...] = (
    DomainViolationId(
        id="refines_meaning_missing",
        domain="more",
        severity="refusal",
        provenance_ref=_PROVENANCE,
        fires_when=(
            "pointer.type is refines and preserves[] has no exactly-one purpose "
            "refines property detail_existing or toward_target"
        ),
    ),
    DomainViolationId(
        id="refines_pair_not_in_profile",
        domain="more",
        severity="refusal",
        provenance_ref=_PROVENANCE,
        fires_when=(
            "resolved source/target kinds fail the profile refines pair rule "
            "(default: unknown kind, or same kind when refines_allow_same_kind is "
            "false; whitelist override when refines_allowed_pairs is set)"
        ),
    ),
    DomainViolationId(
        id="refines_level_invalid",
        domain="more",
        severity="refusal",
        provenance_ref=_PROVENANCE,
        fires_when=(
            "meaning is detail_existing and both source and target resolve to IA "
            "hierarchy levels and target level rank is finer than source "
            "(UI and API share rank; DEC/spec/task/mixed pairs do not fire)"
        ),
    ),
)


def more_violation_registry() -> tuple[DomainViolationId, ...]:
    return _REFINES_REGISTRY
