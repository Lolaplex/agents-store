"""World-model projection (Lean More/WorldModel.lean)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .compliance import (
    RegulationRequirement,
    Row,
    Subject,
    compliance_duties,
    compliance_maps,
    compliance_matrix_from_inputs,
    compliance_violations_from_inputs,
)
from .jwf import level as jwf_level
from .profile import Profile, load_profile
from .ready import dor_violations, open_decisions
from .relations import Pointer, claim_met
from .status import Derived, derive

_HIERARCHY_LEVELS = load_profile().levels

OPEN_ITEM_REASONS = (
    "decision_open",
    "dor_violation",
    "claim_unmet",
    "compliance_gap",
    "challenge_open",
    "gap_signal_open",
)


@dataclass(frozen=True)
class SignalEntry:
    type_: str
    subject: str
    at_ms: int


@dataclass(frozen=True)
class SubjectKind:
    ref: str
    board_kind: str


@dataclass(frozen=True)
class ComplianceGapRef:
    regulation: str
    duty: str
    duty_version: str
    event_type: str

    @staticmethod
    def from_row(row: Row) -> ComplianceGapRef:
        return ComplianceGapRef(row.regulation, row.duty, row.duty_version, row.event_type)

    def to_dict(self) -> dict[str, str]:
        return {
            "regulation": self.regulation,
            "duty": self.duty,
            "duty_version": self.duty_version,
            "event_type": self.event_type,
        }


@dataclass(frozen=True)
class TypedOpenItem:
    board_kind: str
    subject: str
    reason: str
    detail: str | None = None
    compliance: tuple[ComplianceGapRef, ...] = ()

    def to_dict(self) -> dict:
        out: dict = {
            "board_kind": self.board_kind,
            "subject": self.subject,
            "reason": self.reason,
        }
        if self.detail is not None:
            out["detail"] = self.detail
        if self.compliance:
            out["compliance"] = [ref.to_dict() for ref in self.compliance]
        return out


@dataclass
class WorldInputs:
    pointers: list[Pointer] = field(default_factory=list)
    nodes: list = field(default_factory=list)
    subjects: list[SubjectKind] = field(default_factory=list)
    signals: list[SignalEntry] = field(default_factory=list)
    open_challenges: list[str] = field(default_factory=list)
    regulation_requirements: list[RegulationRequirement] = field(default_factory=list)
    matrix_subjects: list[Subject] = field(default_factory=list)


@dataclass
class WorldModel:
    per_subject: list[tuple[str, Derived]]
    open_items: list[TypedOpenItem]
    jwf_index: list[tuple[str, int]] = field(default_factory=list)


def _gap_open_subjects(signals: list[SignalEntry]) -> set[str]:
    opens = [s for s in signals if s.type_ == "gap-open"]
    closes = [s for s in signals if s.type_ == "gap-closed"]
    out: set[str] = set()
    for s in opens:
        if any(c.subject == s.subject and c.at_ms >= s.at_ms for c in closes):
            continue
        out.add(s.subject)
    return out


def _dedupe_refs(refs: list[ComplianceGapRef]) -> tuple[ComplianceGapRef, ...]:
    seen: list[ComplianceGapRef] = []
    out: list[ComplianceGapRef] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.append(ref)
        out.append(ref)
    return tuple(out)


def compliance_duties_of(w: WorldInputs):
    return compliance_duties(w.regulation_requirements)


def compliance_maps_of(w: WorldInputs, levels: list[str] | None = None):
    lvls = _HIERARCHY_LEVELS if levels is None else levels
    return compliance_maps(w.regulation_requirements, w.pointers, lvls)


def compliance_matrix(w: WorldInputs, source):
    return compliance_matrix_from_inputs(
        w.regulation_requirements, w.pointers, w.matrix_subjects, source, levels=_HIERARCHY_LEVELS
    )


def compliance_gap_rows(w: WorldInputs, source, sk: SubjectKind) -> list:
    rows = compliance_matrix(w, source)
    return [
        row
        for row in rows
        if row.gap
        and any(sub.ref == sk.ref and row.level == sub.level for sub in w.matrix_subjects)
    ]


def compliance_gap_refs_for_subject(w: WorldInputs, source, sk: SubjectKind) -> tuple[ComplianceGapRef, ...]:
    mapped = [ComplianceGapRef.from_row(row) for row in compliance_gap_rows(w, source, sk)]
    return _dedupe_refs(mapped)


def subject_has_compliance_gap(w: WorldInputs, source, sk: SubjectKind) -> bool:
    return bool(compliance_gap_refs_for_subject(w, source, sk))


def compliance_open_items(source, w: WorldInputs, sk: SubjectKind) -> list[TypedOpenItem]:
    refs = compliance_gap_refs_for_subject(w, source, sk)
    if not refs:
        return []
    subj = sk.ref.split("@", 1)[0]
    return [TypedOpenItem(sk.board_kind, subj, "compliance_gap", compliance=refs)]


def open_items_for_subject(
    profile: Profile, source, w: WorldInputs, sk: SubjectKind, gaps: set[str]
) -> list[TypedOpenItem]:
    subj = sk.ref.split("@", 1)[0]
    items: list[TypedOpenItem] = []
    if open_decisions(source, subj):
        items.append(TypedOpenItem(sk.board_kind, subj, "decision_open"))
    for vid in dor_violations(source, w.pointers, w.nodes, sk.ref, profile):
        items.append(TypedOpenItem(sk.board_kind, subj, "dor_violation", detail=vid))
    for ptr in w.pointers:
        if ptr.source != sk.ref:
            continue
        if not claim_met(source, ptr, profile):
            items.append(TypedOpenItem(sk.board_kind, subj, "claim_unmet", detail=ptr.id))
    items.extend(compliance_open_items(source, w, sk))
    if subj in w.open_challenges:
        items.append(TypedOpenItem(sk.board_kind, subj, "challenge_open"))
    if subj in gaps:
        items.append(TypedOpenItem(sk.board_kind, subj, "gap_signal_open"))
    return items


def project_world(profile: Profile, source, w: WorldInputs) -> WorldModel:
    gaps = _gap_open_subjects(w.signals)
    per_subject: list[tuple[str, Derived]] = []
    open_items: list[TypedOpenItem] = []

    for sk in w.subjects:
        d = derive(source, sk.ref, profile)
        per_subject.append((sk.ref, d))
        open_items.extend(open_items_for_subject(profile, source, w, sk, gaps))

    jwf_index = [
        (sk.ref.split("@", 1)[0], jwf_level(source, w.pointers, w.nodes, sk.ref, profile))
        for sk in w.subjects
    ]
    return WorldModel(per_subject=per_subject, open_items=open_items, jwf_index=jwf_index)
