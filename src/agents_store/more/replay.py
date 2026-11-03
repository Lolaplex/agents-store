"""Replay harness: load JSON fixtures and project the world model (Lean reference)."""
from __future__ import annotations

import json
from collections.abc import Mapping as ABCMapping
from datetime import datetime, timezone
from importlib.resources import files as _pkg_files
from pathlib import Path
from typing import Any, Callable

from .compliance import RegulationRequirement, Subject
from .events import Event
from .hierarchy import Node
from .profile import Profile, load_profile
from .relations import (
    POINTER_SUSPECT,
    POINTER_UNPINNED,
    REFINES_LEVEL_INVALID,
    REFINES_MEANING_MISSING,
    REFINES_PAIR_NOT_IN_PROFILE,
    Pointer,
    relation_check,
)
from .world_model import (
    OPEN_ITEM_REASONS,
    ComplianceGapRef,
    SignalEntry,
    SubjectKind,
    TypedOpenItem,
    WorldInputs,
    project_world,
)

_CONTRACT = Path(_pkg_files("agents_store.more").joinpath("replay_contract"))
FIXTURES_DIR = _CONTRACT / "fixtures"
INVALID_DIR = _CONTRACT / "invalid"
MCDC_PATH = _CONTRACT / "mcdc.json"

FIXTURE_KEYS = frozenset(
    {"name", "events", "world_inputs", "expected_open_items", "expected_relation_violations"}
)
WORLD_INPUT_KEYS = frozenset(
    {
        "pointers",
        "nodes",
        "subjects",
        "signals",
        "open_challenges",
        "regulation_requirements",
        "matrix_subjects",
    }
)
EVENT_KEYS = frozenset(
    {
        "id",
        "type",
        "actor",
        "at_ms",
        "subjects",
        "pinned_against",
        "supersedes",
        "body",
        "reason",
        "signals",
        "provenance",
    }
)
POINTER_KEYS = frozenset({"id", "source", "target", "type", "preserves"})
NODE_KEYS = frozenset({"id", "level", "parent", "sections"})
SUBJECT_KIND_KEYS = frozenset({"ref", "board_kind"})
SIGNAL_KEYS = frozenset({"type", "subject", "at_ms"})
REGULATION_REQ_KEYS = frozenset({"ref", "regulation", "duty_id", "duty_version"})
MATRIX_SUBJECT_KEYS = frozenset({"ref", "level"})
EXPECTED_KEYS = frozenset({"board_kind", "subject", "reason", "detail", "compliance"})
COMPLIANCE_REF_KEYS = frozenset({"regulation", "duty", "duty_version", "event_type"})
PIN_KEYS = frozenset({"ref", "baseline", "floating"})


class ReplayError(ValueError):
    pass


