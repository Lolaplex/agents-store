"""Wrapper 'jcal': entity <-> one jsoncal item (JSON object text).

Format contract (the source speaks its own vocabulary — no core attrs
are produced here; alignment lives in `correspondence` rows):

    {"uid": "abc-1", "summary": "Dentist",
     "dtstart": "2026-12-01T10:00:00Z", "dtend": "2026-12-01T11:00:00Z",
     "status": "confirmed", <any other key>: <value>}

Rules:
- `uid` is provenance (`jcal:uid`), never identity — entity ids are minted;
  a changed `uid` is an ordinary revision (the adapter's `_by_uid`
  resolution is what keeps uid->entity alignment);
- non-object JSON / unparseable input -> refusal 'parse_fail';
- `dtstart`/`dtend` must be ISO-8601 with 'Z' -> else 'tz_unsupported';
- unmapped keys round-trip losslessly via `jcal:extra` (json);
- `jcal:path` is owned by the jsonfile adapter, never emitted/parsed here.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from ..contracts import AttrSpec, Change, PutResult, Refusal

_KEYS = ("uid", "summary", "dtstart", "dtend", "status")
_KEY_TO_ATTR = {
    "summary": "jcal:summary",
    "dtstart": "jcal:dtstart",
    "dtend": "jcal:dtend",
    "status": "jcal:status",
}
_INSTANT_KEYS = ("dtstart", "dtend")


class JsoncalWrapper:
    id = "jcal"
    namespace = "jcal"

    def attrs(self):
        return [
            AttrSpec("jcal:uid", "text",
                     doc="source-local item id (provenance, not identity)"),
            AttrSpec("jcal:summary", "text", doc="item summary"),
            AttrSpec("jcal:dtstart", "instant",
                     doc="start instant, UTC ISO-8601 with Z"),
            AttrSpec("jcal:dtend", "instant",
                     doc="end instant, UTC ISO-8601 with Z"),
            AttrSpec("jcal:status", "text",
                     doc="source status vocabulary (free text)"),
            AttrSpec("jcal:extra", "json", doc="unmapped keys, lossless"),
            AttrSpec("jcal:path", "text", "many",
                     doc="export file membership 'path#uid' (adapter-owned)"),
            AttrSpec("jcal:rev", "text", "many",
                     doc="last-emitted item hash '<slot> <sha256>' "
                         "(adapter-owned)"),
        ]

    # ---- get: view -> text -------------------------------------------

    def get(self, e: str, view: Mapping[str, Any]) -> str:
        item: dict[str, Any] = {"uid": view.get("jcal:uid") or e}
        for key in _KEYS[1:]:
            a = _KEY_TO_ATTR[key]
            if view.get(a) is not None:
                item[key] = view[a]
        extra = view.get("jcal:extra")
        if isinstance(extra, dict):
            for k in sorted(extra):
                if k not in _KEYS:
                    item[k] = extra[k]
        return json.dumps(item, indent=2, sort_keys=True) + "\n"

    # ---- put: text -> proposed changes --------------------------------

    def put(self, rep: str, e: str | None, view: Mapping[str, Any] | None) -> PutResult:
        try:
            item = json.loads(rep)
        except ValueError as f:
            return PutResult(refusals=(Refusal("jcal", "parse_fail", e=e, payload=str(f)),))
        if not isinstance(item, dict):
            return PutResult(refusals=(
                Refusal("jcal", "parse_fail", e=e, payload="item is not a JSON object"),))
        v = view or {}
        uid = item.get("uid")
        cur_uid = v.get("jcal:uid")
        for key in _INSTANT_KEYS:
            val = item.get(key)
            if val is not None and not _is_utc_instant(val):
                return PutResult(refusals=(
                    Refusal("jcal", "tz_unsupported", e=e, a=_KEY_TO_ATTR[key],
                            payload=str(val)),))

        changes: list[Change] = []

        def diff(attr: str, new: Any) -> None:
            cur = v.get(attr)
            if new is None and cur is not None:
                changes.append(Change(e=e, a=attr, v=cur, added=False))
            elif new is not None and new != cur:
                changes.append(Change(e=e, a=attr, v=new))

        for key in _KEYS[1:]:
            diff(_KEY_TO_ATTR[key], item.get(key))
        if uid is not None and uid != cur_uid:
            changes.append(Change(e=e, a="jcal:uid", v=uid))
        extra = {k: val for k, val in item.items() if k not in _KEYS}
        if extra != (v.get("jcal:extra") or {}):
            if extra:
                changes.append(Change(e=e, a="jcal:extra", v=extra))
            elif "jcal:extra" in v:
                changes.append(Change(e=e, a="jcal:extra", v=v["jcal:extra"], added=False))
        return PutResult(changes=tuple(changes))


def _is_utc_instant(v: Any) -> bool:
    if not isinstance(v, str) or not v.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(v[:-1] + "+00:00")
    except ValueError:
        return False
    return True
