"""Derived status (more-lean-model.md §9, kernel derived_status).

No status is stored or written. derive() folds the event log for one
subject@version into the chain

  verified -> accepted -> released (= done) -> proven_in_production

and reports why each state is or is not reached. drift_check() runs the
log-wide violations that need more than one event.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .checks import (PRODUCTION_EVIDENCE_BEFORE_RELEASE, VERIFICATION_UNPINNED,
                     Violation)
from .events import Event, is_pinned, parse_ref
from .profile import Profile, load_profile

CHAIN = ("verified", "accepted", "released", "proven_in_production")


@dataclass(frozen=True)
class Derived:
    subject: str
    version: str
    verified: bool
    accepted: bool
    released: bool
    proven_in_production: bool
    open_decisions: tuple[str, ...]
    violations: tuple[Violation, ...]
    reasons: tuple[str, ...]
    # id of the latest acceptance decision on subject@version (the one
    # `accepted` reads; Lean latestAcceptance), or None
    acceptance_event: str | None = None

    @property
    def done(self) -> bool:
        """done == released (§9). There is no event that sets it."""
        return self.released

    @property
    def state(self) -> str | None:
        """Highest chain state reached, or None."""
        reached = [s for s in CHAIN if getattr(self, s)]
        return reached[-1] if reached else None


def _events(source) -> list[Event]:
    evs = list(source.events() if hasattr(source, "events") else source)
    return sorted(evs, key=lambda e: (e.seq is None, e.seq or 0))


def _inactive(events: list[Event]) -> set[str]:
    """Event ids that a supersession or overrule has replaced. The
    replaced event stays in the log (history), it just stops counting."""
    out: set[str] = set()
    for e in events:
        if e.type in ("supersession", "overrule"):
            out.update(e.supersedes)
    return out


def _gate_accepted(e: Event) -> bool:
    return bool(e.body.get("gate")) and bool(e.body.get("witness"))


def _before(a: Event, b: Event) -> bool:
    """a happened before b: earlier in the log AND not later by author time."""
    if a.seq is None or b.seq is None:
        return False
    return a.seq < b.seq and a.at <= b.at


def _check_key(e: Event) -> tuple:
    """Lean latestPerCheck: the latest verification per check wins; a pass on
    one check never hides a fail on another check of the same gate (Fabian,
    2026-10-19). Lean keys on (gate, method); the optional `check` is part of
    the method here."""
    return (e.body.get("gate"), e.body.get("method"), e.body.get("check"))


def derive(source, ref: str, profile: Profile | None = None) -> Derived:
    """Fold events into the derived status of `ref` = 'SUBJECT@VERSION'."""
    profile = profile or load_profile()
    subject, version = parse_ref(ref)
    if version is None:
        raise ValueError(f"derive needs subject@version, got {ref!r}")
    events = _events(source)
    inactive = _inactive(events)
    reasons: list[str] = []
    violations: list[Violation] = []

    def about(e: Event) -> bool:
        return subject in e.subjects and e.id not in inactive

    # 1. test verification: gate-accepted, pinned to this exact version.
    # Latest verification per check (gate, method, check) wins; a failing latest check blocks.
    latest: dict[tuple, Event] = {}
    for e in events:
        if e.type != "verification" or not about(e) or e.body.get("stage", "test") != "test":
            continue
        if not e.pinned_against or not all(is_pinned(r) for r in e.pinned_against):
            violations.append(Violation(VERIFICATION_UNPINNED,
                                        "verification without a pinned version is unmeasured and satisfies no gate",
                                        e.id, subject))
            continue
        if ref not in e.pinned_against:
            continue  # pinned to another version: counts for nothing here
        if not _gate_accepted(e):
            reasons.append(f"verification {e.id} has no gate/witness; not gate-accepted")
            continue
        latest[_check_key(e)] = e
    passing = {k: e for k, e in latest.items() if e.body.get("result") == "pass"}
    failing = {k: e for k, e in latest.items() if e.body.get("result") == "fail"}
    verified = bool(passing) and not failing
    if not latest:
        reasons.append(f"no gate-accepted verification pinned to {ref}")
    for e in failing.values():
        reasons.append(f"latest verification {e.id} for check {_check_key(e)} fails")
    passing_ids = {e.id for e in passing.values()} if verified else set()

    # 2. business acceptance: a decided acceptance decision on this version
    # that links passing tests of this version. Latest acceptance wins.
    acc: Event | None = None
    for e in events:
        if e.type == "decision" and about(e) and e.body.get("kind") == "acceptance" \
                and e.body.get("status") == "decided" and ref in e.pinned_against:
            acc = e
    accepted = False
    if acc is None:
        reasons.append(f"no acceptance decision pinned to {ref}")
    elif acc.body.get("outcome") != "accepted":
        reasons.append(f"latest acceptance decision {acc.id} is {acc.body.get('outcome')}")
    else:
        tests = set(acc.body.get("tests") or ())
        if not tests:
            reasons.append(f"acceptance {acc.id} links no tests")
        elif not tests <= passing_ids:
            reasons.append(f"acceptance {acc.id} links tests that are not passing verifications of {ref}: "
                           f"{sorted(tests - passing_ids)}")
        else:
            accepted = True

    open_decisions = tuple(e.id for e in events
                           if e.type == "decision" and about(e) and e.body.get("status") == "open")

    # 3. release inclusion of this version.
    inclusions = [e for e in events if e.type == "inclusion" and about(e) and ref in e.pinned_against]
    released = False
    if not inclusions:
        reasons.append(f"{ref} is not included in a release/baseline")
    elif not verified:
        reasons.append("included, but not verified")
    elif profile.setting("done_requires_acceptance") and not accepted:
        reasons.append("included and verified, but not accepted (done_requires_acceptance)")
    else:
        released = True

    # 4. production evidence: pinned to a baseline that includes this
    # version, and only valid after that inclusion.
    proven = False
    own_baselines = {i.body.get("into") for i in inclusions}
    any_baselines = {i.body.get("into") for i in events
                     if i.type == "inclusion" and subject in i.subjects}
    for e in events:
        if e.type != "verification" or not about(e) or e.body.get("stage") != "production":
            continue
        pins = set(e.pinned_against)
        if not pins & own_baselines and pins & any_baselines:
            continue  # evidence for a baseline holding another version of the subject
        prior = [i for i in inclusions if i.body.get("into") in pins and _before(i, e)]
        if not prior:
            violations.append(Violation(
                PRODUCTION_EVIDENCE_BEFORE_RELEASE,
                f"production verification {e.id} pinned to {sorted(pins)} has no earlier "
                f"inclusion of {ref} into that baseline", e.id, subject))
            continue
        if e.body.get("result") == "pass" and _gate_accepted(e) and released:
            proven = True
    if released and not proven:
        reasons.append("released; no valid production evidence yet")

    return Derived(subject, version, verified, accepted, released, proven,
                   open_decisions, tuple(violations), tuple(reasons),
                   acc.id if acc is not None else None)


def drift_check(log, profile: Profile | None = None) -> list[Violation]:
    """Log-wide drift violations: event_mutated (hash chain re-check),
    verification_unpinned, production_evidence_before_release."""
    out: list[Violation] = list(log.verify()) if hasattr(log, "verify") else []
    events = _events(log)
    for e in events:
        if e.type != "verification":
            continue
        subj = e.subjects[0] if e.subjects else None
        # production evidence pins a baseline id (the `into` of an inclusion;
        # a baseline is immutable, so its id is its version)
        prod = e.body.get("stage") == "production"
        if not e.pinned_against or (not prod and not all(is_pinned(r) for r in e.pinned_against)):
            out.append(Violation(VERIFICATION_UNPINNED,
                                 "verification without a pinned version is unmeasured and satisfies no gate",
                                 e.id, subj))
        if e.body.get("stage") == "production":
            pins = set(e.pinned_against)
            if not any(i.type == "inclusion" and i.body.get("into") in pins
                       and set(i.subjects) & set(e.subjects) and _before(i, e) for i in events):
                out.append(Violation(PRODUCTION_EVIDENCE_BEFORE_RELEASE,
                                     f"production verification {e.id} has no earlier inclusion of its "
                                     f"subject into {sorted(pins)}", e.id, subj))
    return out
