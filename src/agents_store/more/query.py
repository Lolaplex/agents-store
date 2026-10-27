"""Store-level queries over materialized MORe events.

These read the more:* datoms through Store.find (current values, (a, v)
index), not the JSON envelopes. They return event ids (= entity ids) in
materialization order. Liveness (supersession/overrule) is not applied
here; fold the returned events with status.py / decisions.py for that.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents_store.store import Store

from .events import parse_ref
from .said import is_said


def events_about(store: Store, subject: str) -> list[str]:
    """Events whose subjects include `subject`: a ref to a store entity
    (more:subject) or a pointer target id (more:subject_ptr)."""
    return _merge(store, store.find("more:subject", subject),
                  store.find("more:subject_ptr", subject))


def events_pinned_against(store: Store, pin: str) -> list[str]:
    """Events with exactly `pin` in pinned_against (e.g. 'UC-1@3', a commit
    sha or a baseline name)."""
    return store.find("more:pinned_against", pin)


def events_pinned_to(store: Store, target: str) -> list[str]:
    """Events pinned against any version of `target` ('target@…'), or
    against `target` itself (a baseline or commit pin has no '@')."""
    return _merge(store, store.find("more:pinned_against", target),
                  store.find("more:pinned_against", prefix=f"{target}@"))


def events_by_said(store: Store, said: str) -> list[str]:
    """Event names (ids) bound to the content digest `said` (more:said).
    One name per SAID, since the name is part of the hashed content."""
    return store.find("more:said", said)


@dataclass(frozen=True)
class Resolved:
    """A pin or pointer string resolved against the store.

    kind: 'said' (target@<CESR digest>), 'pin' (target@tx, more:pin form),
    'floating' (no version) or 'external' (target is not a store entity).
    ok: True/False when the store can check the version, None otherwise."""
    ref: str
    target: str
    version: str | None
    kind: str
    ok: bool | None


def resolve(store: Store, ref: str) -> Resolved:
    """Resolve 'X', 'X@<tx>' or 'X@<SAID>' (pinned_against, more:pin or a
    pointer target). A SAID version is verified against X's more:said."""
    target, version = parse_ref(ref)
    if version is None:
        return Resolved(ref, target, None, "floating", True if store.exists(target) else None)
    if not store.exists(target):
        return Resolved(ref, target, version, "said" if is_said(version) else "external", None)
    view = store.view(target)
    if is_said(version):
        return Resolved(ref, target, version, "said", view.get("more:said") == version)
    pins = view.get("more:pin")
    return Resolved(ref, target, version, "pin", (ref in pins) if pins else None)


def _merge(store: Store, *lists: list[str]) -> list[str]:
    ids = {e for xs in lists for e in xs}
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    rows = store.conn.execute(
        f"SELECT id FROM entity WHERE id IN ({ph}) ORDER BY created_tx, id", sorted(ids)
    ).fetchall()
    return [r[0] for r in rows]
