"""Folder adapter: reconcile a directory of .md files with the store.

All filesystem I/O for the markdown projection lives here. The 'md'
wrapper stays pure (text <-> changes).

Rules:
- `id:` in frontmatter is the anchor; a file without it gets minted an
  entity and is rewritten with the id (converges on second sync);
- unknown / mismatched / colliding / unparseable ids -> refusal rows,
  file untouched;
- a store entity with `body` and no `md:path` ever (history-checked)
  is written out at <slug>.md;
- a `md:path` whose file vanished is retracted; the entity is NOT
  deleted (append-only substrate) and the file is not resurrected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Change, Refusal
from ..store import Store
from ..wrappers.markdown import MarkdownWrapper, _ParseFail


@dataclass
class SyncReport:
    scanned: int = 0
    created: int = 0
    files_written: int = 0
    tx_count: int = 0
    refusals: list[Refusal] = field(default_factory=list)


def _slug(title: Any, e: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")
    return (s or "untitled") + ".md" if s else f"untitled-{e[:8]}.md"


def _refuse(store: Store, wrapper: str, reason: str, e=None, a=None, payload=None) -> Refusal:
    store.conn.execute(
        "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?,?,?,?,?)",
        (wrapper, e, a, reason, None if payload is None else str(payload)),
    )
    return Refusal(wrapper=wrapper, reason=reason, e=e, a=a, payload=None if payload is None else str(payload))


def _paths_of(store: Store, e: str) -> set[str]:
    rows = store.conn.execute(
        "SELECT v FROM v_current WHERE e = ? AND a = 'md:path'", (e,)
    ).fetchall()
    return {r[0] for r in rows}


def _path_owner(store: Store, path: str) -> str | None:
    row = store.conn.execute(
        "SELECT e FROM v_current WHERE a = 'md:path' AND v = ?", (path,)
    ).fetchone()
    return row[0] if row else None


def _ever_had_path(store: Store, e: str) -> bool:
    return store.conn.execute(
        "SELECT 1 FROM datom WHERE e = ? AND a = 'md:path' LIMIT 1", (e,)
    ).fetchone() is not None


def sync(store: Store, root: str | Path, w: MarkdownWrapper | None = None) -> SyncReport:
    w = w or MarkdownWrapper()
    root = Path(root)
    rep = SyncReport()
    seen_by_entity: dict[str, set[str]] = {}

    for f in sorted(root.glob("*.md")):
        rep.scanned += 1
        rel = f.name
        text = f.read_text(encoding="utf-8")
        try:
            fid = w.peek_id(text)
        except _ParseFail as ex:
            rep.refusals.append(_refuse(store, "md", "parse-fail", payload=f"{rel}: {ex}"))
            continue

        if fid is not None and not store.exists(fid):
            rep.refusals.append(_refuse(store, "md", "unknown-entity", e=fid, payload=rel))
            continue

        owner = _path_owner(store, rel)
        if owner is not None and owner != fid:
            rep.refusals.append(_refuse(store, "md", "path-collision", e=fid, payload=rel))
            continue

        view = store.view(fid) if fid else {}
        res = w.put(text, fid, view)
        if res.refusals:
            for r in res.refusals:
                rep.refusals.append(_refuse(store, "md", r.reason, e=r.e or fid, a=r.a, payload=rel))
            continue  # put-level refusal: whole file rejected

        changes = list(res.changes)
        if fid is None or rel not in _paths_of(store, fid):
            target_e = fid if fid is not None else None
            changes.append(Change(e=target_e, a="md:path", v=rel))
        if changes:
            result = store.transact(changes, wrapper="md", note=f"folder sync {rel}")
            rep.tx_count += 1
            rep.refusals.extend(result.refusals)
            if fid is None and result.entity:
                fid = result.entity
                rep.created += 1

        if fid is not None:
            seen_by_entity.setdefault(fid, set()).add(rel)
            rendered = w.get(fid, store.view(fid))
            if rendered != text:
                f.write_text(rendered, encoding="utf-8")
                rep.files_written += 1

    # retract md:path datoms whose file vanished under this root
    all_entities = {
        r[0] for r in store.conn.execute("SELECT DISTINCT e FROM v_current WHERE a = 'md:path'")
    }
    for e in sorted(all_entities):
        stale = set()
        for p in _paths_of(store, e):
            if Path(p).parent == Path(".") and not (root / p).exists():
                stale.add(p)
        stale -= seen_by_entity.get(e, set())
        if stale:
            r = store.transact(
                [Change(e=e, a="md:path", v=p, added=False) for p in stale],
                wrapper="md", note="folder sync: vanished paths",
            )
            rep.tx_count += 1
            rep.refusals.extend(r.refusals)

    # write-back: entities renderable by the md wrapper that never had a
    # path get a file (any md-mapped attr, not only body — a CalDAV-created
    # event must appear as a frontmatter-only note too)
    renderable = {
        r[0] for r in store.conn.execute(
            "SELECT DISTINCT e FROM v_current WHERE a IN "
            "('title', 'status', 'when', 'end', 'body')")
    }
    for e in sorted(renderable):
        if _paths_of(store, e) or _ever_had_path(store, e):
            continue
        view = store.view(e)
        name = _slug(view.get("title"), e)
        if (root / name).exists():
            name = f"{_slug(view.get('title'), e)[:-3]}-{e[:8]}.md"
        f = root / name
        f.write_text(w.get(e, view), encoding="utf-8")
        rep.files_written += 1
        r = store.transact([Change(e=e, a="md:path", v=name)], wrapper="md",
                           note="folder sync: write-back")
        rep.tx_count += 1
        rep.refusals.extend(r.refusals)

    return rep
