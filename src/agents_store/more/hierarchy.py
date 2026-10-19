"""Hierarchy and the one_question lint (more-lean-model.md §10, kernel
hierarchy). Fachgebiet -> Anwendungsfall -> BP|CM|UI|API|TC|AC|DEC; each
level declares one question in the profile, each node answers its own
level's question and no other.

A node's content is authored as sections keyed by the level whose
question they answer. That makes the lint mechanical, with no guessing
from prose:
- node_answers_none: the own-level section is missing, empty or a
  placeholder.
- node_answers_multiple: a non-empty section for another level, or a
  heading inside the own answer that names another level (alias or its
  question text). Fix: split, then point.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .profile import Profile, load_profile

NODE_ANSWERS_NONE = "node_answers_none"
NODE_ANSWERS_MULTIPLE = "node_answers_multiple"
# implementation ids for structural rules the kernel states without naming
LEVEL_UNKNOWN = "level_unknown"
PARENT_INVALID = "hierarchy_parent_invalid"
LEVEL_QUESTION_MISSING = "level_question_missing"


@dataclass(frozen=True)
class Node:
    id: str
    level: str
    parent: str | None = None
    sections: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    id: str
    node: str | None
    detail: str


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.casefold()).strip()


def _headings(text: str) -> Iterable[str]:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            yield s.lstrip("#").strip()
        elif s.endswith(":") and 0 < len(s) <= 60:
            yield s[:-1].strip()
        elif s.endswith("?") and len(s) <= 120:
            yield s


def _level_of_heading(h: str, profile: Profile) -> str | None:
    n = _norm(h)
    if not n:
        return None
    aliases = profile.setting("level_aliases")
    for lvl in profile.levels:
        q = profile.questions.get(lvl)
        texts = [q.en, q.de] if q else []
        if any(t and _norm(t) == n for t in texts):
            return lvl
        for a in aliases.get(lvl, ()):
            a = _norm(a)
            if n == a or n.startswith(a + " "):
                return lvl
    return None


def _placeholder(text: str | None, profile: Profile) -> bool:
    if text is None:
        return True
    return _norm(text) in {_norm(p) for p in profile.setting("placeholders")}


def lint_profile(profile: Profile | None = None) -> list[Finding]:
    """Each level declares exactly one, non-empty question."""
    profile = profile or load_profile()
    out = []
    for lvl in profile.levels:
        q = profile.questions.get(lvl)
        if q is None or not q.en.strip():
            out.append(Finding(LEVEL_QUESTION_MISSING, None, f"level {lvl} declares no question"))
    for lvl in profile.questions:
        if lvl not in profile.levels:
            out.append(Finding(LEVEL_UNKNOWN, None, f"question declared for unknown level {lvl}"))
    return out


def lint(nodes: Iterable[Node], profile: Profile | None = None) -> list[Finding]:
    profile = profile or load_profile()
    nodes = list(nodes)
    by_id = {n.id: n for n in nodes}
    out: list[Finding] = []
    for n in nodes:
        if n.level not in profile.levels:
            out.append(Finding(LEVEL_UNKNOWN, n.id, f"level {n.level!r} not in {profile.levels}"))
            continue
        want = profile.parent.get(n.level)
        if want is None:
            if n.parent is not None:
                out.append(Finding(PARENT_INVALID, n.id, f"{n.level} is a root level and has no parent"))
        else:
            p = by_id.get(n.parent) if n.parent else None
            if p is None:
                out.append(Finding(PARENT_INVALID, n.id, f"{n.level} needs a {want} parent; {n.parent!r} not found"))
            elif p.level != want:
                out.append(Finding(PARENT_INVALID, n.id, f"{n.level} parent must be {want}, is {p.level}"))

        q = profile.questions[n.level]
        own = n.sections.get(n.level)
        if _placeholder(own, profile):
            out.append(Finding(NODE_ANSWERS_NONE, n.id, f"no answer to {n.level}: {q.en!r}"))
        for lvl, text in n.sections.items():
            if lvl == n.level or _placeholder(text, profile):
                continue
            target = lvl if lvl in profile.levels else "unknown level"
            out.append(Finding(NODE_ANSWERS_MULTIPLE, n.id,
                               f"{n.level} node carries a {target} answer; split it into a {target} node and point to it"))
        for h in _headings(own or ""):
            lvl = _level_of_heading(h, profile)
            if lvl and lvl != n.level:
                out.append(Finding(NODE_ANSWERS_MULTIPLE, n.id,
                                   f"{n.level} answer contains a {lvl} section ({h!r}); split it into a {lvl} node and point to it"))
    return out
