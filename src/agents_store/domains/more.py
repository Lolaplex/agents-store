"""MORe domain provider: append admits events through EventLog / store_bridge.

Writes land via Store.transact inside EventLog.append (T17). This module does
not open SQL itself.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agents_store.contracts import DomainViolationId, WriteRefusal
from agents_store.domains.more_violations import more_violation_registry
from agents_store.more.events import EVENT_TYPES, Event
from agents_store.more.log import EventLog, Refused
from agents_store.more.store_bridge import StoreWriteRefused

# Surface wrapper id on WriteRefusal rows this provider returns.
_WRAPPER = "more"

# Reasons this provider may emit (plus MORe check / number-guard ids passed through).
_STATIC_REFUSALS = (
    "payload_invalid",
    "append_refused",
)


@dataclass(frozen=True)
class MoreDomain:
    name: str = "more"

    def write_ops(self) -> Sequence[str]:
        return ("append",)

    def read_ops(self) -> Sequence[str]:
        return ()

    def refusal_ids(self) -> Sequence[str]:
        return _STATIC_REFUSALS

    def violation_registry(self) -> Sequence[DomainViolationId]:
        return more_violation_registry()

    def append(
        self,
        conn: sqlite3.Connection,
        payload: Mapping[str, Any],
        actor: str,
    ) -> str | WriteRefusal:
        if not isinstance(payload, Mapping):
            return WriteRefusal(_WRAPPER, "payload_invalid", payload="payload must be an object")
        if not actor or not isinstance(actor, str):
            return WriteRefusal(_WRAPPER, "payload_invalid", a="actor", payload="actor is required")
        try:
            event = _event_from_payload(payload, actor)
        except (TypeError, ValueError, KeyError) as exc:
            return WriteRefusal(_WRAPPER, "payload_invalid", payload=str(exc))

        log = EventLog(conn=conn)
        try:
            out = log.append(event)
        except Refused as refused:
            v = refused.violations[0]
            return WriteRefusal(_WRAPPER, v.id, payload=v.detail)
        except StoreWriteRefused as refused:
            return refused.refusals[0]
        except ValueError as exc:
            return WriteRefusal(_WRAPPER, "payload_invalid", payload=str(exc))
        return out.id  # type: ignore[return-value]


def _event_from_payload(payload: Mapping[str, Any], actor: str) -> Event:
    data = dict(payload)
    data["actor"] = actor  # surface actor wins; never trust caller-supplied actor in MCP
    typ = data.get("type")
    if typ not in EVENT_TYPES:
        raise ValueError(f"type must be one of {EVENT_TYPES}, got {typ!r}")
    if "subjects" not in data:
        raise ValueError("subjects is required")
    # Drop log-assigned fields if a caller echoed them.
    for k in ("id", "seq", "prev", "digest", "said"):
        data.pop(k, None)
    return Event.from_envelope(data)


def factory() -> MoreDomain:
    return MoreDomain()
