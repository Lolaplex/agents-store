"""Compliance matrix as a projection (PORTING.md §3.4, Lean
More/Compliance.lean; kernel-proposal.json
generated_projections.compliance_matrix).

Inputs: `regulation_requirement` artifacts and `maps_to` pointers (level and event
type on `preserves[]` with purpose compliance), subjects with hierarchy level, and
the event log. Duties and mappings are derived, never parallel side lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .checks import Violation
from .profile import load_profile
from .status import _events, _gate_accepted, _inactive

DUTY_UNMAPPED = "duty_unmapped"
MATRIX_HAND_EDITED = "matrix_hand_edited"
PRESERVES_MISSING = "preserves_missing"
MAPS_TO_TARGET_MISMATCH = "maps_to_target_mismatch"
MAPS_TO_COMPLIANCE_PURPOSE_INVALID = "maps_to_compliance_purpose_invalid"
MAPS_TO_REL_REVERSE = "mapped_from"
COMPLIANCE_PURPOSE = "compliance"
ROW = ("regulation", "duty_id@version", "level", "event_type", "satisfying_events", "gap")


@dataclass(frozen=True)
class Duty:
    regulation: str
    id: str
    version: str


@dataclass(frozen=True)
class Mapping:
    duty_id: str
    duty_version: str
    level: str
    event_type: str

    def covers(self, d: Duty) -> bool:
        return self.duty_id == d.id and self.duty_version == d.version


@dataclass(frozen=True)
class Subject:
    ref: str      # "SUBJECT@VERSION"
    level: str


@dataclass(frozen=True)
class RegulationRequirement:
    ref: str
    regulation: str
    duty_id: str
    duty_version: str


EVENT_TYPE_KEYS = ("decision", "verification", "inclusion", "supersession", "overrule", "move")


def duty_of(req: RegulationRequirement) -> Duty:
    return Duty(req.regulation, req.duty_id, req.duty_version)


def compliance_duties(reqs: Iterable[RegulationRequirement]) -> list[Duty]:
    return [duty_of(r) for r in reqs]


def _levels_from_preserves(preserves: Iterable[tuple[str, str]], levels: Iterable[str]) -> list[str]:
    level_set = set(levels)
    return [prop for purp, prop in preserves if purp == COMPLIANCE_PURPOSE and prop in level_set]


def _event_types_from_preserves(preserves: Iterable[tuple[str, str]]) -> list[str]:
    et_set = set(EVENT_TYPE_KEYS)
    return [prop for purp, prop in preserves if purp == COMPLIANCE_PURPOSE and prop in et_set]


def maps_to_regulation_target(req: RegulationRequirement) -> str:
    return f"{req.regulation}@{req.duty_version}"


def maps_to_compliance_purpose_invalid(ptr) -> bool:
    if getattr(ptr, "type", None) != "maps_to":
        return False
    for purp, prop in ptr.preserves:
        if purp != COMPLIANCE_PURPOSE and (
            prop in load_profile().levels
            or prop in {"decision", "verification", "inclusion", "supersession", "overrule", "move"}
        ):
            return True
    return False


def mapping_of(reqs: Iterable[RegulationRequirement], ptr, levels: Iterable[str]) -> Mapping | None:
    if ptr.type != "maps_to":
        return None
    if maps_to_compliance_purpose_invalid(ptr):
        return None
    req = next((r for r in reqs if r.ref == ptr.source), None)
    if req is None:
        return None
    if ptr.floating or ptr.target != maps_to_regulation_target(req):
        return None
    lvls = _levels_from_preserves(ptr.preserves, levels)
    ets = _event_types_from_preserves(ptr.preserves)
    if len(lvls) != 1 or len(ets) != 1:
        return None
    return Mapping(req.duty_id, req.duty_version, lvls[0], ets[0])


def compliance_maps(reqs: Iterable[RegulationRequirement], ptrs, levels: Iterable[str]) -> list[Mapping]:
    out: list[Mapping] = []
    for ptr in ptrs:
        m = mapping_of(reqs, ptr, levels)
        if m is not None:
            out.append(m)
    return out


@dataclass(frozen=True)
class Row:
    regulation: str
    duty: str
    duty_version: str
    level: str
    event_type: str
    satisfying: tuple[tuple[str, str], ...]   # (subject@version, event id)
    gap: bool


def completes(e) -> bool:
    """An event counts as evidence only in its completed form: a verification
    passes and is gate-accepted, a decision is decided (Lean completes)."""
    if e.type == "verification":
        return e.body.get("result") == "pass" and _gate_accepted(e)
    if e.type == "decision":
        return e.body.get("status") == "decided"
    return True


def satisfying(source, subjects: Iterable[Subject], m: Mapping) -> list[tuple[str, str]]:
    events = _events(source)
    inactive = _inactive(events)
    out = []
    for s in subjects:
        if s.level != m.level:
            continue
        subject = s.ref.rpartition("@")[0]
        out += [(s.ref, e.id) for e in events
                if subject in e.subjects and e.id not in inactive and e.type == m.event_type
                and completes(e) and s.ref in e.pinned_against]
    return out


def matrix(duties, maps, subjects, source) -> list[Row]:
    """One row per (duty, mapping)."""
    duties, maps, subjects = list(duties), list(maps), list(subjects)
    rows = []
    for d in duties:
        for m in maps:
            if m.covers(d):
                sat = tuple(satisfying(source, subjects, m))
                rows.append(Row(d.regulation, d.id, d.version, m.level, m.event_type, sat, not sat))
    return rows


def unmapped(duties, maps) -> list[Duty]:
    maps = list(maps)
    return [d for d in duties if not any(m.covers(d) for m in maps)]


def duty_unmapped_detail(d: Duty) -> str:
    return f"{d.regulation} {d.id}@{d.version}"


def compliance_violations(duties, maps, subjects, source, stored) -> list[Violation]:
    duties, maps = list(duties), list(maps)
    projected = matrix(duties, maps, subjects, source)
    out = [Violation(DUTY_UNMAPPED, duty_unmapped_detail(d)) for d in unmapped(duties, maps)]
    if list(stored) != projected:
        out.append(Violation(MATRIX_HAND_EDITED, "stored matrix differs from the projection"))
    return out


def compliance_matrix_from_inputs(
    regulation_requirements: Iterable[RegulationRequirement],
    pointers: Iterable,
    matrix_subjects: Iterable[Subject],
    source,
    *,
    levels: Iterable[str] | None = None,
) -> list[Row]:
    """Lean `complianceMatrix` / `matrix (complianceDutiesOf w) (complianceMapsOf w) …`."""
    lvls = load_profile().levels if levels is None else levels
    reqs = list(regulation_requirements)
    return matrix(
        compliance_duties(reqs),
        compliance_maps(reqs, pointers, lvls),
        matrix_subjects,
        source,
    )


def compliance_violations_from_inputs(
    regulation_requirements: Iterable[RegulationRequirement],
    pointers: Iterable,
    matrix_subjects: Iterable[Subject],
    source,
    stored: list[Row],
    *,
    levels: Iterable[str] | None = None,
) -> list[Violation]:
    """Lean `complianceViolationsFromInputs` (author-view duty_unmapped, matrix_hand_edited)."""
    lvls = load_profile().levels if levels is None else levels
    reqs = list(regulation_requirements)
    duties = compliance_duties(reqs)
    maps = compliance_maps(reqs, pointers, lvls)
    return compliance_violations(duties, maps, matrix_subjects, source, stored)
