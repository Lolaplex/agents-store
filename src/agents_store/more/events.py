"""Event: the fifth core primitive (more-lean-model.md §8, kernel
core_primitives.event). Immutable, append-only, the only write path for
state. One envelope for all six types; type-specific fields live in `body`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping

EVENT_TYPES = ("decision", "verification", "inclusion", "supersession", "overrule", "move")

# Envelope fields that are hashed. id/seq/prev/digest are assigned by the log.
_ENVELOPE = ("type", "actor", "at", "pinned_against", "subjects", "reason",
             "supersedes", "signals", "provenance", "body")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ref(ref: str) -> tuple[str, str | None]:
    """'UC-042@3' -> ('UC-042', '3'); 'UC-042' -> ('UC-042', None) (floating)."""
    target, sep, version = ref.rpartition("@")
    if not sep or not target or not version:
        return ref, None
    return target, version


def is_pinned(ref: str) -> bool:
    return parse_ref(ref)[1] is not None


def _tup(v: Any) -> tuple:
    if v is None:
        return ()
    if isinstance(v, str):
        return (v,)
    return tuple(v)


@dataclass(frozen=True)
class Event:
    type: str
    actor: str
    subjects: tuple[str, ...]
    pinned_against: tuple[str, ...] = ()
    at: str = field(default_factory=now)
    reason: str | None = None
    supersedes: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    provenance: str | None = None
    body: Mapping[str, Any] = field(default_factory=dict)
    # assigned on append
    id: str | None = None
    seq: int | None = None
    prev: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("subjects", "pinned_against", "supersedes", "signals"):
            object.__setattr__(self, name, _tup(getattr(self, name)))
        # freeze body by a JSON round trip: no shared mutable state with the caller
        object.__setattr__(self, "body", json.loads(json.dumps(dict(self.body or {}))))

    def envelope(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in _ENVELOPE}
        for k in ("subjects", "pinned_against", "supersedes", "signals"):
            d[k] = list(d[k])
        return d

    def canonical(self) -> bytes:
        return json.dumps(self.envelope(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_envelope(cls, d: Mapping[str, Any], **assigned: Any) -> "Event":
        return cls(**{k: d.get(k) for k in _ENVELOPE if k in d}, **assigned)

    def with_assigned(self, **kw: Any) -> "Event":
        return replace(self, **kw)
