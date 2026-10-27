"""Kind membership: structural over attr names, multiplicative, graded.

An entity is in every kind whose `required` attrs are all present.
`derivations` fill gaps for display only — a derivable missing attr is
reported as such, marked derived, never written back.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .contracts import GapFill, KindSpec
from .store import Store


def _kind_specs(conn: sqlite3.Connection) -> list[KindSpec]:
    rows = conn.execute("SELECT name, required, optional, derivations FROM kind").fetchall()
    out = []
    for name, required, optional, derivations in rows:
        derivs = tuple(
            GapFill(attr=d["attr"], from_attrs=tuple(d["from"]), rule=d["rule"])
            for d in json.loads(derivations)
        )
        out.append(
            KindSpec(name=name, required=tuple(json.loads(required)),
                     optional=tuple(json.loads(optional)), derivations=derivs)
        )
    return out


@dataclass(frozen=True)
class GapsReport:
    kind: str
    member: bool                      # all required present
    have_required: tuple[str, ...]
    missing: tuple[str, ...]          # required, absent, NOT derivable
    derivable: tuple[str, ...]        # required, absent, fillable by a declared derivation
    present_optional: tuple[str, ...]


def of(conn: sqlite3.Connection, e: str) -> set[str]:
    """Kind names the entity currently satisfies (all required attrs present)."""
    present = set(Store(conn).view(e))
    return {
        k.name for k in _kind_specs(conn)
        if k.required and all(a in present for a in k.required)
    }


def gaps(conn: sqlite3.Connection, e: str, kind: str) -> GapsReport:
    present = set(Store(conn).view(e))
    spec = next((k for k in _kind_specs(conn) if k.name == kind), None)
    if spec is None:
        raise ValueError(f"unknown kind {kind!r}")
    have = tuple(a for a in spec.required if a in present)
    missing: list[str] = []
    derivable: list[str] = []
    for a in spec.required + spec.optional:
        if a in present:
            continue
        covered = any(
            d.attr == a and all(f in present for f in d.from_attrs)
            for d in spec.derivations
        )
        if covered:
            derivable.append(a)
        elif a in spec.required:
            missing.append(a)
    return GapsReport(
        kind=kind,
        member=not missing,  # derivable gaps don't block membership; they mark display-only fills
        have_required=have,
        missing=tuple(missing),
        derivable=tuple(derivable),
        present_optional=tuple(a for a in spec.optional if a in present),
    )
