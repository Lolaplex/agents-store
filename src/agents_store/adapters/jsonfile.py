"""JSON file adapter: reconcile one jsoncal export file with the store.

All file I/O for the jcal projection lives here. The 'jcal' wrapper stays
pure (item object <-> changes).

Rules:
- the file is a JSON array of item objects; anything else -> 'parse-fail';
- resolution: `jcal:uid` datum first, then `uid == entity id` (re-exported
  items carry minted ids); unresolved or absent uid -> mint;
- `jcal:path` = '<relpath>#<uid>' marks file membership; an item removed
  from the file gets its path datum retracted — the entity survives;
- after ingest the file is re-exported from the store (sorted keys,
  sorted by uid) so round-trips converge;
- per-item failures are refusal rows; other items still land.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Change, Refusal
from ..store import Store
from ..wrappers.jsoncal import JsoncalWrapper


@dataclass
class SyncReport:
    scanned: int = 0
    created: int = 0
    written: bool = False
    tx_count: int = 0
    refusals: list[Refusal] = field(default_factory=list)


def _refuse(store: Store, reason: str, e=None, a=None, payload=None) -> Refusal:
    store.conn.execute(
        "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?,?,?,?,?)",
        ("jcal", e, a, reason, None if payload is None else str(payload)),
    )
    return Refusal(wrapper="jcal", reason=reason, e=e, a=a,
                   payload=None if payload is None else str(payload))


def _by_uid(store: Store, uid: str) -> str | None:
    row = store.conn.execute(
        "SELECT e FROM v_current WHERE a = 'jcal:uid' AND v = ?", (uid,)
    ).fetchone()
    if row:
        return row[0]
    return uid if store.exists(uid) else None


def _paths_of(store: Store, e: str) -> list[str]:
    rows = store.conn.execute(
        "SELECT v FROM v_current WHERE e = ? AND a = 'jcal:path'", (e,)
    ).fetchall()
    return [r[0] for r in rows]


def sync(store: Store, path: str | Path, w: JsoncalWrapper | None = None) -> SyncReport:
    w = w or JsoncalWrapper()
    path = Path(path)
    rep = SyncReport()
    tag = path.name

    items: list[Any] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as ex:
            rep.refusals.append(_refuse(store, "parse-fail", payload=f"{tag}: {ex}"))
            return rep
        if not isinstance(data, list):
            rep.refusals.append(
                _refuse(store, "parse-fail", payload=f"{tag}: top level is not an array"))
            return rep
        items = data

    seen_slots: set[str] = set()
    for i, item in enumerate(items):
        rep.scanned += 1
        if not isinstance(item, dict):
            rep.refusals.append(_refuse(store, "parse-fail",
                                        payload=f"{tag}[{i}]: not an object"))
            continue
        raw_uid = item.get("uid")
        uid = str(raw_uid) if raw_uid is not None else None
        e = _by_uid(store, uid) if uid else None
        view = store.view(e) if e else {}
        res = w.put(json.dumps(item), e, view)
        if res.refusals:
            for r in res.refusals:
                rep.refusals.append(_refuse(store, r.reason, e=r.e or e,
                                            a=r.a, payload=f"{tag}[{i}] {r.payload}"))
            continue
        if res.changes:
            result = store.transact(list(res.changes), wrapper="jcal",
                                    note=f"jsonfile sync {tag}[{i}]")
            rep.tx_count += 1
            rep.refusals.extend(result.refusals)
            if e is None and result.entity:
                e = result.entity
                rep.created += 1
        if e is None:
            continue
        slot = f"{tag}#{uid or e}"
        if slot not in _paths_of(store, e):
            r = store.transact([Change(e=e, a="jcal:path", v=slot)],
                               wrapper="jcal", note=f"jsonfile sync {slot}")
            rep.tx_count += 1
            rep.refusals.extend(r.refusals)
        seen_slots.add(slot)

    # retract path datoms for items removed from THIS file
    for e, p in store.conn.execute(
            "SELECT e, v FROM v_current WHERE a = 'jcal:path'").fetchall():
        if p.startswith(f"{tag}#") and p not in seen_slots:
            r = store.transact([Change(e=e, a="jcal:path", v=p, added=False)],
                               wrapper="jcal", note=f"jsonfile sync: removed {p}")
            rep.tx_count += 1
            rep.refusals.extend(r.refusals)

    # write-back: re-export every entity member of this file
    member_es = [r[0] for r in store.conn.execute(
        "SELECT DISTINCT e FROM v_current WHERE a = 'jcal:path' "
        "AND v LIKE ?", (f"{tag}#%",))]
    if member_es:
        rendered = [json.loads(w.get(e, store.view(e))) for e in member_es]
        rendered.sort(key=lambda it: str(it.get("uid", "")))
        out = json.dumps(rendered, indent=2, sort_keys=True) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != out:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(out, encoding="utf-8")
            rep.written = True
    return rep
