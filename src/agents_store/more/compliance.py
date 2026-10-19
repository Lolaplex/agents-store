"""Compliance matrix as a projection (PORTING.md §3.4, Lean
More/Compliance.lean; kernel-proposal.json
generated_projections.compliance_matrix).

Inputs: one duty per regulation text (id and version), maps_to mappings
duty -> (hierarchy level, event type), the subjects with their level, and
the event log. The matrix is a pure function of these. A stored matrix
that differs from it is matrix_hand_edited; a duty with no mapping is
duty_unmapped. Mappings are per organisation, not part of the kernel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .checks import Violation
from .status import _events, _gate_accepted, _inactive

DUTY_UNMAPPED = "duty_unmapped"
MATRIX_HAND_EDITED = "matrix_hand_edited"
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


def compliance_violations(duties, maps, subjects, source, stored) -> list[Violation]:
    duties, maps = list(duties), list(maps)
    out = [Violation(DUTY_UNMAPPED, f"{d.regulation} {d.id}@{d.version}")
           for d in unmapped(duties, maps)]
    if list(stored) != matrix(duties, maps, subjects, source):
        out.append(Violation(MATRIX_HAND_EDITED, "stored matrix differs from the projection"))
    return out
