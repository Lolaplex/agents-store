"""Wrapper 'md': entity <-> markdown file (frontmatter + body).

Format contract:
    ---
    id: <entity-id>        # the anchor; path is NOT identity
    title: ...
    status: open
    when: 2026-10-12T10:00:00Z
    end: ...
    <any other key>: <value>     # preserved losslessly via md:extra (json)
    ---
    body text...

Rules:
- a file with no `id` proposes e=None (new entity);
- `id` present but != the caller's e -> refusal 'id-mismatch';
- frontmatter must be `key: value` lines inside --- fences; else 'parse-fail';
- `md:path` is owned by the folder adapter, never emitted/parsed here.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from ..contracts import AttrSpec, Change, PutResult, Refusal

CORE_KEYS = ("title", "status", "when", "end")
RESERVED = frozenset({"id", "body", *CORE_KEYS})


class MarkdownWrapper:
    id = "md"
    namespace = "md"

    def attrs(self):
        return [
            AttrSpec("title", "text", doc="human title"),
            AttrSpec("status", "text", doc="task state: open | done"),
            AttrSpec("when", "instant", doc="start instant, UTC ISO-8601 with Z"),
            AttrSpec("end", "instant", doc="end instant, UTC ISO-8601 with Z"),
            AttrSpec("body", "text", doc="long-form text (markdown)"),
            AttrSpec(
                "md:path", "text", "many",
                doc="markdown projection path relative to the folder root",
            ),
            AttrSpec("md:extra", "json", doc="unmapped frontmatter keys, lossless"),
        ]

    # ---- get: view -> text -------------------------------------------

    def get(self, e: str, view: Mapping[str, Any]) -> str:
        lines = ["---", f"id: {e}"]
        for a in CORE_KEYS:
            if a in view and view[a] is not None:
                lines.append(f"{a}: {view[a]}")
        extra = view.get("md:extra")
        if isinstance(extra, dict):
            for k in sorted(extra):
                if k not in RESERVED and ":" not in k:
                    lines.append(f"{k}: {extra[k]}")
        lines += ["---", ""]
        body = str(view.get("body") or "")
        return "\n".join(lines) + body + ("\n" if body else "")

    # ---- put: text -> proposed changes --------------------------------

    def put(self, rep: str, e: str | None, view: Mapping[str, Any] | None) -> PutResult:
        try:
            fm, body = _parse(rep)
        except _ParseFail as f:
            return PutResult(refusals=(Refusal("md", "parse-fail", e=e, payload=str(f)),))
        fid = fm.get("id")
        if e is not None and fid is not None and fid != e:
            return PutResult(refusals=(
                Refusal("md", "id-mismatch", e=e, payload=f"file id {fid} != {e}"),))
        te = e or fid
        v = view or {}
        changes: list[Change] = []
        for a in CORE_KEYS + ("body",):
            new = fm.get(a) if a != "body" else (body or None)
            cur = v.get(a)
            if new is None and cur is not None:
                changes.append(Change(e=te, a=a, v=cur, added=False))
            elif new is not None and new != cur:
                changes.append(Change(e=te, a=a, v=new))
        extra = {k: val for k, val in fm.items() if k not in RESERVED}
        if extra != (v.get("md:extra") or {}):
            if extra:
                changes.append(Change(e=te, a="md:extra", v=extra))
            elif "md:extra" in v:
                changes.append(Change(e=te, a="md:extra", v=v["md:extra"], added=False))
        return PutResult(changes=tuple(changes))

    def peek_id(self, rep: str) -> str | None:
        """Cheap identity probe for adapters: frontmatter `id` or None.
        Raises _ParseFail on malformed frontmatter."""
        fm, _ = _parse(rep)
        return fm.get("id")


class _ParseFail(ValueError):
    pass


def _parse(rep: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body). No leading '---' -> whole text is body."""
    lines = rep.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, rep
    fm: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            rest = lines[i + 1:]
            while rest and not rest[0].strip():
                rest.pop(0)  # skip blank lines between fence and body
            return fm, "\n".join(rest)
        if not line.strip():
            continue
        if ":" not in line:
            raise _ParseFail(f"frontmatter line {i}: {line!r} has no ':'")
        key, _, val = line.partition(":")
        key = key.strip()
        if not key:
            raise _ParseFail(f"frontmatter line {i}: empty key")
        if key == "body":
            raise _ParseFail("'body' must be the file body, not a frontmatter key")
        fm[key] = val.strip()
    raise _ParseFail("unterminated frontmatter (no closing ---)")
