"""Minimal stdio MCP server (stdlib only). Tools: append, domains.

Actor comes from server config (--actor / serve_stdio actor=), never from a
tool argument. No HTTP. Lean MCP comes later.
"""
from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, TextIO

from . import connect
from .contracts import WriteRefusal
from .surface import append, default_registry, list_domains

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "agents-store", "version": "0.0.1"}

TOOLS = [
    {
        "name": "append",
        "description": (
            "Append via a registered domain provider. Writes go through "
            "store.transact. Actor is the server's configured actor."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Registered domain name."},
                "payload": {
                    "type": "object",
                    "description": "Domain payload (for more: event envelope without actor).",
                },
            },
            "required": ["domain", "payload"],
            "additionalProperties": False,
        },
    },
    {
        "name": "domains",
        "description": "List registered domain providers and their ops.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def _read_message(inp: BinaryIO) -> dict[str, Any] | None:
    """Read one Content-Length framed JSON-RPC message."""
    headers: dict[str, str] = {}
    while True:
        line = inp.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        raw = line.decode("utf-8", errors="replace").strip()
        if ":" in raw:
            k, v = raw.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = inp.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(out: BinaryIO, msg: dict[str, Any]) -> None:
    data = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    out.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    out.write(data)
    out.flush()


def _result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_text(obj: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(obj, sort_keys=True)}],
        "isError": bool(isinstance(obj, dict) and obj.get("ok") is False),
    }


def _handle_call(
    name: str,
    arguments: dict[str, Any],
    *,
    conn,
    actor: str,
    reg,
) -> dict[str, Any]:
    if name == "domains":
        return _tool_text({"ok": True, "domains": list_domains(reg)})
    if name == "append":
        domain = arguments.get("domain")
        payload = arguments.get("payload")
        if not isinstance(domain, str) or not domain:
            return _tool_text({"ok": False, "error": "domain is required"})
        if not isinstance(payload, dict):
            return _tool_text({"ok": False, "error": "payload must be an object"})
        # Actor is never taken from arguments.
        result = append(domain, payload, actor, conn=conn, reg=reg)
        if isinstance(result, WriteRefusal):
            return _tool_text({
                "ok": False,
                "refusal": {
                    "wrapper": result.wrapper,
                    "reason": result.reason,
                    "e": result.e,
                    "a": result.a,
                    "payload": result.payload,
                },
            })
        return _tool_text({"ok": True, "id": result})
    return _tool_text({"ok": False, "error": f"unknown tool {name!r}"})


def serve_stdio(
    *,
    db: str,
    actor: str,
    inp: BinaryIO | None = None,
    out: BinaryIO | None = None,
    err: TextIO | None = None,
) -> int:
    if not actor:
        (err or sys.stderr).write("mcp: --actor is required\n")
        return 2
    inp = inp or sys.stdin.buffer
    out = out or sys.stdout.buffer
    conn = connect(db)
    reg = default_registry()
    try:
        while True:
            msg = _read_message(inp)
            if msg is None:
                return 0
            if msg.get("method") and "id" not in msg:
                continue
            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params") or {}
            if method == "initialize":
                _write_message(out, _result(req_id, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                }))
            elif method == "tools/list":
                _write_message(out, _result(req_id, {"tools": TOOLS}))
            elif method == "tools/call":
                name = params.get("name", "")
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}
                result = _handle_call(name, arguments, conn=conn, actor=actor, reg=reg)
                _write_message(out, _result(req_id, result))
            elif method == "ping":
                _write_message(out, _result(req_id, {}))
            else:
                _write_message(out, _error(req_id, -32601, f"method not found: {method}"))
    finally:
        conn.close()
