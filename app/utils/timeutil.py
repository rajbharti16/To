"""Timestamp parsing + human formatting. Everything is UTC epoch seconds."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_DMY = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_YMD_DOT = re.compile(r"^(\d{4})[./](\d{1,2})[./](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?")

_MIN_TS = 946_684_800
_MAX_TS = 4_102_444_800


def _epoch(value) -> int | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1e11:
        v /= 1000.0
    return int(v) if _MIN_TS <= v <= _MAX_TS else None


def _mk(y, mo, d, h=0, mi=0, s=0) -> int | None:
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    ts = int(dt.timestamp())
    return ts if _MIN_TS <= ts <= _MAX_TS else None


def parse_ts(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _epoch(text)
    for rx in (_ISO, _YMD_DOT):
        m = rx.match(text)
        if m:
            return _mk(*m.groups(default=0))
    m = _DMY.match(text)
    if m:
        d, mo, y, h, mi, s = m.groups(default=0)
        return _mk(y, mo, d, h, mi, s)
    return None


def now() -> int:
    return int(time.time())


def age_hours(ts: int | None, at: int | None = None) -> float | None:
    if not ts:
        return None
    return max(0.0, ((at or now()) - ts) / 3600.0)


def fmt_age(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    minutes = int(max(0.0, hours) * 60)
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"{minutes}m"
    h, m = divmod(minutes, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h:02d}h"


def fmt_dt(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fmt_left(expires_at: int | None) -> str:
    if not expires_at:
        return "—"
    left = expires_at - now()
    return "cleaning" if left <= 0 else fmt_age(left / 3600.0)