"""Hybrid logical clock: globally comparable ordering keys for datoms.

ord format: f"{ms:013d}.{counter:05d}.{node}". Properties:

- sorts lexicographically; physical time dominates, counter breaks ties
  within one millisecond, node id breaks remaining ties (total order);
- every key starts with a 13-digit millisecond epoch, so it always sorts
  after the 12-digit legacy backfill keys (printf('%012d', tx)) produced
  by _migrate_v6 — old local history loses to any synced write, which is
  chronologically correct;
- node ids are restricted to [A-Za-z0-9_-] so the key splits cleanly.
"""
from __future__ import annotations

import re
import time

_NODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_node(node: str) -> str:
    if not _NODE_RE.match(node):
        raise ValueError(f"hlc: bad node id {node!r} ([A-Za-z0-9_-] only)")
    return node


def _fmt(ms: int, counter: int, node: str) -> str:
    return f"{ms:013d}.{counter:05d}.{node}"


def _parse(ord_key: str) -> tuple[int, int] | None:
    """(ms, counter) for hlc-formatted keys; None for legacy tx keys."""
    head, _, _ = ord_key.partition(".")
    tail = ord_key.split(".", 2)
    if len(tail) != 3 or not head.isdigit():
        return None
    ctr = tail[1]
    return (int(head), int(ctr) if ctr.isdigit() else 0)


class Hlc:
    """Per-node clock. One instance per process; thread-unsafe callers must
    serialize transact() anyway (single sqlite connection)."""

    def __init__(self, node_id: str):
        self.node = _check_node(node_id)
        self._ms = 0
        self._counter = 0

    def tick(self) -> str:
        """Next ordering key for a local event."""
        ms = int(time.time() * 1000)
        if ms <= self._ms:
            self._counter += 1
            ms = self._ms
        else:
            self._ms, self._counter = ms, 0
        return _fmt(ms, self._counter, self.node)

    def observe(self, remote_ord: str) -> None:
        """Merge a remote key so future local ticks order after it."""
        parsed = _parse(remote_ord)
        if parsed is None:
            return  # legacy backfill key: no clock component to merge
        rms, rctr = parsed
        if rms > self._ms or (rms == self._ms and rctr >= self._counter):
            self._ms = rms
            self._counter = rctr + 1
