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

from .events import Event, is_pinned, parse_ref
from .profile import Profile
from .status import _events, _gate_accepted, _inactive

POINTER_UNPINNED = "pointer_unpinned"
POINTER_SUSPECT = "pointer_suspect"
PRESERVES_MISSING = "preserves_missing"
CLAIM_UNMET = "claim_unmet"

# RelType.claim. Types not listed claim nothing.
CLAIM = {
    "derives_from": "derivation",
    "represented_by": "derivation",
    "implements": "test",
    "verifies": "test",
    "validated_by": "validation",
    "accepted_by": "acceptance",
}
# RelType.needsPreserves
NEEDS_PRESERVES = {"derives_from", "represented_by", "implements", "verifies"}


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


def relation_violations(source, ptr: Pointer, profile: Profile) -> list[str]:
    out = []
    if ptr.floating and ptr.type != "nav":
        out.append(POINTER_UNPINNED)
    if suspect(source, ptr):
        out.append(POINTER_SUSPECT)
    if ptr.type in NEEDS_PRESERVES and not ptr.preserves:
        out.append(PRESERVES_MISSING)
    if not claim_met(source, ptr, profile):
        out.append(CLAIM_UNMET)
    return out


def relation_check(source, pointers: Iterable[Pointer], profile: Profile) -> list[tuple[str, str]]:
    return [(p.id, v) for p in pointers for v in relation_violations(source, p, profile)]


# RelType.isRepresentation: the only edges that can make two refs equivalent.
REPRESENTATION = {"derives_from", "represented_by"}
PURPOSES = ("verification", "acceptance", "operations")


def valid_for(profile: Profile, purpose: str, ptr: Pointer) -> bool:
    """A pinned representation edge that preserves every invariant relevant
    to `purpose` (Lean validFor)."""
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
