"""agents-store demo — one identity, many lawful projections.

Creates (or reuses) one entity carrying {title, body, status, when},
materializes it into scratch/notes/ via the folder adapter, renders the
HTML pane, then flips `status` by editing the markdown FILE — the write
enters through the md wrapper, lands in the canonical store, and would
surface identically through CalDAV once Radicale runs
(examples/radicale.config).

Run twice: the second run reuses the entity (idempotent — only deltas
are appended, history grows, identity stays).

    .venv\\Scripts\\python examples/demo.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents_store import Change, connect  # noqa: E402
from agents_store.adapters import folder  # noqa: E402
from agents_store.capabilities.entity_html import EntityHtml  # noqa: E402
from agents_store.capabilities.markdown_html import MarkdownHtml  # noqa: E402
from agents_store.certify import certify, grant_roundtrip  # noqa: E402
from agents_store import kinds  # noqa: E402
from agents_store.mediator import wrapper_capability  # noqa: E402
from agents_store.pane import render  # noqa: E402
from agents_store.registry import Registry  # noqa: E402
from agents_store.store import Store  # noqa: E402
from agents_store.wrappers.ical import ICalWrapper  # noqa: E402
from agents_store.wrappers.markdown import MarkdownWrapper  # noqa: E402

def _scratch_root() -> Path:
    raw = os.environ.get("AGENTS_STORE_SCRATCH")
    return Path(raw) if raw else ROOT / "scratch"


def _paths() -> tuple[Path, Path]:
    root = _scratch_root()
    return root / "demo.sqlite", root / "notes"
MD_CORPUS = [
    {"title": "t", "body": "b"},
    {"title": "t", "status": "open", "body": "b"},
    {"when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z",
     "body": "b"},
    {"body": "b", "md:extra": {"k": "v"}},
]


def main() -> None:
    db, notes = _paths()
    db.parent.mkdir(parents=True, exist_ok=True)
    notes.mkdir(parents=True, exist_ok=True)
    conn = connect(str(db))
    store = Store(conn)
    mdw, icw = MarkdownWrapper(), ICalWrapper()
    cert = certify(conn, mdw, MD_CORPUS)
    grant_roundtrip(conn, mdw, cert)
    conn.commit()

    reg = Registry()
    reg.register_capability(wrapper_capability(mdw, "markdown"))
    reg.register_capability(wrapper_capability(icw, "ical"))
    reg.register_capability(MarkdownHtml())
    reg.register_capability(EntityHtml())

    # 1. entity: reuse via the anchor file if it exists (idempotent)
    anchor = notes / "demo-entity.md"
    e = None
    if anchor.exists():
        fid = mdw.peek_id(anchor.read_text(encoding="utf-8"))
        if fid and store.exists(fid):
            e = fid
    if e is None:
        e = store.transact([
            Change(e=None, a="title", v="Demo entity"),
            Change(e=None, a="body", v="one identity, many projections"),
            Change(e=None, a="status", v="open"),
            Change(e=None, a="when", v="2026-10-20T10:00:00Z"),
        ], wrapper="store", note="demo create").entity

    # 2. markdown projection
    rep = folder.sync(store, str(notes), mdw)
    view = store.view(e)
    path = view.get("md:path")
    md_file = notes / list(path)[0] if isinstance(path, tuple) else notes / str(path)
    print(f"entity   : {e}")
    print(f"kinds    : {sorted(kinds.of(conn, e))}")
    try:
        md_rel = md_file.relative_to(ROOT)
    except ValueError:
        md_rel = md_file
    print(f"md file  : {md_rel}")
    print("--- markdown ---")
    print(md_file.read_text(encoding="utf-8"))

    # 3. flip status through the FILE path (edit -> sync -> canonical tx)
    text = md_file.read_text(encoding="utf-8")
    cur = view.get("status")
    nxt = "done" if cur == "open" else "open"
    md_file.write_text(text.replace(f"status: {cur}", f"status: {nxt}"),
                       encoding="utf-8")
    folder.sync(store, str(notes), mdw)
    print(f"status   : {cur} -> {store.view(e)['status']} (via file edit)")

    # 4. every representation carries the same id
    print("--- ical (what CalDAV serves) ---")
    print(icw.get(e, store.view(e)))
    art = render(conn, reg, e, "html")
    print("--- html pane ---")
    print(getattr(art, "value", art))
    print(f"history  : {len(store.history(e))} datoms "
          f"(append-only; run again = deltas only)")
    conn.commit()


if __name__ == "__main__":
    main()
