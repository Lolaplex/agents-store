"""Console entry: ``agents-store`` — domain-neutral append, reads and panes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__, connect
from .contracts import WriteRefusal
from .surface import (
    append,
    default_registry,
    list_domains,
    query_entities,
    render_pane,
    view_entity,
)


def _default_db() -> str:
    return os.environ.get("AGENTS_STORE_DB", "").strip() or ":memory:"


def _resolve_actor(raw: str | None) -> str:
    actor = (raw or os.environ.get("AGENTS_ACTOR_DID", "")).strip()
    if not actor:
        raise SystemExit("error: --actor or AGENTS_ACTOR_DID is required")
    return actor


def _load_payload(raw: str | None, path: str | None) -> dict[str, Any]:
    if path and raw:
        raise SystemExit("pass either a JSON argument or --file, not both")
    if path:
        text = Path(path).read_text(encoding="utf-8")
    elif raw is None or raw == "-":
        text = sys.stdin.read()
    else:
        text = raw
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"payload is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("payload must be a JSON object")
    return data


def _refusal_dict(r: WriteRefusal) -> dict[str, Any]:
    return {
        "ok": False,
        "refusal": {
            "wrapper": r.wrapper,
            "reason": r.reason,
            "e": r.e,
            "a": r.a,
            "payload": r.payload,
        },
    }


def _print_refusal(r: WriteRefusal) -> None:
    print(json.dumps(_refusal_dict(r), sort_keys=True), file=sys.stderr)


def cmd_append(args: argparse.Namespace) -> int:
    actor = _resolve_actor(args.actor)
    payload = _load_payload(args.payload, args.file)
    reg = default_registry()
    conn = connect(args.db)
    try:
        result = append(args.domain, payload, actor, conn=conn, reg=reg)
    finally:
        conn.close()
    if isinstance(result, WriteRefusal):
        _print_refusal(result)
        return 1
    print(json.dumps({"ok": True, "id": result}, sort_keys=True))
    return 0


def cmd_domains(_args: argparse.Namespace) -> int:
    rows = list_domains(default_registry())
    print(json.dumps({"ok": True, "domains": rows}, sort_keys=True, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        items = query_entities(
            conn,
            kind=args.kind,
            status=args.status,
            limit=args.limit,
        )
    finally:
        conn.close()
    print(json.dumps({"ok": True, "items": items}, sort_keys=True, indent=2))
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        result = view_entity(conn, args.entity_id)
    finally:
        conn.close()
    if isinstance(result, WriteRefusal):
        _print_refusal(result)
        return 1
    print(json.dumps({"ok": True, "entity": result}, sort_keys=True, indent=2))
    return 0


def cmd_pane(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        result = render_pane(conn, None, args.entity_id, target=args.target)
    finally:
        conn.close()
    if isinstance(result, WriteRefusal):
        _print_refusal(result)
        return 1
    print(json.dumps({"ok": True, "pane": result}, sort_keys=True, indent=2))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve_stdio

    actor = _resolve_actor(args.actor)
    return serve_stdio(db=args.db, actor=actor)


def help_json_spec() -> dict[str, Any]:
    """Return structured CLI contract matching klanker helpjson discovery."""
    return {
        "name": "agents-store",
        "version": __version__,
        "description": "One identity, many lawful projections: workspace calendar/task/note/decision store.",
        "commands": [
            {
                "name": "domains",
                "description": "List registered domain providers and their ops.",
                "usage": "agents-store domains",
                "side_effects": "read-only",
                "options": [],
            },
            {
                "name": "list",
                "description": "List current entities filtered by kind (event/task/note/decision) or status.",
                "usage": "agents-store list [--kind KIND] [--status STATUS] [--limit N] [--db DB]",
                "side_effects": "read-only",
                "options": [
                    {"flags": ["--kind"], "dest": "kind", "help": "Kind filter (event, task, note, decision)"},
                    {"flags": ["--status"], "dest": "status", "help": "Task status filter (open, done)"},
                    {"flags": ["--limit"], "dest": "limit", "help": "Maximum items to return"},
                    {"flags": ["--db"], "dest": "db", "help": "SQLite store path (default AGENTS_STORE_DB)"},
                ],
            },
            {
                "name": "view",
                "description": "Inspect one entity's materialized attributes, kinds and provenance.",
                "usage": "agents-store view ENTITY_ID [--db DB]",
                "side_effects": "read-only",
                "arguments": [
                    {"name": "entity_id", "dest": "entity_id", "help": "Minted entity ID", "required": True},
                ],
                "options": [
                    {"flags": ["--db"], "dest": "db", "help": "SQLite store path (default AGENTS_STORE_DB)"},
                ],
            },
            {
                "name": "pane",
                "description": "Render one entity into a certified projection (markdown, ical, html, jsoncal).",
                "usage": "agents-store pane ENTITY_ID [--target TARGET] [--db DB]",
                "side_effects": "read-only",
                "arguments": [
                    {"name": "entity_id", "dest": "entity_id", "help": "Minted entity ID", "required": True},
                ],
                "options": [
                    {"flags": ["--target"], "dest": "target", "help": "Projection target kind (default markdown)"},
                    {"flags": ["--db"], "dest": "db", "help": "SQLite store path (default AGENTS_STORE_DB)"},
                ],
            },
            {
                "name": "append",
                "description": "Append a calendar event, task, note, or MORe decision through Store.transact.",
                "usage": "agents-store append --domain DOMAIN [--actor DID] [--db DB] [--file FILE] [PAYLOAD]",
                "side_effects": "mutating",
                "arguments": [
                    {"name": "payload", "dest": "payload", "help": "JSON object payload (or '-' for stdin)", "nargs": "?", "required": False},
                ],
                "options": [
                    {"flags": ["--domain"], "dest": "domain", "help": "Registered domain (e.g. records, more)", "required": True},
                    {"flags": ["--actor"], "dest": "actor", "help": "Actor DID (fallback AGENTS_ACTOR_DID)"},
                    {"flags": ["--db"], "dest": "db", "help": "SQLite store path (default AGENTS_STORE_DB)"},
                    {"flags": ["--file"], "dest": "file", "help": "Read JSON payload from file path"},
                ],
            },
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agents-store",
        description="agents-store CLI: domain-neutral surface over the semantic kernel.",
    )
    p.add_argument(
        "--help-json",
        action="store_true",
        help="Emit machine-readable CLI command & side_effects metadata as JSON.",
    )
    sub = p.add_subparsers(dest="cmd")

    ap = sub.add_parser("append", help="Append via a domain provider (writes through store.transact).")
    ap.add_argument("--domain", required=True, help="Registered domain name (e.g. records, more).")
    ap.add_argument("--actor", default=None, help="Actor DID or id (defaults to AGENTS_ACTOR_DID).")
    ap.add_argument("--db", default=_default_db(), help="Store SQLite path (default: AGENTS_STORE_DB or :memory:).")
    ap.add_argument("--file", dest="file", default=None, help="Read JSON payload from this path.")
    ap.add_argument(
        "payload",
        nargs="?",
        default=None,
        help="JSON object, or '-' for stdin (default when --file is omitted).",
    )
    ap.set_defaults(func=cmd_append)

    dp = sub.add_parser("domains", help="List registered domain providers.")
    dp.set_defaults(func=cmd_domains)

    lp = sub.add_parser("list", aliases=["query"], help="List entities filtered by kind/status.")
    lp.add_argument("--kind", default=None, help="Filter by kind (event, task, note, decision).")
    lp.add_argument("--status", default=None, help="Filter by status (open, done).")
    lp.add_argument("--limit", type=int, default=100, help="Maximum items to return (default 100).")
    lp.add_argument("--db", default=_default_db(), help="Store SQLite path (default: AGENTS_STORE_DB or :memory:).")
    lp.set_defaults(func=cmd_list)

    vp = sub.add_parser("view", help="View an entity's materialized attrs, kinds and provenance.")
    vp.add_argument("entity_id", help="Entity ID to inspect.")
    vp.add_argument("--db", default=_default_db(), help="Store SQLite path (default: AGENTS_STORE_DB or :memory:).")
    vp.set_defaults(func=cmd_view)

    pp = sub.add_parser("pane", help="Render an entity through certified projection capabilities.")
    pp.add_argument("entity_id", help="Entity ID to render.")
    pp.add_argument("--target", default="markdown", help="Target kind (markdown, ical, html, jsoncal).")
    pp.add_argument("--db", default=_default_db(), help="Store SQLite path (default: AGENTS_STORE_DB or :memory:).")
    pp.set_defaults(func=cmd_pane)

    mp = sub.add_parser("mcp", help="Run the domain-neutral MCP server on stdio.")
    mp.add_argument("--actor", default=None, help="Actor DID for all appends (defaults to AGENTS_ACTOR_DID).")
    mp.add_argument("--db", default=_default_db(), help="Store SQLite path (default: AGENTS_STORE_DB or :memory:).")
    mp.set_defaults(func=cmd_mcp)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "help_json", False):
        print(json.dumps(help_json_spec(), indent=2, sort_keys=True))
        return 0
    if not getattr(args, "cmd", None):
        parser.error("a subcommand is required (or pass --help-json)")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
