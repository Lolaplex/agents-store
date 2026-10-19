"""The cut-over profile (kernel/Cutover: Model, Profile, Eval, Validate;
kernel-proposal.json layers.profiles.cutover).

Every cut-over event is a MORe event (`classify`, `to_more_log`). Task
statuses, the projection and the reflow are folds over the MORe-live log:
superseded events and decisions by deciders who may not approve do not
count, and no event sets a status. Times are UTC epoch milliseconds.

Fix for the drift clash (Fabian, 2026-10-19; Lean Cutover/Profile.lean):
the baseline inclusion names every task:<id> of the baseline, so task
observations follow an inclusion of their subject (production_evidence);
an authorized approval also emits a supersession of the proposal events,
so the open decision closes. A withdrawn approval does not reopen it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable

from .events import Event

STATUSES = ("planned", "ready", "active", "completed", "blocked", "failed", "skipped", "rollback")
SERVICE = "cutover-service"

KINDS = {
    "baselinePublished": ("revision",),
    "reflowProposed": ("proposal",),
    "reflowApproved": ("reflow", "approver"),
    "corrected": ("old", "replacement"),
    "actualStarted": ("task", "at"),
    "actualFinished": ("task", "at"),
    "blocked": ("task", "reason"),
    "unblocked": ("task",),
    "failed": ("task", "reason"),
    "skipped": ("task", "reason"),
    "rollbackStarted": ("task", "at"),
    "rollbackCompleted": ("task", "at"),
    "gateViolation": ("task", "pred"),
}


@dataclass(frozen=True)
class Interval:
    start: int
    finish: int

    def well_formed(self) -> bool:
        return self.start <= self.finish


@dataclass(frozen=True)
class Task:
    id: int
    dependencies: tuple[int, ...]
    baseline: Interval


@dataclass(frozen=True)
class Baseline:
    revision: int
    tasks: tuple[Task, ...]
    deps: tuple[tuple[int, int], ...]

    def task_ids(self) -> list[int]:
        return [t.id for t in self.tasks]

    def find_task(self, tid: int) -> Task | None:
        return next((t for t in self.tasks if t.id == tid), None)

    def refers(self, tid) -> bool:
        return self.find_task(tid) is not None


@dataclass(frozen=True)
class ForecastEntry:
    task: int
    interval: Interval


@dataclass(frozen=True)
class ReflowProposal:
    id: int
    base_revision: int
    forecast: tuple[ForecastEntry, ...]
    reason: str = ""


@dataclass(frozen=True)
class ReflowPolicy:
    preserve_windows: bool = True
    allow_parallelisation: bool = False


@dataclass(frozen=True)
class CutoverEvent:
    id: int
    kind: str
    revision: int | None = None
    task: int | None = None
    at: int | None = None
    old: int | None = None
    replacement: int | None = None
    proposal: ReflowProposal | None = None
    reflow: int | None = None
    approver: str | None = None
    reason: str | None = None
    pred: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown cut-over event kind {self.kind!r}")
        missing = [f for f in KINDS[self.kind] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.kind} needs {missing}")


@dataclass(frozen=True)
class Authority:
    approvers: tuple[str, ...]

    def can_approve(self, p) -> bool:
        return p in self.approvers


@dataclass(frozen=True)
class EffectiveState:
    baseline: Baseline
    forecast_revision: int
    forecast: list[ForecastEntry]
    actual_starts: list[tuple[int, int]]
    actual_finishes: list[tuple[int, int]]
    blocked: list[int]
    failed: list[int]
    skipped: list[int]
    rollback: list[int]
    statuses: list[tuple[int, str]]
    gate_violations: list[tuple[int, int]]
    conflicting_approvals: bool


@dataclass(frozen=True)
class ReflowResult:
    forecast: list[ForecastEntry]
    affected: list[int]
    conflicts: list[tuple[str, int]]
    violations: list[tuple]


class AdmitError(Exception):
    pass


class ValidateError(Exception):
    pass


def baseline_name(rev: int) -> str:
    return f"cutover-rev@{rev}"


def task_subject(t: int) -> str:
    return f"task:{t}"


def reflow_subject(r: int) -> str:
    return f"reflow:{r}"


_OBSERVE = {
    "actualStarted": ("actual_start", "pass"),
    "actualFinished": ("actual_finish", "pass"),
    "blocked": ("blocked", "deviation"),
    "unblocked": ("unblocked", "pass"),
    "failed": ("failed", "fail"),
    "skipped": ("skipped", "deviation"),
    "rollbackStarted": ("rollback_start", "pass"),
    "rollbackCompleted": ("rollback_complete", "pass"),
    "gateViolation": ("gate_violation", "fail"),
}


def classify(e: CutoverEvent) -> tuple[str, dict, tuple[int, ...]]:
    if e.kind == "baselinePublished":
        return "inclusion", {"into": baseline_name(e.revision)}, ()
    if e.kind == "corrected":
        return "supersession", {}, (e.old,)
    if e.kind == "reflowProposed":
        return "decision", {"status": "open"}, ()
    if e.kind == "reflowApproved":
        return "decision", {"status": "decided", "decided_by": e.approver}, ()
    method, result = _OBSERVE[e.kind]
    return "verification", {"stage": "production", "method": method, "result": result}, ()


def kind_types() -> dict[str, str]:
    p = ReflowProposal(0, 0, ())
    sample = {"revision": 0, "proposal": p, "reflow": 0, "approver": "", "old": 0,
              "replacement": 0, "task": 0, "at": 0, "reason": "", "pred": 0}
    return {k: classify(CutoverEvent(0, k, **{f: sample[f] for f in fs}))[0]
            for k, fs in KINDS.items()}


def subjects_of(b: Baseline, e: CutoverEvent) -> tuple[str, ...]:
    if e.kind == "baselinePublished":
        return ("cutover",) + tuple(task_subject(t.id) for t in b.tasks)
    if e.kind == "corrected":
        return ("cutover",)
    if e.kind == "reflowProposed":
        return (reflow_subject(e.proposal.id),)
    if e.kind == "reflowApproved":
        return (reflow_subject(e.reflow),)
    if e.kind == "gateViolation":
        return (task_subject(e.task), task_subject(e.pred))
    return (task_subject(e.task),)


def at_of(e: CutoverEvent) -> int:
    return e.at if e.kind in ("actualStarted", "actualFinished", "rollbackStarted",
                              "rollbackCompleted") else 0


def actor_of(e: CutoverEvent) -> str:
    return e.approver if e.kind == "reflowApproved" else SERVICE


def pins_of(rev: int, e: CutoverEvent) -> tuple[str, ...]:
    if e.kind == "baselinePublished":
        return (baseline_name(e.revision),)
    if e.kind == "reflowProposed":
        return (baseline_name(e.proposal.base_revision),)
    return (baseline_name(rev),)


def authorized(auth: Authority, e: CutoverEvent) -> bool:
    t, body, _ = classify(e)
    if t == "decision" and body["status"] == "decided":
        return auth.can_approve(body.get("decided_by"))
    return True


def more_id(n: int) -> str:
    return str(2 * n)


def close_id(n: int) -> str:
    return str(2 * n + 1)


def proposal_events(log: Iterable[CutoverEvent], pid: int) -> list[int]:
    return [e.id for e in log if e.kind == "reflowProposed" and e.proposal.id == pid]


def closed_by(auth: Authority, log: list[CutoverEvent], e: CutoverEvent) -> list[int]:
    if e.kind == "reflowApproved" and auth.can_approve(e.approver):
        return proposal_events(log, e.reflow)
    return []


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def to_more(b: Baseline, e: CutoverEvent) -> Event:
    t, body, sup = classify(e)
    return Event(t, actor_of(e), subjects_of(b, e), pins_of(b.revision, e), at=_iso(at_of(e)),
                 supersedes=tuple(more_id(x) for x in sup), body=body, id=more_id(e.id))


def to_more_log(auth: Authority, b: Baseline, log: Iterable[CutoverEvent]) -> list[Event]:
    log = list(log)
    out: list[Event] = []
    for e in log:
        out.append(to_more(b, e))
        ids = closed_by(auth, log, e)
        if ids:
            out.append(Event("supersession", actor_of(e), subjects_of(b, e),
                             pins_of(b.revision, e), at=_iso(at_of(e)),
                             supersedes=tuple(more_id(x) for x in ids), id=close_id(e.id)))
    return [replace(ev, seq=i) for i, ev in enumerate(out)]


def event_well_formed(b: Baseline, log: list[CutoverEvent], e: CutoverEvent) -> bool:
    ids = [x.id for x in log]
    k = e.kind
    if k == "baselinePublished":
        return e.revision == b.revision
    if k == "corrected":
        return e.old in ids and e.replacement in ids and e.old != e.replacement
    if k == "reflowProposed":
        p = e.proposal
        return p.base_revision == b.revision and all(
            b.refers(fe.task) and fe.interval.well_formed() for fe in p.forecast)
    if k == "reflowApproved":
        return True
    if k == "gateViolation":
        return b.refers(e.task) and b.refers(e.pred)
    return b.refers(e.task)


def log_well_formed(b: Baseline, log: list[CutoverEvent]) -> bool:
    ids = [e.id for e in log]
    return len(ids) == len(set(ids)) and all(event_well_formed(b, log, e) for e in log)


def superseded_ids(auth: Authority, log: list[CutoverEvent]) -> list[int]:
    out: list[int] = []
    for e in log:
        out += list(classify(e)[2]) + closed_by(auth, log, e)
    return out


def sort_by_id(log: Iterable[CutoverEvent]) -> list[CutoverEvent]:
    return sorted(log, key=lambda e: e.id)


def live_events(auth: Authority, ordered: list[CutoverEvent]) -> list[CutoverEvent]:
    sup = set(superseded_ids(auth, ordered))
    return [e for e in ordered if e.id not in sup and authorized(auth, e)]


def effective_payload(auth: Authority, log) -> list[CutoverEvent]:
    return live_events(auth, sort_by_id(log))


def find_proposal(log, pid: int) -> ReflowProposal | None:
    return next((e.proposal for e in log if e.kind == "reflowProposed" and e.proposal.id == pid), None)


def select_approved(auth: Authority, live: list[CutoverEvent]) -> tuple[int | None, bool]:
    ids = list(dict.fromkeys(e.reflow for e in live
                             if e.kind == "reflowApproved" and auth.can_approve(e.approver)))
    if not ids:
        return None, False
    if len(ids) == 1:
        return ids[0], False
    return None, True


def baseline_forecast(b: Baseline) -> list[ForecastEntry]:
    return [ForecastEntry(t.id, t.baseline) for t in b.tasks]


def lookup_forecast(f, tid) -> Interval | None:
    return next((fe.interval for fe in f if fe.task == tid), None)


def _latest(payload, kind) -> list[tuple[int, int]]:
    acc: list[tuple[int, int]] = []
    for e in payload:
        if e.kind == kind:
            acc = [x for x in acc if x[0] != e.task] + [(e.task, e.at)]
    return acc


def _flag(payload, on: str, off: str | None = None) -> list[int]:
    acc: list[int] = []
    for e in payload:
        if off is not None and e.kind == off:
            acc = [x for x in acc if x != e.task]
        elif e.kind == on and e.task not in acc:
            acc.append(e.task)
    return acc


def derive_status(t: Task, starts, finishes, blocked, failed, skipped, rollback) -> str:
    if t.id in rollback:
        return "rollback"
    if t.id in failed:
        return "failed"
    if t.id in skipped:
        return "skipped"
    if t.id in blocked:
        return "blocked"
    if any(x[0] == t.id for x in finishes):
        return "completed"
    if any(x[0] == t.id for x in starts):
        return "active"
    if all(any(x[0] == d for x in finishes) or d in skipped for d in t.dependencies):
        return "ready"
    return "planned"


def project(auth: Authority, b: Baseline, log) -> EffectiveState:
    log = list(log)
    ordered = sort_by_id(log)
    live = live_events(auth, ordered)
    approved, conflicting = select_approved(auth, live)
    prop = find_proposal(ordered, approved) if approved is not None and not conflicting else None
    rev, forecast = (approved, list(prop.forecast)) if prop else (b.revision, baseline_forecast(b))
    starts, finishes = _latest(live, "actualStarted"), _latest(live, "actualFinished")
    blocked, failed, skipped = _flag(live, "blocked", "unblocked"), _flag(live, "failed"), _flag(live, "skipped")
    rollback: list[int] = []
    for e in live:
        if e.kind == "rollbackStarted" and e.task not in rollback:
            rollback.append(e.task)
        elif e.kind == "rollbackCompleted":
            rollback = [x for x in rollback if x != e.task]
    statuses = [(t.id, derive_status(t, starts, finishes, blocked, failed, skipped, rollback))
                for t in b.tasks]
    gates = [(e.task, e.pred) for e in live if e.kind == "gateViolation"]
    return EffectiveState(b, rev, forecast, starts, finishes, blocked, failed, skipped,
                          rollback, statuses, gates, conflicting)


def _peel(remaining: list[Task]) -> tuple[list[Task], list[Task]]:
    ids = [t.id for t in remaining]
    ready = [t for t in remaining if all(d not in ids for d in t.dependencies)]
    rest = [t for t in remaining if all(r.id != t.id for r in ready)]
    return ready, rest


def topo_layers(tasks: list[Task]) -> tuple[list[Task], list[tuple[str, int]]]:
    out: list[Task] = []
    tasks = list(tasks)
    for _ in range(len(tasks) + 1):
        if not tasks:
            return out, []
        ready, rest = _peel(tasks)
        if not ready:
            return out, [("cycle", t.id) for t in rest]
        out += ready
        tasks = rest
    return out, [("cycle", t.id) for t in tasks]


def reflow(b: Baseline, finishes: list[tuple[int, int]], now: int,
           starts: list[tuple[int, int]], policy: ReflowPolicy = ReflowPolicy()) -> ReflowResult:
    layers, conflicts = topo_layers(list(b.tasks))
    ids = b.task_ids()
    missing = []
    for p, s in b.deps:
        if p not in ids:
            missing.append(("missing_task", p))
        elif s not in ids:
            missing.append(("missing_task", s))
    started = {x[0] for x in starts}
    fin = dict(finishes)
    forecast: list[ForecastEntry] = []
    viol: list[tuple] = []
    for t in layers:
        if t.id in started:
            forecast.append(ForecastEntry(t.id, t.baseline))
            continue
        ends = []
        for d in t.dependencies:
            if d in fin:
                ends.append(fin[d])
            elif (iv := lookup_forecast(forecast, d)) is not None:
                ends.append(iv.finish)
            elif (dt := b.find_task(d)) is not None:
                ends.append(dt.baseline.finish)
        s = max(max(ends, default=now), now, t.baseline.start)
        iv = Interval(s, s + (t.baseline.finish - t.baseline.start))
        if not iv.well_formed():
            viol.append(("non_positive_duration", t.id))
        for d in t.dependencies:
            if d in fin:
                if not fin[d] <= s:
                    viol.append(("dep_order", d, t.id))
            elif (div := lookup_forecast(forecast, d)) is not None and not div.finish <= s:
                viol.append(("dep_order", d, t.id))
        forecast.append(ForecastEntry(t.id, iv))
    affected = [fe.task for fe in forecast
                if (bt := b.find_task(fe.task)) is None or fe.interval != bt.baseline]
    return ReflowResult(forecast, affected, conflicts + missing, viol)


def schedule_invariants(b: Baseline, f) -> bool:
    ok = all(b.refers(fe.task) and fe.interval.well_formed() for fe in f)
    for p, s in b.deps:
        pi, si = lookup_forecast(f, p), lookup_forecast(f, s)
        if pi is not None and si is not None and not pi.finish <= si.start:
            ok = False
    return ok


def admit_event(auth: Authority, b: Baseline, log: list[CutoverEvent], e: CutoverEvent) -> list[CutoverEvent]:
    if any(x.id == e.id for x in log):
        raise AdmitError("duplicate_id")
    if not event_well_formed(b, list(log) + [e], e):
        raise AdmitError("ill_formed_event")
    if e.kind == "reflowApproved" and not auth.can_approve(e.approver):
        raise AdmitError("unknown_approver")
    return list(log) + [e]


def validate(auth: Authority, b: Baseline, log) -> EffectiveState:
    log = list(log)
    if not log_well_formed(b, log):
        raise ValidateError("ill_formed_log")
    st = project(auth, b, log)
    if st.conflicting_approvals:
        raise ValidateError("conflicting_approvals")
    return st


def run_reflow(auth: Authority, b: Baseline, log, policy: ReflowPolicy, now: int) -> ReflowResult:
    st = validate(auth, b, log)
    return reflow(b, st.actual_finishes, now, st.actual_starts, policy)
