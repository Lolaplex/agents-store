"""Hybrid logical clock: globally comparable ordering keys for datoms.

ord format: f"{ms:013d}.{counter:05d}.{node}". Properties:

- sorts lexicographically; physical time dominates, counter breaks ties
  within one millisecond, node id breaks remaining ties (total order);
- every key starts with a 13-digit millisecond epoch, so it always sorts
  after the 12-digit legacy backfill keys (printf('%012d', tx)) produced
  by _migrate_v6 — old local history loses to any synced write, which is
  chronologically correct;
- node ids normalize to [A-Za-z0-9_-] so the key splits cleanly (arbitrary
  ids like did:key:... hash deterministically into the same alphabet);
- observe() clamps remote ms at MAX_DRIFT_MS ahead of the local wall
  clock: a skewed peer cannot pin the fleet clock in the far future;
- counter caps at 99999 — the 05d field would break lexical order at
  100000 — by advancing the millisecond instead.
"""
from __future__ import annotations

import hashlib
import re
import time

_RAW_NODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_HLC_RE = re.compile(r"^\d{13}\.\d{5}\.[A-Za-z0-9_-]+$")

MAX_DRIFT_MS = 60_000
_MAX_COUNTER = 99_999

# tx.hlc/datom.ord wire shape as a SQLite GLOB: 13 digits, dot, 5 digits,
# dot, node — filters the legacy 12-digit backfill keys out of MAX(hlc).
HLC_GLOB = "[0-9]" * 13 + "." + "[0-9]" * 5 + ".*"


def normalize_node_id(raw: str) -> str:
    """Any node id -> a valid hlc node part. [A-Za-z0-9_-]{1,32} passes
    through; anything else (did:..., actor@host) hashes to a deterministic
    k_<sha256[:16]> — still a valid node part, still a stable tie-break."""
    s = str(raw or "")
    if _RAW_NODE_RE.match(s):
        return s
    return "k_" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def is_hlc(ord_key: str) -> bool:
    """Strict wire shape: 13-digit ms, 5-digit counter, valid node part."""
    return isinstance(ord_key, str) and bool(_HLC_RE.match(ord_key))


def _fmt(ms: int, counter: int, node: str) -> str:
    return f"{ms:013d}.{counter:05d}.{node}"


def _parse(ord_key: str) -> tuple[int, int] | None:
    """(ms, counter) for hlc-formatted keys; None for legacy/garbage keys."""
    if not is_hlc(ord_key):
        return None
    ms, ctr, _ = ord_key.split(".", 2)
    return int(ms), int(ctr)


class Hlc:
    """Per-node clock. One instance per process; thread-unsafe callers must
    serialize transact() anyway (single sqlite connection)."""

    def __init__(self, node_id: str):
        self.node = normalize_node_id(node_id)
        self._ms = 0
        self._counter = 0

    def tick(self) -> str:
        """Next ordering key for a local event."""
        ms = int(time.time() * 1000)
        if ms <= self._ms:
            if self._counter >= _MAX_COUNTER:
                # counter field is 05d: bump the ms instead of wrapping
                # to a lexically-smaller 6-digit counter
                self._ms += 1
                self._counter = 0
            else:
                self._counter += 1
            ms = self._ms
        else:
            self._ms, self._counter = ms, 0
        return _fmt(ms, self._counter, self.node)

    def observe(self, remote_ord: str) -> None:
        """Merge a remote key so future local ticks order after it."""
        parsed = _parse(remote_ord)
        if parsed is None:
            return  # legacy backfill or malformed key: nothing to merge
        rms, rctr = parsed
        wall = int(time.time() * 1000)
        if rms > wall + MAX_DRIFT_MS:
            # skewed peer: clamp at the drift bound rather than letting it
            # pin this node's clock in the far future
            rms, rctr = wall + MAX_DRIFT_MS, 0
        if rms > self._ms or (rms == self._ms and rctr >= self._counter):
            if rctr >= _MAX_COUNTER:
                self._ms, self._counter = rms + 1, 0
            else:
                self._ms, self._counter = rms, rctr + 1
