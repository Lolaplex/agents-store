"""Wrapper 'ical': entity <-> one iCalendar component (VEVENT or VTODO).

Declared mapping (the round-trip set certification covers):
    title  <-> SUMMARY        when <-> DTSTART
    status <-> VTODO STATUS   end  <-> DTEND (VEVENT) / DUE (VTODO)
    UID = entity id (never minted from content)

Shape rules:
- VTODO iff `status` present (both when+status -> VTODO; a task is more
  specific than an event). VEVENT iff `when` present and no `status`.
- UTC Z times only: TZID / floating -> refusal 'tz-unsupported'.
- STATUS values map open<->NEEDS-ACTION, done<->COMPLETED; anything else
  in -> 'status-map' refusal.
- Every prop we don't map is preserved verbatim in `ical:extra` (a JSON
  list of raw lines) and re-emitted — lossless, never silently dropped.
- Exactly one VEVENT/VTODO per representation; else 'parse-fail'.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from ..contracts import AttrSpec, Change, PutResult, Refusal

_STATUS_TO_ICAL = {"open": "NEEDS-ACTION", "done": "COMPLETED"}
_STATUS_FROM_ICAL = {v: k for k, v in _STATUS_TO_ICAL.items()}
_MAPPED = {"UID", "SUMMARY", "DTSTART", "DTEND", "DUE", "STATUS"}
_VERSION = "VERSION:2.0"
_PRODID = "PRODID:-//agents-store//EN"


def _esc(s: Any) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _unesc(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _to_ical_dt(v: Any) -> str:
    return str(v).replace("-", "").replace(":", "").replace(" ", "T").rstrip("Z") + "Z"


def _from_ical_dt(v: str) -> str | None:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", v.strip())
    if not m:
        return None
    return f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}Z"


def _fold(line: str) -> list[str]:
    out, cur = [], line
    while len(cur.encode()) > 75:
        cut = cur[:75]
        out.append(cut)
        cur = " " + cur[75:]
    out.append(cur)
    return out


class ICalWrapper:
    id = "ical"
    namespace = "ical"

    def attrs(self):
        return [
            AttrSpec("title", "text"),
            AttrSpec("status", "text"),
            AttrSpec("when", "instant"),
            AttrSpec("end", "instant"),
            AttrSpec("ical:extra", "json", doc="unmapped props, raw lines"),
            AttrSpec("ical:href", "text", doc="CalDAV resource name (adapter-owned)"),
            AttrSpec("ical:client-uid", "text", doc="UID as first PUT by client (adapter-owned)"),
        ]

    def get(self, e: str, view: Mapping[str, Any]) -> str:
        is_todo = "status" in view and view.get("status") is not None
        comp = "VTODO" if is_todo else "VEVENT"
        lines = ["BEGIN:VCALENDAR", _VERSION, _PRODID, f"BEGIN:{comp}", f"UID:{e}"]
        if view.get("title") is not None:
            lines.append(f"SUMMARY:{_esc(view['title'])}")
        if view.get("when") is not None:
            lines.append(f"DTSTART:{_to_ical_dt(view['when'])}")
        if view.get("end") is not None:
            lines.append(("DUE:" if is_todo else "DTEND:") + _to_ical_dt(view["end"]))
        if is_todo:
            lines.append(f"STATUS:{_STATUS_TO_ICAL.get(view['status'], view['status'])}")
        extra = view.get("ical:extra")
        if isinstance(extra, (list, tuple)):
            for ln in extra:
                name = ln.split(":", 1)[0].split(";", 1)[0]
                if name.upper() not in _MAPPED and name.upper() not in ("BEGIN", "END"):
                    lines.append(str(ln))
        lines += [f"END:{comp}", "END:VCALENDAR"]
        return "\r\n".join(x for ln in lines for x in _fold(ln)) + "\r\n"

    # ---- put -----------------------------------------------------------

    def put(self, rep: str, e: str | None, view: Mapping[str, Any] | None) -> PutResult:
        try:
            comp, props, extra = _parse(rep)
        except _ParseFail as f:
            return PutResult(refusals=(Refusal("ical", "parse-fail", e=e, payload=str(f)),))
        uid = props["UID"][1] if "UID" in props else None
        if e is not None and uid is not None and uid != e:
            return PutResult(refusals=(
                Refusal("ical", "uid-mismatch", e=e, payload=f"UID {uid} != {e}"),))
        te = e or uid
        # timezone law: only Z times
        for name in ("DTSTART", "DTEND", "DUE"):
            if name in props:
                pname, pval = props[name]
                if "TZID" in pname or not pval.strip().endswith("Z"):
                    return PutResult(refusals=(
                        Refusal("ical", "tz-unsupported", e=te, a="when", payload=pval),))
        if "STATUS" in props and props["STATUS"][1] not in _STATUS_FROM_ICAL:
            return PutResult(refusals=(
                Refusal("ical", "status-map", e=te, a="status", payload=props["STATUS"][1]),))

        v = view or {}
        changes: list[Change] = []

        def diff(attr: str, new: str | None) -> None:
            cur = v.get(attr)
            if new is None and cur is not None:
                changes.append(Change(e=te, a=attr, v=cur, added=False))
            elif new is not None and new != cur:
                changes.append(Change(e=te, a=attr, v=new))

        diff("title", _unesc(props["SUMMARY"][1]) if "SUMMARY" in props else None)
        diff("when", _from_ical_dt(props["DTSTART"][1]) if "DTSTART" in props else None)
        end_key = "DUE" if comp == "VTODO" else "DTEND"
        diff("end", _from_ical_dt(props[end_key][1]) if end_key in props else None)
        if comp == "VTODO":
            diff("status", _STATUS_FROM_ICAL[props["STATUS"][1]] if "STATUS" in props else None)
        else:
            # VEVENT has no task state: a VEVENT for a task entity means
            # "make it an event" -> propose retracting status.
            diff("status", None)
        cur_extra = v.get("ical:extra") or []
        if extra != list(cur_extra):
            if extra:
                changes.append(Change(e=te, a="ical:extra", v=extra))
            elif "ical:extra" in v:
                changes.append(Change(e=te, a="ical:extra", v=list(cur_extra), added=False))
        return PutResult(changes=tuple(changes))


class _ParseFail(ValueError):
    pass


def _parse(rep: str) -> tuple[str, dict[str, tuple[str, str]], list[str]]:
    """-> (component, mapped props {NAME:(rawname, value)}, extra raw lines)"""
    unfolded: list[str] = []
    for raw in rep.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += raw[1:]
        elif raw.strip():
            unfolded.append(raw)
    comps = [l for l in unfolded if l.upper() in ("BEGIN:VEVENT", "BEGIN:VTODO")]
    if len(comps) != 1:
        raise _ParseFail(f"expected exactly one VEVENT/VTODO, got {len(comps)}")
    comp = comps[0].split(":", 1)[1].upper()
    props: dict[str, tuple[str, str]] = {}
    extra: list[str] = []
    inside = False
    for ln in unfolded:
        u = ln.upper()
        if u == f"BEGIN:{comp}":
            inside = True
            continue
        if u == f"END:{comp}":
            inside = False
            continue
        if not inside or ":" not in ln:
            continue
        name = ln.split(":", 1)[0]
        base = name.split(";", 1)[0].upper()
        if base in _MAPPED:
            props[base] = (name, ln.split(":", 1)[1])
        else:
            extra.append(ln)
    return comp, props, extra
