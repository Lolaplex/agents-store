"""Domain-neutral write/read surface for CLI and MCP (T18 + Wave 5 read/pane).

agents-store is the semantic kernel. Domains register as providers; this
module dispatches ``append``, lists domains, and exposes query/view/pane reads.
All writes go through Store.transact (never raw SQL from this layer).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from . import kinds, pane
from .capabilities.entity_html import EntityHtml
from .capabilities.markdown_html import MarkdownHtml
from .contracts import WriteRefusal
from .mediator import wrapper_capability
from .registry import Registry
from .store import Store
from .wrappers.ical import ICalWrapper
from .wrappers.jsoncal import JsoncalWrapper
from .wrappers.markdown import MarkdownWrapper

SURFACE = "agents-store"
UNKNOWN_DOMAIN = "unknown_domain"
OP_NOT_SUPPORTED = "op_not_supported"
UNKNOWN_ENTITY = "unknown_entity"


def default_registry() -> Registry:
    """Load entry-point domains (and wrappers / capabilities / violation ids)."""
    reg = Registry()
    reg.load_entry_points()
    return reg


def default_pane_registry(reg: Registry | None = None) -> Registry:
    """Return a Registry populated with built-in projection capabilities."""
    base = reg if reg is not None else default_registry()
    builtins = (
        wrapper_capability(MarkdownWrapper(), "markdown"),
        wrapper_capability(ICalWrapper(), "ical"),
        wrapper_capability(JsoncalWrapper(), "jsoncal"),
        MarkdownHtml(),
        EntityHtml(),
    )
    for cap in builtins:
        if cap.id not in base.capabilities:
            base.register_capability(cap)
    return base


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return value


def _latest_provenance(conn: sqlite3.Connection, entity_id: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        """SELECT t.agent, t.ts FROM tx t
           JOIN datom d ON d.tx = t.id
           WHERE d.e = ?
           ORDER BY t.id DESC LIMIT 1""",
        (entity_id,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """SELECT t.agent, t.ts FROM tx t
               JOIN entity e ON e.created_tx = t.id
               WHERE e.id = ?""",
            (entity_id,),
        ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def list_domains(reg: Registry | None = None) -> list[dict[str, Any]]:
    """Return registered domains with their declared ops and refusal ids."""
    reg = reg or default_registry()
    out: list[dict[str, Any]] = []
    for name in sorted(reg.domains):
        d = reg.domains[name]
        registry_fn = getattr(d, "violation_registry", None)
        registry = registry_fn() if callable(registry_fn) else ()
        out.append({
            "name": d.name,
            "write_ops": list(d.write_ops()),
            "read_ops": list(d.read_ops()),
            "refusal_ids": list(d.refusal_ids()),
            "violation_registry": [
                {
                    "id": v.id,
                    "severity": v.severity,
                    "provenance_ref": v.provenance_ref,
                    "fires_when": v.fires_when,
                }
                for v in registry
            ],
        })
    return out


def append(
    domain: str,
    payload: Mapping[str, Any],
    actor: str,
    *,
    conn: sqlite3.Connection,
    reg: Registry | None = None,
) -> str | WriteRefusal:
    """Dispatch an append to the named domain provider.

    Returns the minted entity/event id, or a typed WriteRefusal. Unknown
    domains and domains that do not declare ``append`` are refused here.
    """
    reg = reg or default_registry()
    provider = reg.domains.get(domain)
    if provider is None:
        return WriteRefusal(SURFACE, UNKNOWN_DOMAIN, payload=domain)
    if "append" not in provider.write_ops():
        return WriteRefusal(
            SURFACE, OP_NOT_SUPPORTED, payload=f"{domain} does not support append"
        )
    out = provider.append(conn, payload, actor)
    if not isinstance(out, WriteRefusal):
        conn.commit()
    return out


def query_entities(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return current materialized entity summaries filtered by kind/status."""
    bounded = max(1, min(int(limit), 1000))
    store = Store(conn)
    rows = conn.execute(
        "SELECT id FROM entity ORDER BY created_tx, id"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for (eid,) in rows:
        view = store.view(eid)
        if status is not None and view.get("status") != status:
            continue
        entity_kinds = sorted(kinds.of(conn, eid))
        if kind is not None and kind not in entity_kinds:
            continue
        actor, ts = _latest_provenance(conn, eid)
        out.append({
            "id": eid,
            "kinds": entity_kinds,
            "attrs": _json_safe(view),
            "actor": actor,
            "ts": ts,
        })
        if len(out) >= bounded:
            break
    return out


def view_entity(conn: sqlite3.Connection, entity_id: str) -> dict[str, Any] | WriteRefusal:
    """Return the full current materialized view and provenance for one entity."""
    store = Store(conn)
    if not store.exists(entity_id):
        return WriteRefusal(SURFACE, UNKNOWN_ENTITY, e=entity_id, payload=entity_id)
    actor, ts = _latest_provenance(conn, entity_id)
    history_count = conn.execute(
        "SELECT COUNT(*) FROM datom WHERE e = ?", (entity_id,)
    ).fetchone()[0]
    return {
        "id": entity_id,
        "kinds": sorted(kinds.of(conn, entity_id)),
        "attrs": _json_safe(store.view(entity_id)),
        "actor": actor,
        "ts": ts,
        "history_count": int(history_count),
    }


def render_pane(
    conn: sqlite3.Connection,
    reg: Registry | None,
    entity_id: str,
    target: str = "markdown",
) -> dict[str, Any] | WriteRefusal:
    """Render an entity into a registered representation or return WriteRefusal."""
    store = Store(conn)
    if not store.exists(entity_id):
        return WriteRefusal(SURFACE, UNKNOWN_ENTITY, e=entity_id, payload=entity_id)
    pane_reg = default_pane_registry(reg)
    art = pane.render(conn, pane_reg, entity_id, target)
    if isinstance(art, WriteRefusal):
        return art
    return {
        "id": entity_id,
        "target": art.out_kind,
        "exactness": art.exactness,
        "path": list(art.path.steps),
        "content": art.value,
    }
