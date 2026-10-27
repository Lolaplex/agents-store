"""Store-level queries over materialized MORe events.

These read the more:* datoms through Store.find (current values, (a, v)
index), not the JSON envelopes. They return event ids (= entity ids) in
materialization order. Liveness (supersession/overrule) is not applied
here; fold the returned events with status.py / decisions.py for that.
"""
from __future__ import annotations

from agents_store.store import Store


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


def _merge(store: Store, *lists: list[str]) -> list[str]:
    ids = {e for xs in lists for e in xs}
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    rows = store.conn.execute(
        f"SELECT id FROM entity WHERE id IN ({ph}) ORDER BY created_tx, id", sorted(ids)
    ).fetchall()
    return [r[0] for r in rows]
