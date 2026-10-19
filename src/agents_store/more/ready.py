"""Ready and the Definition of Ready (PORTING.md §3.5, Lean
More/Ready.lean; kernel-proposal.json derived_status.ready). Ready is
derived, never set: no DoR check fails.
"""
from __future__ import annotations

from typing import Iterable

from .events import parse_ref
from .hierarchy import NODE_ANSWERS_MULTIPLE, NODE_ANSWERS_NONE, Node, lint
from .profile import Profile
from .relations import Pointer, outgoing, suspect
from .status import _events, _inactive

DOR_DECISION_OPEN = "dor_decision_open"
DOR_LINKED_DECISION_OPEN = "dor_linked_decision_open"
DOR_AC_UNCLEAR = "dor_ac_unclear"
DOR_DEPENDENCY_UNRESOLVED = "dor_dependency_unresolved"
DOR_SPEC_NOT_POINTED = "dor_spec_not_pointed"
DOR_SPEC_RESTATED = "dor_spec_restated"


def open_decisions(source, subject: str) -> list[str]:
    events = _events(source)
    inactive = _inactive(events)
    return [e.id for e in events if e.type == "decision" and subject in e.subjects
            and e.id not in inactive and e.body.get("status") == "open"]


def _node_lint(node: Node, profile: Profile) -> set[str]:
    """Lean lintNode: only the one_question findings of this node."""
    return {f.id for f in lint([node], profile)
            if f.id in (NODE_ANSWERS_NONE, NODE_ANSWERS_MULTIPLE)}


def dor_checks(source, pointers: Iterable[Pointer], nodes: Iterable[Node], ref: str,
               profile: Profile) -> list[tuple[bool, str]]:
    """Each DoR check (Lean dorChecks) with the id it raises when it fails."""
    pointers, nodes = list(pointers), list(nodes)
    subject, _ = parse_ref(ref)

    def has_open(s: str) -> bool:
        return bool(open_decisions(source, s))

    def subj(p: Pointer) -> str:
        return parse_ref(p.target)[0]

    ac_clear = any(n.level == "AC" and n.parent == subject and not _node_lint(n, profile)
                   for n in nodes)
    deps = (all(not has_open(subj(p)) and not suspect(source, p)
                for p in outgoing(pointers, ref, "depends_on"))
            and all(not has_open(subj(p)) for p in outgoing(pointers, ref, "causes_risk")))
    points = any(p.source == ref and not p.floating
                 and p.type in ("refines", "references", "derives_from") for p in pointers)
    restates = any(n.id == subject and NODE_ANSWERS_MULTIPLE in _node_lint(n, profile)
                   for n in nodes)
    return [
        (not has_open(subject), DOR_DECISION_OPEN),
        (all(not has_open(subj(p)) for p in outgoing(pointers, ref, "decided_in")),
         DOR_LINKED_DECISION_OPEN),
        (ac_clear, DOR_AC_UNCLEAR),
        (deps, DOR_DEPENDENCY_UNRESOLVED),
        (points, DOR_SPEC_NOT_POINTED),
        (not restates, DOR_SPEC_RESTATED),
    ]


def dor_violations(source, pointers, nodes, ref: str, profile: Profile) -> list[str]:
    return [vid for ok, vid in dor_checks(source, pointers, nodes, ref, profile) if not ok]


def ready(source, pointers, nodes, ref: str, profile: Profile) -> bool:
    return not dor_violations(source, pointers, nodes, ref, profile)
