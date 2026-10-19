"""Quality gates, the acceptance decision and the JWF board state
(PORTING.md §3.6-3.7, Lean More/Gate.lean and More/Jwf.lean;
kernel-proposal.json jira_status_model).

A gate is the condition of one transition (JWF p.10: "Die Bedingungen
liegen dort, wo der Status wechselt"). It holds when drift is clean on
what it touches and its JWF p.10 guards hold; QG1 also needs Ready. No
gate has an approval step. The acceptance decision is not a gate: it
reaches Abgenommen and is also the QG3 guard "freigegeben".

The board state is never set: it is the longest prefix of 14 true
conditions, so each state implies all earlier ones.
"""
from __future__ import annotations

from typing import Iterable

from .events import is_pinned, parse_ref
from .hierarchy import Node
from .profile import Profile, load_profile
from .ready import open_decisions, ready
from .relations import CLAIM_UNMET, Pointer, claim_met, outgoing, pinned_to_both, relation_check
from .status import _events, _gate_accepted, _inactive, derive, drift_check

ACCEPTANCE_TOPIC = "acceptance_decision"   # Lean acceptanceTopic (kernel addition `topic`)

# Gate.guards: (key, JWF p.10 wording, source). The wording must equal the spec.
GUARDS = {
    "QG1": (("goal_understood", "Ziel verstanden", "review"),
            ("acceptance_criteria_sufficient", "Akzeptanzkriterien ausreichend", "review"),
            ("essential_risks_known", "wesentliche Risiken bekannt", "review")),
    "QG2": (("implementation_complete", "Umsetzung fertig", "implementation_complete"),
            ("tests_successful", "Tests erfolgreich", "tests_pass"),
            ("decisions_traceable", "Entscheidungen nachvollziehbar", "decisions_traceable")),
    "QG3": (("released", "freigegeben", "acceptance_decided"),
            ("release_assigned", "Release zugeordnet", "release_assigned"),
            ("production_status_documented", "Produktions-/Change-Status dokumentiert",
             "production_documented")),
}
# Gate.reaches
REACHES = {"QG1": "Fertig für Einplanung", "QG2": "In Abnahme", "QG3": "Geschlossen"}


def acceptance_decided(source, ref: str, profile: Profile) -> bool:
    """Lean acceptanceDecided: `accepted`, and the latest acceptance on ref is
    the acceptance decision (topic) by a decider with an acceptor role."""
    d = derive(source, ref, profile)
    if not d.accepted or d.acceptance_event is None:
        return False
    e = next(x for x in _events(source) if x.id == d.acceptance_event)
    acceptors = set(profile.setting("acceptor_roles"))
    return (e.body.get("topic") == ACCEPTANCE_TOPIC
            and any(r in acceptors for r in profile.roles(e.body.get("decided_by"))))


def _guard_verified(source, ref: str, method: str) -> bool:
    """A live, passing, gate-accepted review verification pinned to ref whose
    method names the guard (Lean guardVerified)."""
    events = _events(source)
    inactive = _inactive(events)
    subject, _ = parse_ref(ref)
    return any(e.type == "verification" and subject in e.subjects and e.id not in inactive
               and ref in e.pinned_against and e.body.get("stage") == "review"
               and e.body.get("method") == method and e.body.get("result") == "pass"
               and _gate_accepted(e) for e in events)


def guard_holds(source, pointers, ref: str, profile: Profile, key: str, kind: str) -> bool:
    d = derive(source, ref, profile)
    subject, _ = parse_ref(ref)
    if kind == "review":
        return _guard_verified(source, ref, key)
    if kind == "implementation_complete":
        return any(claim_met(source, p, profile) for p in outgoing(pointers, ref, "implements"))
    if kind == "tests_pass":
        return d.verified
    if kind == "decisions_traceable":
        return not open_decisions(source, subject)
    if kind == "acceptance_decided":
        return acceptance_decided(source, ref, profile)
    if kind == "release_assigned":
        events = _events(source)
        inactive = _inactive(events)
        return any(e.type == "inclusion" and subject in e.subjects and e.id not in inactive
                   and ref in e.pinned_against for e in events)
    if kind == "production_documented":
        return d.proven_in_production
    raise ValueError(kind)


