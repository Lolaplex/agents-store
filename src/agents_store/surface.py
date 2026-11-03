"""Domain-neutral write/read surface for CLI and MCP (T18).

agents-store is the semantic kernel. Domains register as providers; this
module dispatches ``append`` and lists domains. All provider writes go through
Store.transact (never raw SQL from this layer).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from .contracts import WriteRefusal
from .registry import Registry

SURFACE = "agents-store"
UNKNOWN_DOMAIN = "unknown_domain"
OP_NOT_SUPPORTED = "op_not_supported"


def default_registry() -> Registry:
    """Load entry-point domains (and wrappers / capabilities / violation ids)."""
    reg = Registry()
    reg.load_entry_points()
    return reg


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
    return provider.append(conn, payload, actor)
