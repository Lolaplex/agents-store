"""Per-event checks, decidable from the event alone.

The log runs these on append and refuses any event that fails (refuse by
default, agents-store guardrail 3); the same function audits imported
events without refusing. Checks that need the rest of the log
(verification_unpinned counting, production_evidence_before_release,
event_mutated) live in status.py / log.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .events import EVENT_TYPES, Event, is_pinned
from .profile import Profile

# Kernel violation ids (kernel-proposal.json derived_status / event.drift_checks_added)
STATUS_HAND_SET = "status_hand_set"
ACCEPTANCE_AS_STATUS = "acceptance_as_status"
VERIFICATION_UNPINNED = "verification_unpinned"
PRODUCTION_EVIDENCE_BEFORE_RELEASE = "production_evidence_before_release"
SUPERSESSION_UNLINKED = "supersession_unlinked"
EVENT_MUTATED = "event_mutated"
# Implementation ids for event rules the kernel states without naming
# (core_primitives.event.rules); listed in companion/python/README.md for a ruling.
ENVELOPE_INVALID = "envelope_invalid"
EVENT_TYPE_UNKNOWN = "event_type_unknown"
EVENT_UNPINNED = "event_unpinned"
OVERRULE_UNREASONED = "overrule_unreasoned"
OVERRULE_WITHOUT_SIGNAL = "overrule_without_signal"
MOVE_CHANGES_CONTENT = "move_changes_content"


@dataclass(frozen=True)
class Violation:
    id: str
    detail: str
    event_id: str | None = None
    subject: str | None = None


def _classify_status_write(value: Any, profile: Profile) -> str:
    """A status write whose value means business acceptance is the more
    specific acceptance_as_status; any other is status_hand_set."""
    v = str(value).strip().casefold()
    acc = {a.casefold() for a in profile.setting("acceptance_values")}
    acc |= {s.casefold() for s in profile.setting("acceptance_states")}
    return ACCEPTANCE_AS_STATUS if v in acc else STATUS_HAND_SET


def _status_writes(body: Any, keys: set[str], path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(body, dict):
        for k, v in body.items():
            p = f"{path}.{k}" if path else k
            if k.casefold() in keys:
                yield p, v
            yield from _status_writes(v, keys, p)
    elif isinstance(body, list):
        for i, v in enumerate(body):
            yield from _status_writes(v, keys, f"{path}[{i}]")


def check_event(e: Event, profile: Profile) -> list[Violation]:
    out: list[Violation] = []

    def v(vid: str, detail: str) -> None:
        out.append(Violation(vid, detail, e.id, e.subjects[0] if e.subjects else None))

    status_types = {t.casefold() for t in profile.setting("status_event_types")}
    if e.type.casefold() in status_types:
        target = e.body.get("to") or e.body.get("status") or e.body.get("state") or ""
        v(_classify_status_write(target, profile),
          f"event type {e.type!r} writes a status ({target!r}); status is derived, never set")
        return out
    if e.type not in EVENT_TYPES:
        v(EVENT_TYPE_UNKNOWN, f"{e.type!r} is not one of {EVENT_TYPES}")
        return out

    if not e.actor:
        v(ENVELOPE_INVALID, "actor is required")
    if not e.at:
        v(ENVELOPE_INVALID, "at is required")
    if not e.subjects:
        v(ENVELOPE_INVALID, "subjects must name at least one artifact")

    # No status is writable (derived_status.rule). decision.status open|decided
    # is the decision's own state, not the subject's, and is allowed.
    keys = {k.casefold() for k in profile.setting("status_keys")}
    for path, value in _status_writes(dict(e.body), keys):
        if e.type == "decision" and path == "status" and value in profile.setting("decision_statuses"):
            continue
        v(_classify_status_write(value, profile),
          f"body.{path} = {value!r} writes a status; status is derived, never set")

    if e.type == "verification":
        result = e.body.get("result")
        method = str(e.body.get("method", "")).casefold()
        if str(result).casefold() in {a.casefold() for a in profile.setting("acceptance_values")} \
                or method in ("acceptance", "abnahme", "business_acceptance"):
            v(ACCEPTANCE_AS_STATUS,
              "business acceptance recorded as a verification; it is a decision event (§9)")
        elif result not in profile.setting("verification_results"):
            v(ENVELOPE_INVALID, f"verification.result {result!r} not in {profile.setting('verification_results')}")
        stage = e.body.get("stage", "test")
        if stage not in profile.setting("verification_stages"):
            v(ENVELOPE_INVALID, f"verification.stage {stage!r} not in {profile.setting('verification_stages')}")
        # An unpinned verification is not refused: it is a recorded claim that
        # is 'unmeasured' and satisfies no gate. status.py reports it.
    else:
        if not e.pinned_against:
            v(EVENT_UNPINNED, f"{e.type} needs pinned_against (envelope: required)")
        elif e.type in ("decision", "inclusion") and not all(is_pinned(r) for r in e.pinned_against):
            # an inclusion/decision against a floating ref claims every version
            v(EVENT_UNPINNED, f"{e.type} pinned_against must name versions: {list(e.pinned_against)}")

    if e.type == "decision":
        if e.body.get("status") not in profile.setting("decision_statuses"):
            v(ENVELOPE_INVALID, f"decision.status must be one of {profile.setting('decision_statuses')}")
        if e.body.get("status") == "decided" and not e.body.get("decided_by"):
            v(ENVELOPE_INVALID, "a decided decision needs decided_by")
        if e.body.get("kind") == "acceptance" and e.body.get("outcome") not in ("accepted", "rejected"):
            v(ENVELOPE_INVALID, "acceptance decision needs outcome accepted|rejected")
        if e.body.get("kind") == "acceptance" and e.body.get("status") != "decided":
            v(ENVELOPE_INVALID, "an acceptance is only valid on a decided decision")
        # body.topic (optional): the question the decision answers, e.g.
        # "acceptance_decision". Kernel addition (Cypoe/more-framework@e32e5c3:lean-model/more-lean-model.md §12a);
        # admission does not check it, as in Lean.

    if e.type == "inclusion" and not e.body.get("into"):
        v(ENVELOPE_INVALID, "inclusion needs into (release/baseline)")

    if e.type in ("supersession", "overrule") and not e.supersedes:
        v(SUPERSESSION_UNLINKED, f"{e.type} must link the superseded item@version or event id")
    if e.type == "overrule":
        if not (e.reason or "").strip():
            v(OVERRULE_UNREASONED, "overrule needs a reason")
        sig = [s for s in e.signals if s and s != "acknowledged-none"]
        if not sig:
            v(OVERRULE_WITHOUT_SIGNAL, "overrule needs >= 1 signal and may not declare acknowledged-none")

    if e.type == "move":
        before, after = e.body.get("content_hash_before"), e.body.get("content_hash_after")
        if not before or not after:
            v(ENVELOPE_INVALID, "move needs content_hash_before and content_hash_after")
        elif before != after:
            v(MOVE_CHANGES_CONTENT, "move with changed content: split into move + supersession")
        if not e.body.get("custody_from") or not e.body.get("custody_to"):
            v(ENVELOPE_INVALID, "move needs custody_from and custody_to")
    return out