def _ms_to_at(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _check_keys(obj: ABCMapping[str, Any], allowed: frozenset[str], ctx: str) -> None:
    unknown = set(obj.keys()) - allowed
    if unknown:
        raise ReplayError(f"{ctx}: unknown keys {sorted(unknown)}")


def _require_array(obj: ABCMapping[str, Any], key: str, ctx: str) -> list:
    if key not in obj:
        raise ReplayError(f"{ctx}: missing required array {key!r}")
    val = obj[key]
    if not isinstance(val, list):
        raise ReplayError(f"{ctx}: {key!r} must be an array")
    return val


def _parse_pin(raw: Any, ctx: str) -> str:
    if not isinstance(raw, ABCMapping):
        raise ReplayError(f"{ctx}: pin must be an object")
    _check_keys(raw, PIN_KEYS, ctx)
    keys = [k for k in PIN_KEYS if k in raw]
    if len(keys) != 1:
        raise ReplayError(f"{ctx}: pin needs exactly one of ref, baseline, floating")
    k = keys[0]
    val = str(raw[k])
    if k == "ref":
        return val
    if k == "baseline":
        return val
    return val if k == "floating" else val


def pin_to_envelope(raw: Any, ctx: str) -> str:
    if not isinstance(raw, ABCMapping):
        raise ReplayError(f"{ctx}: pin must be an object")
    if "ref" in raw:
        return str(raw["ref"])
    if "baseline" in raw:
        return str(raw["baseline"])
    if "floating" in raw:
        return str(raw["floating"])
    raise ReplayError(f"{ctx}: pin needs exactly one of ref, baseline, floating")


def _parse_event(raw: ABCMapping[str, Any], ctx: str, seq: int) -> Event:
    _check_keys(raw, EVENT_KEYS, ctx)
    if "type" not in raw or "actor" not in raw or "id" not in raw:
        raise ReplayError(f"{ctx}: event needs id, type, actor")
    body = dict(raw.get("body") or {})
    if not isinstance(body, dict):
        raise ReplayError(f"{ctx}: body must be an object")
    at_ms = raw.get("at_ms")
    if at_ms is None:
        at = _ms_to_at(seq * 1000)
    else:
        if not isinstance(at_ms, int):
            raise ReplayError(f"{ctx}: at_ms must be an integer")
        at = _ms_to_at(at_ms)
    pins_raw = raw.get("pinned_against")
    if pins_raw is None:
        pins: list[str] = []
    elif not isinstance(pins_raw, list):
        raise ReplayError(f"{ctx}: pinned_against must be an array")
    else:
        pins = [pin_to_envelope(p, f"{ctx}.pinned_against[{i}]") for i, p in enumerate(pins_raw)]
    subjects = raw.get("subjects")
    if subjects is None or not isinstance(subjects, list):
        raise ReplayError(f"{ctx}: subjects must be an array")
    env = {
        "type": raw["type"],
        "actor": raw["actor"],
        "at": at,
        "subjects": subjects,
        "pinned_against": pins,
        "reason": raw.get("reason"),
        "supersedes": raw.get("supersedes") if isinstance(raw.get("supersedes"), list) else [],
        "signals": raw.get("signals") if isinstance(raw.get("signals"), list) else [],
        "provenance": raw.get("provenance"),
        "body": body,
    }
    return Event.from_envelope(env, id=str(raw["id"]), seq=seq)


def _parse_pointer(raw: ABCMapping[str, Any], ctx: str) -> Pointer:
    _check_keys(raw, POINTER_KEYS, ctx)
    preserves = raw.get("preserves")
    if preserves is None:
        pres: tuple[tuple[str, str], ...] = ()
    elif not isinstance(preserves, list):
        raise ReplayError(f"{ctx}: preserves must be an array")
    else:
        pres = tuple((str(p[0]), str(p[1])) for p in preserves)
    return Pointer(str(raw["id"]), str(raw["source"]), str(raw["target"]), str(raw["type"]), pres)


def _parse_node(raw: ABCMapping[str, Any], ctx: str) -> Node:
    _check_keys(raw, NODE_KEYS, ctx)
    sections = raw.get("sections")
    if sections is None:
        sec = {}
    elif not isinstance(sections, dict):
        raise ReplayError(f"{ctx}: sections must be an object")
    else:
        sec = dict(sections)
    parent = raw.get("parent")
    return Node(str(raw["id"]), str(raw["level"]), str(parent) if parent is not None else None, sec)


def _parse_regulation_requirement(raw: ABCMapping[str, Any], ctx: str) -> RegulationRequirement:
    _check_keys(raw, REGULATION_REQ_KEYS, ctx)
    return RegulationRequirement(
        str(raw["ref"]),
        str(raw["regulation"]),
        str(raw["duty_id"]),
        str(raw["duty_version"]),
    )


def _parse_matrix_subject(raw: ABCMapping[str, Any], ctx: str) -> Subject:
    _check_keys(raw, MATRIX_SUBJECT_KEYS, ctx)
    return Subject(str(raw["ref"]), str(raw["level"]))


def _parse_subject_kind(raw: ABCMapping[str, Any], ctx: str) -> SubjectKind:
    _check_keys(raw, SUBJECT_KIND_KEYS, ctx)
    return SubjectKind(str(raw["ref"]), str(raw["board_kind"]))


def _parse_signal(raw: ABCMapping[str, Any], ctx: str) -> SignalEntry:
    _check_keys(raw, SIGNAL_KEYS, ctx)
    return SignalEntry(str(raw["type"]), str(raw["subject"]), int(raw["at_ms"]))


def _parse_compliance_ref(raw: ABCMapping[str, Any], ctx: str) -> ComplianceGapRef:
    _check_keys(raw, COMPLIANCE_REF_KEYS, ctx)
    return ComplianceGapRef(
        str(raw["regulation"]),
        str(raw["duty"]),
        str(raw["duty_version"]),
        str(raw["event_type"]),
    )


def parse_fixture_data(data: ABCMapping[str, Any], *, path: str = "fixture") -> None:
    if not isinstance(data, dict):
        raise ReplayError(f"{path}: root must be an object")
    _check_keys(data, FIXTURE_KEYS, path)
    events = _require_array(data, "events", path)
    expected = _require_array(data, "expected_open_items", path)
    wi_raw = data.get("world_inputs")
    if not isinstance(wi_raw, dict):
        raise ReplayError(f"{path}: world_inputs must be an object")
    _check_keys(wi_raw, WORLD_INPUT_KEYS, f"{path}.world_inputs")
    for key in WORLD_INPUT_KEYS:
        val = wi_raw[key]
        if not isinstance(val, list):
            raise ReplayError(f"{path}.world_inputs.{key} must be an array")
    for i, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.events[{i}] must be an object")
        _parse_event(raw, f"{path}.events[{i}]", i + 1)
    wi = wi_raw
    for i, raw in enumerate(wi["pointers"]):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.world_inputs.pointers[{i}] must be an object")
        _parse_pointer(raw, f"{path}.world_inputs.pointers[{i}]")
    for i, raw in enumerate(wi["nodes"]):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.world_inputs.nodes[{i}] must be an object")
        _parse_node(raw, f"{path}.world_inputs.nodes[{i}]")
    for i, raw in enumerate(wi["subjects"]):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.world_inputs.subjects[{i}] must be an object")
        _parse_subject_kind(raw, f"{path}.world_inputs.subjects[{i}]")
    for i, raw in enumerate(wi["signals"]):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.world_inputs.signals[{i}] must be an object")
        _parse_signal(raw, f"{path}.world_inputs.signals[{i}]")
    for i, raw in enumerate(wi["regulation_requirements"]):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.world_inputs.regulation_requirements[{i}] must be an object")
        _parse_regulation_requirement(raw, f"{path}.world_inputs.regulation_requirements[{i}]")
    rel_viol = data.get("expected_relation_violations")
    if rel_viol is not None:
        if not isinstance(rel_viol, list):
            raise ReplayError(f"{path}: expected_relation_violations must be an array")
        for i, pair in enumerate(rel_viol):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ReplayError(f"{path}: expected_relation_violations[{i}] must be [pointer_id, violation_id]")
    for i, raw in enumerate(expected):
        if not isinstance(raw, dict):
            raise ReplayError(f"{path}.expected_open_items[{i}] must be an object")
        _check_keys(raw, EXPECTED_KEYS, f"{path}.expected_open_items[{i}]")
        comp = raw.get("compliance")
        if comp is not None:
            if not isinstance(comp, list):
                raise ReplayError(f"{path}.expected_open_items[{i}].compliance must be an array")
            for j, cref in enumerate(comp):
                if not isinstance(cref, dict):
                    raise ReplayError(f"{path}.expected_open_items[{i}].compliance[{j}] must be an object")
                _parse_compliance_ref(cref, f"{path}.expected_open_items[{i}].compliance[{j}]")


def parse_world_inputs(data: ABCMapping[str, Any]) -> WorldInputs:
    wi = data["world_inputs"]
    return WorldInputs(
        pointers=[_parse_pointer(p, "wi.pointers") for p in wi["pointers"]],
        nodes=[_parse_node(n, "wi.nodes") for n in wi["nodes"]],
        subjects=[_parse_subject_kind(s, "wi.subjects") for s in wi["subjects"]],
        signals=[_parse_signal(s, "wi.signals") for s in wi["signals"]],
        open_challenges=list(wi["open_challenges"]),
        regulation_requirements=[
            _parse_regulation_requirement(r, "wi.regulation_requirements")
            for r in wi["regulation_requirements"]
        ],
        matrix_subjects=[_parse_matrix_subject(s, "wi.matrix_subjects") for s in wi["matrix_subjects"]],
    )


def parse_expected_item(raw: ABCMapping[str, Any]) -> TypedOpenItem:
    compliance_raw = raw.get("compliance")
    if compliance_raw is None:
        compliance: tuple[ComplianceGapRef, ...] = ()
    else:
        compliance = tuple(
            _parse_compliance_ref(c, "compliance") for c in compliance_raw
        )
    detail = raw.get("detail")
    if detail is not None:
        detail = str(detail)
    return TypedOpenItem(
        str(raw["board_kind"]),
        str(raw["subject"]),
        str(raw["reason"]),
        detail=detail,
        compliance=compliance,
    )


def open_items_json(items: list[TypedOpenItem]) -> list[dict[str, Any]]:
    return [i.to_dict() for i in items]


def build_log(data: ABCMapping[str, Any]) -> list[Event]:
    out: list[Event] = []
    for seq, raw in enumerate(data["events"], start=1):
        out.append(_parse_event(raw, f"events[{seq - 1}]", seq))
    return out


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "name" not in data:
        data = dict(data)
        data["name"] = path.stem
    parse_fixture_data(data, path=str(path))
    return data


def project_open_items(data: ABCMapping[str, Any], profile: Profile | None = None) -> list[dict[str, Any]]:
    profile = profile or load_profile()
    log = build_log(data)
    w = parse_world_inputs(data)
    wm = project_world(profile, log, w)
    return open_items_json(wm.open_items)


def project_all_relation_violations(data: ABCMapping[str, Any], profile: Profile | None = None) -> list[list[str]]:
    profile = profile or load_profile()
    log = build_log(data)
    w = parse_world_inputs(data)
    pairs = relation_check(
        log,
        w.pointers,
        profile,
        regulation_requirements=list(w.regulation_requirements),
        subject_kinds=tuple(w.subjects),
        nodes=tuple(w.nodes),
    )
    return [[pid, vid] for pid, vid in pairs]


def run_fixture(data: ABCMapping[str, Any], profile: Profile | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profile = profile or load_profile()
    actual = project_open_items(data, profile)
    expected = [parse_expected_item(x).to_dict() for x in data["expected_open_items"]]
    return actual, expected


def run_fixture_relations(data: ABCMapping[str, Any], profile: Profile | None = None) -> tuple[list[list[str]], list[list[str]]]:
    if "expected_relation_violations" not in data:
        return [], []
    profile = profile or load_profile()
    actual = project_all_relation_violations(data, profile)
    expected_raw = data.get("expected_relation_violations")
    expected = [list(x) for x in expected_raw] if expected_raw is not None else []
    return actual, expected


def list_fixture_paths() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def list_invalid_paths() -> list[Path]:
    if not INVALID_DIR.is_dir():
        return []
    return sorted(INVALID_DIR.glob("*.json"))


def load_mcdc() -> dict[str, Any]:
    return json.loads(MCDC_PATH.read_text(encoding="utf-8"))


def _path_allowed_diff(path: str, differs_in: list[str]) -> bool:
    return any(path == d or path.startswith(d + ".") for d in differs_in)


def _collect_paths(value: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if prefix:
        paths.add(prefix)
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{prefix}.{k}" if prefix else k
            paths |= _collect_paths(v, child)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            child = f"{prefix}.{i}" if prefix else str(i)
            paths |= _collect_paths(v, child)
    return paths


def _get_path(value: Any, path: str) -> Any:
    if not path:
        return value
    parts = path.split(".")
    cur = value
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _skip_pair_equality(path: str, differs_in: list[str]) -> bool:
    if path == "name" or path.startswith("expected_open_items"):
        return True
    if path == "expected_relation_violations" or path.startswith("expected_relation_violations"):
        return True
    if _path_allowed_diff(path, differs_in):
        return True
    if any(d.startswith(path + ".") for d in differs_in):
        return True
    return False


def assert_pair_differs_only(data_a: ABCMapping[str, Any], data_b: ABCMapping[str, Any], differs_in: list[str]) -> None:
    shared = _collect_paths(data_a) & _collect_paths(data_b)
    for path in sorted(shared):
        if _skip_pair_equality(path, differs_in):
            continue
        if _get_path(data_a, path) != _get_path(data_b, path):
            raise ReplayError(f"path {path!r} differs but is not listed in differs_in {differs_in}")


def assert_pair_differs_on(data_a: ABCMapping[str, Any], data_b: ABCMapping[str, Any], differs_in: list[str]) -> None:
    for d in differs_in:
        va = _get_path(data_a, d)
        vb = _get_path(data_b, d)
        if va == vb:
            raise ReplayError(f"differs_in path {d!r} is equal in both fixtures")


def outcome_present(items: list[dict[str, Any]], reason: str, detail: str | None = None) -> bool:
    for item in items:
        if item.get("reason") != reason:
            continue
        if detail is None:
            return True
        if item.get("detail") == detail:
            return True
    return False


def mcdc_outcome_spec(reason: str, condition: str) -> tuple[str, str | None]:
    if reason == "dor_violation":
        return "dor_violation", condition
    if reason == "claim_unmet":
        return "claim_unmet", None
    return reason, None


def mcdc_relation_spec(reason: str, condition: str) -> tuple[str, str]:
    if reason == "refines_violation":
        mapping = {
            "meaning_missing": (REFINES_MEANING_MISSING, "P-R1"),
            "pair_not_in_profile": (REFINES_PAIR_NOT_IN_PROFILE, "P-R2"),
            "level_invalid": (REFINES_LEVEL_INVALID, "P-R3"),
            "pointer_unpinned": (POINTER_UNPINNED, "P-R4"),
            "pointer_suspect": (POINTER_SUSPECT, "P-R5"),
        }
        if condition not in mapping:
            raise ValueError(condition)
        return mapping[condition]
    if reason != "maps_to_violation":
        raise ValueError(reason)
    if condition == "target_mismatch":
        return "maps_to_target_mismatch", "CM-T1"
    if condition == "compliance_purpose_wrong" or condition == "compliance_purpose_mixed":
        return "maps_to_compliance_purpose_invalid", "CM-T1"
    raise ValueError(condition)


def relation_violation_present(pairs: list[list[str]], violation: str, pointer_id: str) -> bool:
    return any(pid == pointer_id and vid == violation for pid, vid in pairs)


def check_mcdc_coverage(
    *,
    open_items_for: Callable[[ABCMapping[str, Any]], list[dict[str, Any]]] | None = None,
    relation_violations_for: Callable[[ABCMapping[str, Any]], list[list[str]]] | None = None,
) -> list[str]:
    project_open = open_items_for or project_open_items
    project_rel = relation_violations_for or project_all_relation_violations
    names = {p.stem for p in list_fixture_paths()}
    spec = load_mcdc()
    errs: list[str] = []
    for reason, block in (spec.get("reasons") or {}).items():
        for cond, pair in (block.get("conditions") or {}).items():
            when_true = pair.get("when_true")
            when_false = pair.get("when_false")
            differs_in = pair.get("differs_in")
            if not when_true or not when_false:
                errs.append(f"{reason}.{cond}: missing when_true or when_false")
                continue
            if not isinstance(differs_in, list) or not differs_in:
                errs.append(f"{reason}.{cond}: missing differs_in array")
                continue
            if when_true not in names:
                errs.append(f"{reason}.{cond}: when_true fixture {when_true!r} missing")
            if when_false not in names:
                errs.append(f"{reason}.{cond}: when_false fixture {when_false!r} missing")
            if when_true in names and when_false in names:
                try:
                    d_true = load_fixture(FIXTURES_DIR / f"{when_true}.json")
                    d_false = load_fixture(FIXTURES_DIR / f"{when_false}.json")
                    assert_pair_differs_only(d_true, d_false, differs_in)
                    assert_pair_differs_on(d_true, d_false, differs_in)
                except ReplayError as e:
                    errs.append(f"{reason}.{cond}: differs_in check: {e}")
                    continue
                if reason in ("maps_to_violation", "refines_violation"):
                    try:
                        vid, pid = mcdc_relation_spec(reason, cond)
                        present_true = relation_violation_present(project_rel(d_true), vid, pid)
                        present_false = relation_violation_present(project_rel(d_false), vid, pid)
                    except ReplayError as e:
                        errs.append(f"{reason}.{cond}: relation projection: {e}")
                        continue
                else:
                    out_reason, out_detail = mcdc_outcome_spec(reason, cond)
                    try:
                        present_true = outcome_present(project_open(d_true), out_reason, out_detail)
                        present_false = outcome_present(project_open(d_false), out_reason, out_detail)
                    except ReplayError as e:
                        errs.append(f"{reason}.{cond}: projection: {e}")
                        continue
                if present_true == present_false:
                    label = f"{reason}.{cond}"
                    if reason in ("maps_to_violation", "refines_violation"):
                        vid, pid = mcdc_relation_spec(reason, cond)
                        errs.append(
                            f"{label}: violation {vid!r} on {pid!r} same in {when_true} and {when_false}"
                        )
                    else:
                        out_reason, out_detail = mcdc_outcome_spec(reason, cond)
                        errs.append(
                            f"{label}: outcome {out_reason!r} detail={out_detail!r} "
                            f"same in {when_true} and {when_false}"
                        )
    return errs

def append_payload_from_fixture_event(
    raw: ABCMapping[str, Any],
    seq: int,
    id_map: ABCMapping[str, str],
    *,
    ctx: str,
) -> dict[str, Any]:
    event = _parse_event(raw, ctx, seq)
    payload = event.envelope()
    sup = raw.get("supersedes")
    if isinstance(sup, list) and sup:
        payload["supersedes"] = [id_map[str(s)] for s in sup if str(s) in id_map]
    return payload

