"""Console entry: ``agents-store`` — domain-neutral append and domain listing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import connect
from .contracts import WriteRefusal
from .surface import append, default_registry, list_domains


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


def _print_refusal(r: WriteRefusal) -> None:
    print(json.dumps({
        "ok": False,
        "refusal": {
            "wrapper": r.wrapper,
            "reason": r.reason,
            "e": r.e,
            "a": r.a,
            "payload": r.payload,
        },
    }, sort_keys=True), file=sys.stderr)


def cmd_append(args: argparse.Namespace) -> int:
    payload = _load_payload(args.payload, args.file)
    conn = connect(args.db)
    try:
        reg = default_registry()
        result = append(args.domain, payload, args.actor, conn=conn, reg=reg)
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


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve_stdio
    return serve_stdio(db=args.db, actor=args.actor)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agents-store",
        description="agents-store CLI: domain-neutral surface over the semantic kernel.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ap = sub.add_parser("append", help="Append via a domain provider (writes through store.transact).")
    ap.add_argument("--domain", required=True, help="Registered domain name (e.g. more).")
    ap.add_argument("--actor", required=True, help="Actor DID or id for the write.")
    ap.add_argument("--db", default=":memory:", help="Store SQLite path (default: :memory:).")
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

    mp = sub.add_parser("mcp", help="Run the domain-neutral MCP server on stdio.")
    mp.add_argument("--actor", required=True, help="Actor for all appends (never taken from tools).")
    mp.add_argument("--db", default=":memory:", help="Store SQLite path (default: :memory:).")
    mp.set_defaults(func=cmd_mcp)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
