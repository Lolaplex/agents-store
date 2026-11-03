"""MORe kernel violation metadata projected by the in-tree domain provider.

These ids come from ``relation_check`` / world-model replay (not from
``MoreDomain.append``). Kernel ids stay out of the open registrar
(``agents_store.violation_ids``).
"""
from __future__ import annotations

from agents_store.contracts import DomainViolationId
from agents_store.registry import MORE_FRAMEWORK_PIN, MORE_FRAMEWORK_REPLAY_REPO

_PIN = MORE_FRAMEWORK_PIN


def _prov(repo_path: str, fragment: str) -> str:
    return f"{MORE_FRAMEWORK_REPLAY_REPO}:{repo_path}@{_PIN}{fragment}"


_PROV_REFINES = _prov("lean-model/more-lean-model.md", "#section-16")
_PROV_RELATIONS = _prov("lean-model/kernel-proposal.json", "#layers.relations")
_PROV_COMPLIANCE_MATRIX = _prov(
    "lean-model/kernel-proposal.json", "#generated_projections.compliance_matrix"
)

# Ids ``relation_violations`` in ``agents_store.more.relations`` may emit.
RELATION_VIOLATION_IDS: frozenset[str] = frozenset({
    "pointer_unpinned",
    "pointer_suspect",
    "maps_to_target_mismatch",
    "maps_to_compliance_purpose_invalid",
    "preserves_missing",
    "refines_meaning_missing",
    "refines_pair_not_in_profile",
    "refines_level_invalid",
    "claim_unmet",
})

_REGISTRY: tuple[DomainViolationId, ...] = (
    DomainViolationId(
        id="pointer_unpinned",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_RELATIONS,
        fires_when="non-nav pointer without target_version",
    ),
    DomainViolationId(
        id="pointer_suspect",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_RELATIONS,
        fires_when="target superseded since pointer was confirmed",
    ),
    DomainViolationId(
        id="maps_to_target_mismatch",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_COMPLIANCE_MATRIX,
        fires_when=(
            "maps_to pointer target is floating or does not match the pinned "
            "regulation corpus text for the source regulation_requirement"
        ),
    ),
    DomainViolationId(
        id="maps_to_compliance_purpose_invalid",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_COMPLIANCE_MATRIX,
        fires_when=(
            "maps_to preserves[] uses compliance purpose on level or event_type "
            "properties incorrectly (wrong purpose or mixed invalid entries)"
        ),
    ),
    DomainViolationId(
        id="preserves_missing",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_RELATIONS,
        fires_when=(
            "relation type requires preserves[] but none are present, or maps_to "
            "compliance purpose is ok but level/event_type preservation is ambiguous"
        ),
    ),
    DomainViolationId(
        id="refines_meaning_missing",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_REFINES,
        fires_when=(
            "pointer.type is refines and preserves[] has no exactly-one purpose "
            "refines property detail_existing or toward_target"
        ),
    ),
    DomainViolationId(
        id="refines_pair_not_in_profile",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_REFINES,
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
        provenance_ref=_PROV_REFINES,
        fires_when=(
            "meaning is detail_existing and both source and target resolve to IA "
            "hierarchy levels and target level rank is finer than source "
            "(UI and API share rank; DEC/spec/task/mixed pairs do not fire)"
        ),
    ),
    DomainViolationId(
        id="claim_unmet",
        domain="more",
        severity="refusal",
        provenance_ref=_PROV_RELATIONS,
        fires_when=(
            "pointer relation type declares an evidence claim and no live event "
            "meets that claim pinned to both pointer ends"
        ),
    ),
)


def more_violation_registry() -> tuple[DomainViolationId, ...]:
    return _REGISTRY
