"""Writability: a wrapper may write an attribute only when a passing
certificate backs a grant_ row. Everything else is refused.

INTERNAL_WRAPPER ('store') is the substrate's own authority — identity ops
(lineage) run under it. It is trusted by construction, not by certificate;
this is structural discipline, not a security boundary (same process).
"""
from __future__ import annotations

import sqlite3

INTERNAL_WRAPPER = "store"


def grant(conn: sqlite3.Connection, wrapper_id: str, attr_name: str, cert_id: int) -> None:
    """Record that `wrapper_id` may write `attr_name`, backed by `cert_id`.
    Loud on: unknown certificate, certificate that did not pass, duplicate."""
    row = conn.execute("SELECT result FROM certificate WHERE id = ?", (cert_id,)).fetchone()
    if row is None:
        raise ValueError(f"grant: no certificate {cert_id}")
    if row[0] != "pass":
        raise ValueError(f"grant: certificate {cert_id} result={row[0]!r}, need 'pass'")
    conn.execute(
        "INSERT INTO grant_ (wrapper, attr, certificate_id) VALUES (?, ?, ?)",
        (wrapper_id, attr_name, cert_id),
    )


def is_writable(conn: sqlite3.Connection, wrapper_id: str, attr_name: str) -> bool:
    if wrapper_id == INTERNAL_WRAPPER:
        return True
    return conn.execute(
        """SELECT 1 FROM grant_ g
           JOIN certificate c ON c.id = g.certificate_id
           WHERE g.wrapper = ? AND g.attr = ? AND c.result = 'pass'
           LIMIT 1""",
        (wrapper_id, attr_name),
    ).fetchone() is not None
