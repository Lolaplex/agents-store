"""Replay MORe contract fixtures through the store MORe domain provider.

Event appends use ``MoreDomain.append`` → ``EventLog.append`` → ``Store.transact``.
World-model outcomes are projected from the materialized log plus fixture ``world_inputs``.
"""
from __future__ import annotations

from typing import Any, Mapping

import sqlite3

from agents_store.contracts import WriteRefusal
from agents_store.db import connect
from agents_store.domains.more import MoreDomain
from agents_store.more.log import EventLog
from agents_store.more.profile import Profile, load_profile
from agents_store.more.replay import (
    ReplayError,
    append_payload_from_fixture_event,
    open_items_json,
    parse_expected_item,
    parse_world_inputs,
    project_all_relation_violations,
)
from agents_store.more.relations import relation_check
from agents_store.more.world_model import project_world

REPLAY_ACTOR = "did:example:replay"


def append_fixture_events(
    conn: sqlite3.Connection,
    data: Mapping[str, Any],
    *,
    actor: str = REPLAY_ACTOR,
) -> list[WriteRefusal]:
    """Append each fixture event via the MORe domain provider. Stops on first refusal."""
    domain = MoreDomain()
    id_map: dict[str, str] = {}
    refusals: list[WriteRefusal] = []
    for seq, raw in enumerate(data["events"], start=1):
        if not isinstance(raw, dict):
            refusals.append(
                WriteRefusal("more", "payload_invalid", payload="event must be an object")
            )
            return refusals
        payload = append_payload_from_fixture_event(
            raw, seq, id_map, ctx=f"events[{seq - 1}]"
        )
        out = domain.append(conn, payload, actor)
        if isinstance(out, WriteRefusal):
            refusals.append(out)
            return refusals
        id_map[str(raw["id"])] = out
    return refusals


def project_open_items_from_store(
    conn: sqlite3.Connection,
    data: Mapping[str, Any],
    profile: Profile | None = None,
) -> list[dict[str, Any]]:
    profile = profile or load_profile()
    source = list(EventLog(conn=conn).events())
    w = parse_world_inputs(data)
    wm = project_world(profile, source, w)
    return open_items_json(wm.open_items)


def project_relation_violations_from_store(
    conn: sqlite3.Connection,
    data: Mapping[str, Any],
    profile: Profile | None = None,
) -> list[list[str]]:
    profile = profile or load_profile()
    source = list(EventLog(conn=conn).events())
    w = parse_world_inputs(data)
    pairs = relation_check(
        source,
        w.pointers,
        profile,
        regulation_requirements=list(w.regulation_requirements),
    )
    return [[pid, vid] for pid, vid in pairs]


def run_fixture_store(
    data: Mapping[str, Any],
    conn: sqlite3.Connection | None = None,
    profile: Profile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[WriteRefusal]]:
    """Return (actual open items, expected open items, append refusals)."""
    own = conn is None
    if own:
        conn = connect(":memory:")
    try:
        refusals = append_fixture_events(conn, data)
        expected = [parse_expected_item(x).to_dict() for x in data["expected_open_items"]]
        if refusals:
            return [], expected, refusals
        actual = project_open_items_from_store(conn, data, profile)
        return actual, expected, refusals
    finally:
        if own and conn is not None:
            conn.close()


def run_fixture_relations_store(
    data: Mapping[str, Any],
    conn: sqlite3.Connection | None = None,
    profile: Profile | None = None,
) -> tuple[list[list[str]], list[list[str]], list[WriteRefusal]]:
    if "expected_relation_violations" not in data:
        return [], [], []
    own = conn is None
    if own:
        conn = connect(":memory:")
    try:
        refusals = append_fixture_events(conn, data)
        expected_raw = data.get("expected_relation_violations") or []
        expected = [list(x) for x in expected_raw]
        if refusals:
            return [], expected, refusals
        actual = project_relation_violations_from_store(conn, data, profile)
        return actual, expected, refusals
    finally:
        if own and conn is not None:
            conn.close()


def more_refusal_rows(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return EventLog(conn=conn).refusals()


def store_open_items_for_fixture(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    conn = connect(":memory:")
    try:
        refusals = append_fixture_events(conn, data)
        if refusals:
            raise ReplayError(
                f"append refused: {refusals[0].reason} {refusals[0].payload!r}"
            )
        return project_open_items_from_store(conn, data)
    finally:
        conn.close()


def store_relation_violations_for_fixture(data: Mapping[str, Any]) -> list[list[str]]:
    conn = connect(":memory:")
    try:
        refusals = append_fixture_events(conn, data)
        if refusals:
            raise ReplayError(
                f"append refused: {refusals[0].reason} {refusals[0].payload!r}"
            )
        return project_relation_violations_from_store(conn, data)
    finally:
        conn.close()


def check_mcdc_coverage_store() -> list[str]:
    from agents_store.more.replay import check_mcdc_coverage

    return check_mcdc_coverage(
        open_items_for=store_open_items_for_fixture,
        relation_violations_for=store_relation_violations_for_fixture,
    )
