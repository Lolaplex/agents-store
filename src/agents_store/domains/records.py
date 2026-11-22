"""Records domain provider: calendar events, tasks and notes through Store.transact."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from agents_store.contracts import Change, DomainViolationId, WriteRefusal
from agents_store.store import Store

_WRAPPER = "records"
_STORE_WRAPPER = "store"

_STATIC_REFUSALS = (
    "payload_invalid",
    "unknown_entity",
    "invalid_attr",
    "invalid_value",
)

_ALLOWED_ATTRS = frozenset({"title", "body", "when", "end", "status"})
_INSTANT_ATTRS = frozenset({"when", "end"})
_VALID_STATUS = frozenset({"open", "done"})
_SUBSTANTIVE = frozenset({"body", "when", "status", "end"})
_KINDS = frozenset({"event", "task", "note"})
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z$")


def _valid_utc_instant(raw: Any) -> bool:
    if not isinstance(raw, str) or not _UTC_RE.fullmatch(raw.strip()):
        return False
    try:
        datetime.fromisoformat(raw.strip()[:-1])
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class RecordsDomain:
    name: str = "records"

    def write_ops(self) -> Sequence[str]:
        return ("append",)

    def read_ops(self) -> Sequence[str]:
        return ("list", "view")

    def refusal_ids(self) -> Sequence[str]:
        return _STATIC_REFUSALS

    def violation_registry(self) -> Sequence[DomainViolationId]:
        return ()

    def append(
        self,
        conn: sqlite3.Connection,
        payload: Mapping[str, Any],
        actor: str,
    ) -> str | WriteRefusal:
        store = Store(conn)

        def _refuse(reason: str, *, e: str | None = None, a: str | None = None, detail: str = "") -> WriteRefusal:
            return store.record_refusal(
                WriteRefusal(_WRAPPER, reason, e=e, a=a, payload=detail or reason)
            )

        if not isinstance(payload, Mapping):
            return _refuse("payload_invalid", detail="payload must be an object")
        if not actor or not isinstance(actor, str) or not actor.strip():
            return _refuse("payload_invalid", a="actor", detail="actor is required")
        actor_clean = actor.strip()

        raw_entity = payload.get("entity")
        entity_id: str | None = None
        if raw_entity is not None:
            if not isinstance(raw_entity, str) or not raw_entity.strip():
                return _refuse("payload_invalid", a="entity", detail="entity must be a non-empty string")
            entity_id = raw_entity.strip()
            if not store.exists(entity_id):
                return _refuse("unknown_entity", e=entity_id, detail=f"unknown entity {entity_id!r}")

        kind = payload.get("kind")
        if kind is not None:
            if not isinstance(kind, str) or kind not in _KINDS:
                return _refuse(
                    "invalid_value",
                    a="kind",
                    detail=f"kind must be one of {sorted(_KINDS)}, got {kind!r}",
                )

        note = payload.get("note")
        if note is not None and not isinstance(note, str):
            return _refuse("invalid_value", a="note", detail="note must be a string")

        # Extract attributes from explicit "attrs" map or top-level keys; caller-supplied
        # "actor" is deliberately ignored so surface actor identity cannot be spoofed.
        raw_attrs = payload.get("attrs")
        if raw_attrs is not None:
            if not isinstance(raw_attrs, Mapping):
                return _refuse("payload_invalid", a="attrs", detail="attrs must be an object")
            attr_map: dict[str, Any] = dict(raw_attrs)
        else:
            skip = {"entity", "kind", "note", "actor", "attrs"}
            attr_map = {str(k): v for k, v in payload.items() if str(k) not in skip}

        if not attr_map:
            return _refuse("payload_invalid", e=entity_id, detail="at least one record attribute is required")

        changes: list[Change] = []
        for k, v in attr_map.items():
            if k not in _ALLOWED_ATTRS:
                return _refuse("invalid_attr", e=entity_id, a=k, detail=f"unsupported attr {k!r}")
            if v is None:
                return _refuse("invalid_value", e=entity_id, a=k, detail=f"{k} must not be null")
            if k == "status":
                if not isinstance(v, str) or v not in _VALID_STATUS:
                    return _refuse(
                        "invalid_value",
                        e=entity_id,
                        a=k,
                        detail=f"status must be 'open' or 'done', got {v!r}",
                    )
                changes.append(Change(e=entity_id, a=k, v=v))
            elif k in _INSTANT_ATTRS:
                if not _valid_utc_instant(v):
                    return _refuse(
                        "invalid_value",
                        e=entity_id,
                        a=k,
                        detail=f"{k} must be UTC ISO-8601 with trailing Z, got {v!r}",
                    )
                changes.append(Change(e=entity_id, a=k, v=v.strip()))
            else:
                if not isinstance(v, str) or (k == "title" and not v.strip()):
                    return _refuse("invalid_value", e=entity_id, a=k, detail=f"{k} must be a non-empty string")
                changes.append(Change(e=entity_id, a=k, v=v))

        # New entities must satisfy the target kind (when declared) or hold at least one
        # substantive attr (matches agents_store.pane.SUBSTANTIVE).
        if entity_id is None:
            present = {c.a for c in changes}
            if kind == "event" and "when" not in present:
                return _refuse("payload_invalid", a="when", detail="event requires 'when'")
            if kind == "task" and "status" not in present:
                return _refuse("payload_invalid", a="status", detail="task requires 'status'")
            if kind == "note" and "body" not in present:
                return _refuse("payload_invalid", a="body", detail="note requires 'body'")
            if not (present & _SUBSTANTIVE):
                return _refuse(
                    "payload_invalid",
                    detail="new record requires at least one of body, when, end, or status",
                )

        op = "evolve" if entity_id is not None else "assert"
        tx_res = store.transact(
            changes,
            wrapper=_STORE_WRAPPER,
            agent=actor_clean,
            op=op,
            note=note or f"records:{kind or op}",
        )
        if tx_res.refusals:
            return tx_res.refusals[0]
        return entity_id if entity_id is not None else tx_res.entity  # type: ignore[return-value]


def factory() -> RecordsDomain:
    return RecordsDomain()
