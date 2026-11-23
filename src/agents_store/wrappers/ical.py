"""Wrapper 'ical': entity <-> one iCalendar component (VEVENT or VTODO).

Declared mapping (the round-trip set certification covers):
    title  <-> SUMMARY        when <-> DTSTART
    status <-> VTODO STATUS   end  <-> DTEND (VEVENT) / DUE (VTODO)
    UID = entity id (never minted from content)

Shape rules:
- VTODO iff `status` present (both when+status -> VTODO; a task is more
  specific than an event). VEVENT iff `when` present and no `status`.
- Times: canonical `when`/`end` stay UTC instants (`...Z`). On put, a
  UTC value, a `TZID=<IANA zone>` wall time, a floating wall time
  (resolved in the store zone, see `store_zone()`) and an all-day
  `VALUE=DATE` are all accepted and converted to that instant. The form
  the client used is kept in `ical:tz` (`TZID=<zone>`, `floating` or
  `date`) and VTIMEZONE blocks verbatim in `ical:vtimezone`, so get
  renders the same form back. A TZID no zone database knows, a wall time
  the zone skips (spring-forward gap), mixed date/date-time values or an
  unparseable stamp -> refusal 'tz_unsupported'. Fall-back overlaps take
  the first occurrence (iCalendar has no fold bit).
- STATUS values map open<->NEEDS-ACTION, done<->COMPLETED; anything else
  in -> 'status_map' refusal.
- Every prop we don't map is preserved verbatim in `ical:extra` (a JSON
  list of raw lines) and re-emitted — lossless, never silently dropped.
- Exactly one VEVENT/VTODO per representation; else 'parse_fail'.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..contracts import AttrSpec, Change, PutResult, WriteRefusal

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


_UTC = timezone.utc
_WALL = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})")
_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})")


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name.strip().strip('"'))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def store_zone() -> ZoneInfo:
    """Zone for floating wall times: `AGENTS_STORE_TIMEZONE`, then `TZ`,
    then the host zone (`/etc/localtime`), then UTC."""
    for name in (os.environ.get("AGENTS_STORE_TIMEZONE"), os.environ.get("TZ")):
        if name and name.strip():
            z = _zone(name.lstrip(":"))
            if z is not None:
                return z
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            z = _zone(target.split("zoneinfo/", 1)[1])
            if z is not None:
                return z
    except OSError:
        pass
    return ZoneInfo("UTC")


def _iso(dt: datetime) -> str:
    return dt.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(v: Any) -> datetime | None:
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})[T ](\d{2}):?(\d{2}):?(\d{2})Z?",
                     str(v).strip())
    if not m:
        return None
    return datetime(*(int(x) for x in m.groups()), tzinfo=_UTC)


def _localize(wall: datetime, zone: ZoneInfo) -> datetime | None:
    """Wall time in `zone` -> aware datetime; None if the zone skips it."""
    first = wall.replace(tzinfo=zone, fold=0)
    back = first.astimezone(_UTC).astimezone(zone).replace(tzinfo=None)
    return first if back == wall else None


def _tz_form(pname: str) -> tuple[str, str | None]:
    """Property name with params -> ('utc'|'tzid'|'floating'|'date', tzid)."""
    params = {}
    for part in pname.split(";")[1:]:
        if "=" in part:
            k, val = part.split("=", 1)
            params[k.strip().upper()] = val.strip()
    if params.get("VALUE", "").upper() == "DATE":
        return "date", None
    if "TZID" in params:
        return "tzid", params["TZID"].strip('"')
    return "dt", None


def _to_instant(pname: str, pval: str) -> tuple[str | None, str | None]:
    """-> (UTC instant 'YYYY-MM-DDTHH:MM:SSZ', ical:tz form) or (None, None)."""
    kind, tzid = _tz_form(pname)
    raw = pval.strip()
    if kind == "date":
        m = _DATE.fullmatch(raw)
        if not m:
            return None, None
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None, None
        return f"{d.isoformat()}T00:00:00Z", "date"
    if raw.endswith("Z"):
        # UTC wins; a TZID on a UTC value (RFC 5545 forbids it, some
        # writers emit `TZID=UTC:...Z`) carries no extra meaning.
        return _from_ical_dt(raw), None
    m = _WALL.fullmatch(raw)
    if not m:
        return None, None
    try:
        wall = datetime(*(int(x) for x in m.groups()))
    except ValueError:
        return None, None
    if kind == "tzid":
        zone = _zone(tzid or "")
        form = f"TZID={tzid}"
    else:
        zone = store_zone()
        form = "floating"
    if zone is None:
        return None, None
    aware = _localize(wall, zone)
    if aware is None:
        return None, None
    return _iso(aware), form


def _render_dt(name: str, v: Any, form: Any) -> str:
    """One DTSTART/DTEND/DUE line in the form the client used."""
    inst = _parse_instant(v)
    if inst is None or not isinstance(form, str) or not form:
        return f"{name}:{_to_ical_dt(v)}"
    if form == "date":
        return f"{name};VALUE=DATE:{inst.strftime('%Y%m%d')}"
    zone = store_zone() if form == "floating" else (
        _zone(form[5:]) if form.startswith("TZID=") else None)
    if zone is not None:
        wall = inst.astimezone(zone).replace(tzinfo=None)
        # The second pass of a fall-back hour has no wall-time label
        # (iCalendar has no fold bit): keep it exact as UTC.
        if _localize(wall, zone) == inst:
            stamp = wall.strftime("%Y%m%dT%H%M%S")
            return f"{name}:{stamp}" if form == "floating" else f"{name};{form}:{stamp}"
    return f"{name}:{_to_ical_dt(v)}"


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
            AttrSpec("ical:tz", "text",
                     doc="time form the client used: TZID=<zone>, floating or date"),
            AttrSpec("ical:vtimezone", "json", doc="VTIMEZONE blocks, raw lines"),
            AttrSpec("ical:href", "text", doc="CalDAV resource name (adapter-owned)"),
            AttrSpec("ical:client-uid", "text", doc="UID as first PUT by client (adapter-owned)"),
        ]

    def get(self, e: str, view: Mapping[str, Any],
            component: str | None = None) -> str:
        """Render VEVENT or VTODO. `component` pins the shape for a
        surface that only speaks one component (e.g. a calendar
        collection renders members as VEVENT even when the entity is
        also a task — `status` is then out of this projection's terms).
        VEVENT omits STATUS: our open|done enum is VTODO-only."""
        if component is not None:
            comp = component.upper()
            if comp not in ("VEVENT", "VTODO"):
                raise ValueError(f"unsupported component {component!r}")
        else:
            comp = "VTODO" if view.get("status") is not None else "VEVENT"
        is_todo = comp == "VTODO"
        form = view.get("ical:tz")
        lines = ["BEGIN:VCALENDAR", _VERSION, _PRODID]
        vtz = view.get("ical:vtimezone")
        if isinstance(form, str) and form.startswith("TZID=") and isinstance(vtz, (list, tuple)):
            lines += [str(ln) for ln in vtz]
        lines += [f"BEGIN:{comp}", f"UID:{e}"]
        if view.get("title") is not None:
            lines.append(f"SUMMARY:{_esc(view['title'])}")
        if view.get("when") is not None:
            lines.append(_render_dt("DTSTART", view["when"], form))
        if view.get("end") is not None:
            lines.append(_render_dt("DUE" if is_todo else "DTEND", view["end"], form))
        if is_todo and view.get("status") is not None:
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
            comp, props, extra, vtimezone = _parse(rep)
        except _ParseFail as f:
            return PutResult(refusals=(WriteRefusal("ical", "parse_fail", e=e, payload=str(f)),))
        uid = props["UID"][1] if "UID" in props else None
        if e is not None and uid is not None and uid != e:
            return PutResult(refusals=(
                WriteRefusal("ical", "uid_mismatch", e=e, payload=f"UID {uid} != {e}"),))
        te = e or uid
        # timezone law: every time resolves to one UTC instant
        instants: dict[str, str] = {}
        forms: list[str | None] = []
        for name in ("DTSTART", "DTEND", "DUE"):
            if name in props:
                pname, pval = props[name]
                inst, form = _to_instant(pname, pval)
                if inst is None:
                    return PutResult(refusals=(
                        WriteRefusal("ical", "tz_unsupported", e=te, a="when",
                                     payload=f"{pname}:{pval}"),))
                instants[name] = inst
                forms.append(form)
        if ("date" in forms) and any(f != "date" for f in forms):
            return PutResult(refusals=(
                WriteRefusal("ical", "tz_unsupported", e=te, a="when",
                             payload="mixed DATE and DATE-TIME values"),))
        tz_form = forms[0] if forms else None
        if "STATUS" in props and props["STATUS"][1] not in _STATUS_FROM_ICAL:
            return PutResult(refusals=(
                WriteRefusal("ical", "status_map", e=te, a="status", payload=props["STATUS"][1]),))

        v = view or {}
        changes: list[Change] = []

        def diff(attr: str, new: str | None) -> None:
            cur = v.get(attr)
            if new is None and cur is not None:
                changes.append(Change(e=te, a=attr, v=cur, added=False))
            elif new is not None and new != cur:
                changes.append(Change(e=te, a=attr, v=new))

        diff("title", _unesc(props["SUMMARY"][1]) if "SUMMARY" in props else None)
        diff("when", instants.get("DTSTART"))
        end_key = "DUE" if comp == "VTODO" else "DTEND"
        diff("end", instants.get(end_key))
        diff("ical:tz", tz_form)
        keep_vtz = vtimezone if tz_form and tz_form.startswith("TZID=") else []
        cur_vtz = v.get("ical:vtimezone") or []
        if keep_vtz != list(cur_vtz):
            if keep_vtz:
                changes.append(Change(e=te, a="ical:vtimezone", v=keep_vtz))
            elif "ical:vtimezone" in v:
                changes.append(Change(e=te, a="ical:vtimezone", v=list(cur_vtz), added=False))
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


def _parse(rep: str) -> tuple[str, dict[str, tuple[str, str]], list[str], list[str]]:
    """-> (component, mapped props {NAME:(rawname, value)}, extra raw lines,
    VTIMEZONE raw lines)"""
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
    vtimezone: list[str] = []
    inside = False
    in_tz = False
    for ln in unfolded:
        u = ln.upper()
        if u == "BEGIN:VTIMEZONE":
            in_tz = True
        if in_tz:
            vtimezone.append(ln)
            if u == "END:VTIMEZONE":
                in_tz = False
            continue
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
    return comp, props, extra, vtimezone
