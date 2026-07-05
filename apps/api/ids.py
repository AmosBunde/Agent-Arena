"""UUIDv7 generation.

Run ids are UUIDv7 because v7 sorts by creation time, which makes pagination
and recent-runs queries cheap (session-design.md). The standard library has
no v7 constructor yet, so this is the RFC 9562 layout: 48 bits of Unix
milliseconds, version and variant bits, and 74 random bits.
"""

from __future__ import annotations

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    timestamp_ms = time.time_ns() // 1_000_000
    value = (timestamp_ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return uuid.UUID(int=value)