def drift_clean(source, pointers, ref: str, profile: Profile) -> bool:
    """No drift on an event about the subject; no relation violation on a
    pointer from ref except claim_unmet (Lean driftClean)."""
    subject, _ = parse_ref(ref)
    events = {e.id: e for e in _events(source)}
    for v in drift_check(source, profile):
        e = events.get(v.event_id) if v.event_id else None
        if e is not None and subject in e.subjects:
            return False
    mine = [p for p in pointers if p.source == ref]
    return all(v == CLAIM_UNMET for _, v in relation_check(source, mine, profile))


def gate_held(source, pointers, nodes, ref: str, gate: str,
              profile: Profile | None = None) -> bool:
    profile = profile or load_profile()
    pointers, nodes = list(pointers), list(nodes)
    return (drift_clean(source, pointers, ref, profile)
            and all(guard_holds(source, pointers, ref, profile, k, kind)
                    for k, _, kind in GUARDS[gate])
            and (gate != "QG1" or ready(source, pointers, nodes, ref, profile)))


def _conditions(source, pointers: Iterable[Pointer], nodes: Iterable[Node], ref: str,
                profile: Profile | None = None) -> list:
    """Lean jwfChain: the 14 conditions in board order, as thunks."""
    profile = profile or load_profile()
    pointers, nodes = list(pointers), list(nodes)
    events = _events(source)
    inactive = _inactive(events)
    subject, _ = parse_ref(ref)
    impl = outgoing(pointers, ref, "implements")
    d = derive(source, ref, profile)

    def live_about(s: str) -> bool:
        return any(s in e.subjects and e.id not in inactive for e in events)

    def child(levels) -> bool:
        return any(n.parent == subject and n.level in levels for n in nodes)

    def counts(e) -> bool:   # Lean countsFor
        return (e.type == "verification" and e.body.get("stage", "test") == "test"
                and bool(e.pinned_against) and all(is_pinned(r) for r in e.pinned_against)
                and ref in e.pinned_against and _gate_accepted(e))

    return [
        lambda: live_about(subject),                                  # 1 Ausgewählt
        lambda: child(("BP", "CM", "AC")),                            # 2 In fachlicher Beschreibung
        lambda: child(("UI", "API")),                                 # 3 In technischer Beschreibung
        lambda: gate_held(source, pointers, nodes, ref, "QG1", profile),  # 4 Fertig für Einplanung
        lambda: bool(impl),                                           # 5 Fertig für Entwicklung
        lambda: any(live_about(parse_ref(p.target)[0]) for p in impl),  # 6 In Entwicklung
        lambda: any(e.id not in inactive and pinned_to_both(p, e)
                    for p in impl for e in events),                   # 7 In technischer QS
        lambda: any(claim_met(source, p, profile) for p in impl),     # 8 Fertig zum Testen
        lambda: any(subject in e.subjects and e.id not in inactive and counts(e)
                    for e in events),                                 # 9 Im fachlichen Test
        lambda: d.verified,                                           # 10 Test abgeschlossen
        lambda: gate_held(source, pointers, nodes, ref, "QG2", profile),  # 11 In Abnahme
        lambda: acceptance_decided(source, ref, profile),             # 12 Abgenommen
        lambda: d.done,                                               # 13 Produktion
        lambda: gate_held(source, pointers, nodes, ref, "QG3", profile),  # 14 Geschlossen
    ]


def chain(source, pointers, nodes, ref: str, profile: Profile | None = None) -> list[bool]:
    """All 14 conditions (Lean jwfChain)."""
    return [bool(c()) for c in _conditions(source, pointers, nodes, ref, profile)]


def level(source, pointers, nodes, ref: str, profile: Profile | None = None) -> int:
    """Length of the longest prefix of true conditions (Lean jwfLevel). Stops at
    the first false condition."""
    n = 0
    for c in _conditions(source, pointers, nodes, ref, profile):
        if not c():
            break
        n += 1
    return n


def jwf_state(source, pointers, nodes, ref: str, profile: Profile | None = None) -> str:
    """The board state of ref. Pure; there is no other way to obtain it."""
    profile = profile or load_profile()
    return profile.status_model.states[level(source, pointers, nodes, ref, profile)]
