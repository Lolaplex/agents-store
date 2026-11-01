"""Typed relations with evidence claims (PORTING.md §3.3, Lean
More/Relation.lean; kernel-proposal.json layers.relations).

A pointer goes from source@version to target@version and carries no
target content. Each type declares an evidence claim; the claim is met
only by live events about the source that are pinned to both ends.
Equivalence is a family indexed by purpose (MP p.8 C.1): two refs are
equivalent for a purpose when representation edges connect them and every
edge preserves all invariants relevant to that purpose (Lean EquivFor,
equivB).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .compliance import (
    COMPLIANCE_PURPOSE,
    MAPS_TO_COMPLIANCE_PURPOSE_INVALID,
    MAPS_TO_TARGET_MISMATCH,
    PRESERVES_MISSING,
    RegulationRequirement,
    maps_to_compliance_purpose_invalid,
    maps_to_regulation_target,
)
from .events import Event, is_pinned, parse_ref
from .profile import Profile, load_profile
from .status import _events, _gate_accepted, _inactive


# RelType.reverse (kernel-proposal.json layers.relations.types)
REL_TYPE_REVERSE: dict[str, str] = {
    "refines": "is_refined_by",
    "references": "is_referenced_by",
    "derives_from": "derives_into",
    "derives_into": "derives_from",
    "implements": "implemented_by",
    "verifies": "verified_by",
    "decided_in": "affects",
    "causes_risk": "results_from",
    "depends_on": "is_prerequisite_of",
    "member_of": "contains",
    "maps_to": "mapped_from",
    "validated_by": "validates",
    "accepted_by": "accepts",
    "nav": "nav",
}

POINTER_UNPINNED = "pointer_unpinned"
POINTER_SUSPECT = "pointer_suspect"
CLAIM_UNMET = "claim_unmet"

# RelType.claim. Types not listed claim nothing.
CLAIM = {
    "derives_from": "derivation",
    "derives_into": "derivation",
    "implements": "test",
    "verifies": "test",
    "validated_by": "validation",
    "accepted_by": "acceptance",
}
# RelType.needsPreserves
NEEDS_PRESERVES = {"derives_from", "derives_into", "implements", "verifies", "maps_to"}


@dataclass(frozen=True)
class Pointer:
    id: str
    source: str           # "SUBJECT@VERSION"
    target: str           # "SUBJECT@VERSION"; no version = floating
    type: str             # RelType.key, e.g. "implements"
    preserves: tuple[tuple[str, str], ...] = ()   # (purpose, invariant)

    @property
    def floating(self) -> bool:
        return not is_pinned(self.target)


def outgoing(pointers: Iterable[Pointer], ref: str, rel_type: str) -> list[Pointer]:
    return [p for p in pointers if p.source == ref and p.type == rel_type]


def pinned_to_both(ptr: Pointer, e: Event) -> bool:
    return ptr.source in e.pinned_against and ptr.target in e.pinned_against


def _is_evidence(profile: Profile, claim: str, e: Event) -> bool:
    b = e.body
    if e.type == "verification":
        ok = b.get("result") == "pass" and _gate_accepted(e)
        if claim == "derivation":
            return ok
        if claim == "test":
            return ok and b.get("stage", "test") == "test"
        if claim == "validation":
            methods = {m.casefold() for m in profile.setting("validator_methods")}
            return ok and str(b.get("method", "")).casefold() in methods
        return False
    if e.type == "decision" and claim == "acceptance":
        return (b.get("status") == "decided" and b.get("kind") == "acceptance"
                and b.get("outcome") == "accepted")
    return False


def evidence(source, ptr: Pointer, profile: Profile) -> list[Event]:
    events = _events(source)
    inactive = _inactive(events)
    claim = CLAIM.get(ptr.type)
    subject, _ = parse_ref(ptr.source)
    return [e for e in events
            if subject in e.subjects and e.id not in inactive and pinned_to_both(ptr, e)
            and claim is not None and _is_evidence(profile, claim, e)]


def claim_met(source, ptr: Pointer, profile: Profile) -> bool:
    return ptr.type not in CLAIM or bool(evidence(source, ptr, profile))


def suspect(source, ptr: Pointer) -> bool:
    """A live supersession or overrule is pinned to the target version."""
    events = _events(source)
    inactive = _inactive(events)
    return any(e.type in ("supersession", "overrule") and e.id not in inactive
               and ptr.target in e.pinned_against for e in events)


def _is_level_property(prop: str) -> bool:
    return prop in load_profile().levels


def _is_event_type_property(prop: str) -> bool:
    return prop in {"decision", "verification", "inclusion", "supersession", "overrule", "move"}


def _maps_to_preserved(ptr: Pointer) -> bool:
    if ptr.type != "maps_to":
        return False
    lvls = [prop for purp, prop in ptr.preserves if purp == COMPLIANCE_PURPOSE and _is_level_property(prop)]
    ets = [prop for purp, prop in ptr.preserves if purp == COMPLIANCE_PURPOSE and _is_event_type_property(prop)]
    return len(lvls) == 1 and len(ets) == 1


def _maps_to_target_mismatch(reqs: list[RegulationRequirement], ptr: Pointer) -> bool:
    if ptr.type != "maps_to":
        return False
    req = next((r for r in reqs if r.ref == ptr.source), None)
    if req is None:
        return True
    return ptr.floating or ptr.target != maps_to_regulation_target(req)


def relation_violations(
    source,
    ptr: Pointer,
    profile: Profile,
    *,
    regulation_requirements: list[RegulationRequirement] | None = None,
) -> list[str]:
    reqs = regulation_requirements or []
    out = []
    if ptr.floating and ptr.type != "nav":
        out.append(POINTER_UNPINNED)
    if suspect(source, ptr):
        out.append(POINTER_SUSPECT)
    if ptr.type == "maps_to":
        if _maps_to_target_mismatch(reqs, ptr):
            out.append(MAPS_TO_TARGET_MISMATCH)
        if maps_to_compliance_purpose_invalid(ptr):
            out.append(MAPS_TO_COMPLIANCE_PURPOSE_INVALID)
        if not maps_to_compliance_purpose_invalid(ptr) and not _maps_to_preserved(ptr):
            out.append(PRESERVES_MISSING)
    elif ptr.type in NEEDS_PRESERVES and not ptr.preserves:
        out.append(PRESERVES_MISSING)
    if not claim_met(source, ptr, profile):
        out.append(CLAIM_UNMET)
    return out


def relation_check(
    source,
    pointers: Iterable[Pointer],
    profile: Profile,
    *,
    regulation_requirements: list[RegulationRequirement] | None = None,
) -> list[tuple[str, str]]:
    return [
        (p.id, v)
        for p in pointers
        for v in relation_violations(
            source, p, profile, regulation_requirements=regulation_requirements
        )
    ]


# RelType.isRepresentation: the only edges that can make two refs equivalent.
REPRESENTATION = {"derives_from", "derives_into"}
PURPOSES = ("verification", "acceptance", "operations")


def known_purpose(profile: Profile, purpose: str) -> bool:
    """Sourced, or registered in the profile (Lean Purpose.knownIn, §12d)."""
    return purpose in PURPOSES or purpose in profile.settings.get("purposes", ())


def valid_for(profile: Profile, purpose: str, ptr: Pointer) -> bool:
    """A known purpose and a pinned representation edge that preserves every
    invariant relevant to `purpose` (Lean validFor)."""
    if not known_purpose(profile, purpose):
        return False
    relevant = profile.setting("relevant")[purpose]
    return (ptr.type in REPRESENTATION and not ptr.floating
            and all((purpose, q) in ptr.preserves for q in relevant))


def equivalent(pointers: Iterable[Pointer], purpose: str, a: str, b: str,
               profile: Profile) -> bool:
    """a ~ b for `purpose`: the equivalence closure of the valid edges, in both
    directions (Lean equivB; a full search, so also complete)."""
    edges = [p for p in pointers if valid_for(profile, purpose, p)]
    seen, todo = {a}, [a]
    while todo:
        x = todo.pop()
        for p in edges:
            for y in ((p.target,) if p.source == x else ()) + ((p.source,) if p.target == x else ()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
    return b in seen
