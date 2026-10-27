"""Canonical numbers in MORe events (C4, ruled 2026-10-27).

Rule: a number in an event is a JSON integer in the I-JSON safe range
(|n| <= 2**53 - 1, RFC 7493 §2.2). A non-integer quantity is written as an
integer with a declared scale: ``{"value": 80, "scale": 2}`` means 0.80
(value * 10**-scale). Binary floats are refused, NaN and ±Infinity too.
Decimal strings and floats under JCS were considered and rejected.

Why: the SAID (said.py) and the hash chain (Event.canonical) hash the JSON
text. Python writes a float as its shortest repr (0.30000000000000004,
1e-07, -0.0) and NaN as the bare token NaN, which is not JSON. Other
implementations write the same value differently, so the same content
would get a different SAID. Integers are written the same everywhere
within the safe range.

`bool` is a JSON literal, not a number, and passes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

MAX_SAFE_INTEGER = 2**53 - 1

# typed refusal reasons (WriteRefusal.reason)
NUMBER_FLOAT = "number_float"                # a finite binary float
NUMBER_NONFINITE = "number_nonfinite"        # NaN, Infinity, -Infinity
NUMBER_OUT_OF_RANGE = "number_out_of_range"  # integer beyond ±(2**53 - 1)
REASONS = (NUMBER_FLOAT, NUMBER_NONFINITE, NUMBER_OUT_OF_RANGE)


@dataclass(frozen=True)
class NumberIssue:
    path: str     # JSON path in the envelope, e.g. "$.body.amount"
    reason: str   # one of REASONS
    value: str    # repr of the offending value


def number_issues(v: Any, path: str = "$") -> list[NumberIssue]:
    """Every number in `v` that is not canonical, in document order."""
    out: list[NumberIssue] = []
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return out
    if isinstance(v, int):
        if abs(v) > MAX_SAFE_INTEGER:
            out.append(NumberIssue(path, NUMBER_OUT_OF_RANGE, repr(v)))
    elif isinstance(v, float):
        reason = NUMBER_FLOAT if math.isfinite(v) else NUMBER_NONFINITE
        out.append(NumberIssue(path, reason, repr(v)))
    elif isinstance(v, Mapping):
        for k, x in v.items():
            out += number_issues(x, f"{path}.{k}")
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            out += number_issues(x, f"{path}[{i}]")
    return out


def scaled(x: Decimal | str | int) -> dict[str, int]:
    """The canonical form of an exact decimal: ``scaled("0.80")`` is
    ``{"value": 80, "scale": 2}``. The scale is the number of digits after
    the point as written, so 0.8 and 0.80 stay distinct (declared scale).
    Floats are refused: convert from the source text, not from a float."""
    if isinstance(x, float):
        raise TypeError("scaled: pass the decimal text or a Decimal, not a float")
    d = Decimal(x)
    if not d.is_finite():
        raise ValueError("scaled: not a finite number")
    sign, digits, exp = d.as_tuple()
    scale = max(0, -exp)
    value = int(d.scaleb(scale))
    if abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("scaled: value beyond ±(2**53 - 1)")
    return {"value": value, "scale": scale}


def unscaled(v: Mapping[str, int]) -> Decimal:
    """Inverse of `scaled`."""
    return Decimal(v["value"]).scaleb(-v["scale"])
