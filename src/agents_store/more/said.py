"""Self-addressing identifiers (SAIDs) for MORe events.

Name vs. content: the event's name (event id = entity id, a minted ULID) is
the reference target for lineage, more:pin and corrections. The SAID is a
separate content digest, stored as more:said (text, one) in the event's own
tx; that datom is the name -> SAID binding. A correction or supersession is
a new event with a new name and a new SAID; nothing is rewritten.

Scheme (KERI/CESR, as in keripy ``Saider``):

- digest: BLAKE3-256 over the serialized SAD with the ``d`` field set to the
  44-char placeholder ``'#' * 44``;
- encoding: CESR qb64 with derivation code ``E`` (Blake3_256): base64url of
  one zero lead byte + the 32 raw bytes, the first char replaced by ``E``
  (44 chars, so the second char is always in ``A``-``P``);
- serialization: KERI style, not JCS. Compact JSON exactly as keripy dumps it
  (``json.dumps(sad, separators=(",", ":"), ensure_ascii=False)``, UTF-8,
  with ``allow_nan=False`` so NaN/Infinity never reach a digest), in
  the SAD's own field order. The event SAD has a fixed top-level order:
  ``d``, ``i`` (the event name), then the envelope fields in
  ``events._ENVELOPE`` order. Nested objects (``body``, …) have no
  schema-fixed order, so their keys are sorted (code-point order, like
  ``sort_keys=True``) before serializing. keripy's ``Saider.verify`` accepts
  the resulting SAD unchanged.
- numbers: only integers within ±(2**53 - 1); a non-integer quantity is
  ``{"value": <int>, "scale": <int>}`` (numbers.py, C4). EventLog.append
  refuses anything else before a SAID is computed.

Including ``i`` binds the SAID to one name: the same content under another
event id has another SAID. The log's seq/prev/digest are not hashed; the
sha256 hash chain in the event table stays as it is.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Mapping

import blake3

from .events import _ENVELOPE, Event

CODE = "E"                      # CESR MtrDex.Blake3_256
SIZE = 44                       # qb64 length of a 32-byte digest with code E
PLACEHOLDER = "#" * SIZE        # KERI dummy for the 'd' field while digesting
LABEL = "d"
NAME = "i"

_SAID_RE = re.compile(r"^E[A-P][A-Za-z0-9_-]{42}$")


def is_said(s: str) -> bool:
    """True for a well-formed CESR Blake3-256 qb64 digest."""
    return isinstance(s, str) and _SAID_RE.match(s) is not None


def qb64_blake3_256(raw: bytes) -> str:
    """CESR qb64 of a 32-byte BLAKE3-256 digest (code 'E', one lead pad byte)."""
    if len(raw) != 32:
        raise ValueError("Blake3-256 digest must be 32 bytes")
    b64 = base64.urlsafe_b64encode(b"\x00" + raw).decode("ascii")
    return CODE + b64[1:]


def digest(ser: bytes) -> str:
    """CESR Blake3-256 digest of raw bytes (keripy ``Diger(ser=...)``)."""
    return qb64_blake3_256(blake3.blake3(ser).digest())


def dumps(sad: Mapping[str, Any]) -> bytes:
    """keripy JSON serialization: compact, insertion order, UTF-8. NaN and
    ±Infinity raise ValueError (they are not JSON)."""
    return json.dumps(sad, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def saidify(sad: Mapping[str, Any], label: str = LABEL) -> tuple[str, dict[str, Any]]:
    """SAID of `sad` and a copy with the SAID in `label` (keripy
    ``Saider.saidify``). The label must already be a field of the SAD."""
    if label not in sad:
        raise KeyError(f"saidify: SAD has no {label!r} field")
    d = dict(sad)
    d[label] = PLACEHOLDER
    said = digest(dumps(d))
    d[label] = said
    return said, d


def verify(sad: Mapping[str, Any], label: str = LABEL) -> bool:
    """The SAD carries its own SAID in `label`."""
    said = sad.get(label)
    return is_said(said) and saidify(sad, label)[0] == said


def _sorted(v: Any) -> Any:
    if isinstance(v, Mapping):
        return {k: _sorted(v[k]) for k in sorted(v)}
    if isinstance(v, (list, tuple)):
        return [_sorted(x) for x in v]
    return v


def event_sad(event: Event, name: str) -> dict[str, Any]:
    """The SAD of one event under `name`, with the placeholder in 'd'."""
    if not name:
        raise ValueError("event_sad: the event name (event id) is required")
    env = event.envelope()
    sad: dict[str, Any] = {LABEL: PLACEHOLDER, NAME: name}
    for k in _ENVELOPE:
        sad[k] = _sorted(env[k])
    return sad


def event_said(event: Event, name: str) -> str:
    return saidify(event_sad(event, name))[0]
