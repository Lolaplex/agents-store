"""certify: run the lens laws over a caller-supplied corpus, record a
certificate, and (on pass) grant the wrapper its declared attrs.

Laws (contracts.Wrapper docstring):
  GetPut  put(get(v), e, v) proposes no changes and no refusals.
  PutGet  for base v1, target v2: apply(v1, put(get(v2), e, v1)) agrees
          with v2 on every declared attr.

Corpus is a caller-supplied iterable of EntityView dicts — certify never
invents views itself.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .code_hash import code_hash_for_wrapper
from .contracts import AttrSpec, Change, Wrapper
from .grant import grant
from .registry import RegistryError

_LENS_ENTITY = "lens-check"


def apply(view: Mapping[str, Any], changes: Iterable[Change],
          many: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Apply proposed changes to an entity view. `many` names the attrs whose
    value is a set of values (cardinality 'many'); a list under a 'one' attr
    (e.g. json) is a single value. Local to certify for now — promote to
    contracts if wrappers need it."""
    out = dict(view)
    for c in changes:
        cur = out.get(c.a)
        if c.a in many:
            vals = list(cur) if isinstance(cur, (tuple, list)) else ([] if cur is None else [cur])
            if c.added:
                if c.v not in vals:
                    vals.append(c.v)
            else:
                vals = [x for x in vals if x != c.v]
            if vals:
                out[c.a] = tuple(vals)
            else:
                out.pop(c.a, None)
        else:
            if c.added:
                out[c.a] = c.v
            elif cur == c.v:
                out.pop(c.a, None)
    return out


@dataclass(frozen=True)
class LensReport:
    wrapper: str
    passed: bool
    attrs_checked: tuple[str, ...]
    failures: tuple[str, ...]


def _declared(w: Wrapper) -> list[str]:
    return [a.name for a in w.attrs()]


def check_lens(w: Wrapper, corpus: Iterable[Mapping[str, Any]]) -> LensReport:
    views = [dict(v) for v in corpus]
    attrs = _declared(w)
    failures: list[str] = []

    for i, v in enumerate(views):
        r = w.get(_LENS_ENTITY, v)
        res = w.put(r, _LENS_ENTITY, v)
        if res.changes or res.refusals:
            failures.append(
                f"GetPut[{i}]: put(get(v)) proposed {len(res.changes)} changes, "
                f"{len(res.refusals)} refusals"
            )

    for a in attrs:
        for i, target in enumerate(views):
            base = views[i - 1]
            if a not in target and a not in base:
                continue
            r = w.get(_LENS_ENTITY, target)
            res = w.put(r, _LENS_ENTITY, base)
            if res.refusals:
                failures.append(f"PutGet[{a}][{i}]: put refused: {res.refusals[0].reason}")
                continue
            nxt = apply(base, res.changes, many={s.name for s in w.attrs() if s.cardinality == "many"})
            if nxt.get(a) != target.get(a):
                failures.append(
                    f"PutGet[{a}][{i}]: expected {target.get(a)!r}, got {nxt.get(a)!r}"
                )

    return LensReport(
        wrapper=w.id,
        passed=not failures,
        attrs_checked=tuple(attrs),
        failures=tuple(failures[:20]),
    )


def register_wrapper(conn: sqlite3.Connection, w: Wrapper) -> None:
    """Insert the wrapper row and its declared attr vocabulary.

    Re-declaring the same id or attr with a different spec is a loud collision."""
    impl = f"{type(w).__module__}.{type(w).__qualname__}"
    row = conn.execute(
        "SELECT namespace, impl_ref FROM wrapper WHERE id = ?", (w.id,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO wrapper (id, namespace, impl_ref) VALUES (?, ?, ?)",
            (w.id, w.namespace, impl),
        )
    elif row != (w.namespace, impl):
        raise RegistryError(
            f"wrapper id collision: {w.id!r} already registered as {row!r}"
        )
    for spec in w.attrs():
        existing = conn.execute(
            "SELECT value_type, cardinality, doc FROM attr WHERE name = ?",
            (spec.name,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO attr (name, value_type, cardinality, doc) VALUES (?, ?, ?, ?)",
                (spec.name, spec.value_type, spec.cardinality, spec.doc),
            )
        elif (existing[0], existing[1]) != (spec.value_type, spec.cardinality):
            raise RegistryError(
                f"attr collision: {spec.name!r} already registered as {existing!r}"
            )
        elif existing[2] and spec.doc and existing[2] != spec.doc:
            raise RegistryError(
                f"attr collision: {spec.name!r} doc mismatch {existing[2]!r} vs {spec.doc!r}"
            )


def certify(conn: sqlite3.Connection, w: Wrapper, corpus: Iterable[Mapping[str, Any]],
            *, tier: str = "witness") -> int:
    """Run check_lens, register the wrapper + its attrs, write a certificate row.
    Returns the certificate id. Corpus is materialized once for the n= label."""
    views = list(corpus)
    register_wrapper(conn, w)
    report = check_lens(w, views)
    digest = code_hash_for_wrapper(w)
    return conn.execute(
        "INSERT INTO certificate (tier, subject, ref, corpus, result, code_hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tier, f"wrapper:{w.id}", "check_lens", f"n={len(views)}",
         "pass" if report.passed else "fail", digest),
    ).lastrowid


def grant_roundtrip(conn: sqlite3.Connection, w: Wrapper, cert_id: int) -> list[str]:
    """Grant every attr the wrapper declares, backed by cert_id."""
    granted = []
    for spec in w.attrs():
        grant(conn, w.id, spec.name, cert_id)
        granted.append(spec.name)
    return granted
