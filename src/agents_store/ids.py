"""Minted entity identifiers. ULID: 48-bit ms timestamp + 80-bit random,
Crockford base32, 26 chars. Time-sortable; monotonic within the same
millisecond so creation order == lexicographic order. Never derived from
content, path, rank or order of the entity itself.
"""
from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_MASK48 = (1 << 48) - 1
_MASK80 = (1 << 80) - 1

_last_ms = -1
_last_rand = 0


def mint() -> str:
    global _last_ms, _last_rand
    ms = time.time_ns() // 1_000_000 & _MASK48
    if ms == _last_ms:
        _last_rand = (_last_rand + 1) & _MASK80
    else:
        _last_ms = ms
        _last_rand = secrets.randbits(80)
    n = ms << 80 | _last_rand
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(chars))
