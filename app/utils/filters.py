"""Pure filter logic — no IO, unit-testable."""
from __future__ import annotations

import re

TARGET_FALLBACK = 24.0

_COUNTRY_RE = re.compile(r"\(([A-Z]{2})\)")
_PHONE_RE = re.compile(r"\+\d{6,16}")

# priority order: most explicit key wins
_AGE_NUM_KEYS = (
    "telegram_session_age",
    "session_age",
    "session_age_hours",
    "session_age_seconds",
)
_PERIOD_KEYS = ("session_age_period", "telegram_session_age_period")

_PERIOD_HOURS = {
    "hour": 1.0, "hours": 1.0, "h": 1.0, "hr": 1.0, "hrs": 1.0,
    "час": 1.0, "часа": 1.0, "часов": 1.0, "ч": 1.0,
    "day": 24.0, "days": 24.0, "d": 24.0,
    "д": 24.0, "дн": 24.0, "дня": 24.0, "дней": 24.0, "сут": 24.0, "суток": 24.0,
    "month": 730.0, "months": 730.0, "mo": 730.0,
    "мес": 730.0, "месяц": 730.0, "месяца": 730.0, "месяцев": 730.0,
    "year": 8760.0, "years": 8760.0, "y": 8760.0,
    "г": 8760.0, "год": 8760.0, "года": 8760.0, "лет": 8760.0,
}

# "session age: 30 days", "сессия 2 месяца", "30d session"
_AGE_TEXT_RES = (
    re.compile(
        r"(?:session\s*age|возраст\s*сесси[ия]|сесси[яи])\s*[:\-–—]?\s*"
        r"(\d+(?:[.,]\d+)?)\s*([A-Za-zА-Яа-я]+)?"
    ),
    re.compile(
        r"(\d+(?:[.,]\d+)?)\s*([A-Za-zА-Яа-я]+)?\s*(?:session|сесси[яи])"
    ),
)


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def country_of(item: dict) -> str:
    """ISO2 country: explicit field first, then the "(XX)" marker in the title."""
    explicit = str(item.get("country") or "").strip().upper()
    if len(explicit) == 2 and explicit.isalpha():
        return explicit
    m = _COUNTRY_RE.search(item.get("title", "") or "")
    return m.group(1) if m else ""


def phone_of(item: dict) -> str:
    m = _PHONE_RE.search(item.get("title", "") or "")
    return m.group(0) if m else ""


def _period_hours(item: dict) -> float | None:
    for key in _PERIOD_KEYS:
        raw = item.get(key)
        if isinstance(raw, str):
            mult = _PERIOD_HOURS.get(raw.strip().lower())
            if mult:
                return mult
    return None


def _unit_from_key(key: str) -> float | None:
    if key.endswith("_seconds"):
        return 1 / 3600
    if key.endswith("_hours"):
        return 1.0
    if key.endswith("_days"):
        return 24.0
    return None


def _age_from_text(item: dict) -> float | None:
    text = f"{item.get('title') or ''} {item.get('description') or ''}"
    if not text.strip():
        return None
    for rx in _AGE_TEXT_RES:
        for m in rx.finditer(text):
            amount = _num(m.group(1))
            if amount is None or amount <= 0:
                continue
            unit = (m.group(2) or "").strip().lower()
            mult = _PERIOD_HOURS.get(unit)
            if mult:
                return amount * mult
            # bare "session 30" -> assume days (dominant market usage)
            if unit in ("", "s"):
                return amount * 24.0
    return None


def session_hours(item: dict) -> float | None:
    """Age of the session in hours, or None when it cannot be determined.

    The market does not expose session age as a structured item field — it is
    only a search filter. So: numeric fields first, then title/description text.
    """
    for key in _AGE_NUM_KEYS:
        raw = item.get(key)
        v = _num(raw)
        if v is None or v <= 0:
            continue
        mult = _period_hours(item) or _unit_from_key(key)
        if mult:
            return v * mult
        if v > 100_000:      # seconds
            return v / 3600
        if v > 1_000:        # hours
            return v
        return v * 24.0      # days
    return _age_from_text(item)


def search_query(s: dict) -> dict:
    """Server-side age floor. Empty dict when no floor is configured."""
    floor = _num(s.get("session_min_hours")) or 0.0
    days = int(floor // 24)
    if days < 1:
        return {}  # sub-day floors: the API only knows day/month/year
    if days % 30 == 0:
        return {"session_age": days // 30, "session_age_period": "month"}
    return {"session_age": days, "session_age_period": "day"}


def spam_ok(item: dict, mode: str) -> bool:
    if mode == "any":
        return True
    flag = item.get("telegram_spam_block")
    return (flag is True) if mode == "yes" else (flag is not True)


def has_mail(item: dict) -> bool:
    return bool(item.get("telegram_email")) or item.get("email_type") not in (None, "", "no")


def _codes(raw: str) -> set[str]:
    return {c.strip().upper() for c in (raw or "").split(",") if c.strip()}


def passes(item: dict, s: dict) -> tuple[bool, str]:
    """Returns (ok, reason). Reason is short so the loop can log a tally."""
    price = _num(item.get("price")) or 0.0
    if price < (_num(s.get("price_min")) or 0.0):
        return False, "price_min"
    if price > (_num(s.get("price_max")) or float("inf")):
        return False, "price_max"
    if not spam_ok(item, s.get("spam_mode", "no")):
        return False, "spam"
    if s.get("mail_mode") == "yes" and not has_mail(item):
        return False, "no_mail"
    if s.get("mail_mode") == "no" and has_mail(item):
        return False, "has_mail"
    if s.get("password_mode") == "yes" and not item.get("telegram_password"):
        return False, "no_2fa"
    if s.get("password_mode") == "no" and item.get("telegram_password"):
        return False, "has_2fa"

    cc = country_of(item)
    allow = _codes(s.get("countries", ""))
    deny = _codes(s.get("deny_countries", ""))
    if allow and cc not in allow:
        return False, "country_not_included"
    if cc and cc in deny:
        return False, "country_excluded"

    if s.get("nsb_only") == "1" and item.get("nsb") is False:
        return False, "resold"

    floor = _num(s.get("session_min_hours")) or 0.0
    if floor:
        age = session_hours(item)
        if age is None:
            # unknown age is not a reject — buy_one re-checks after check-account
            return True, "age_unknown"
        if age < floor:
            return False, "session_too_fresh"
    return True, "ok"


def clean_delay_hours(item: dict, target: float = TARGET_FALLBACK) -> float:
    """Hours to wait before cleaning. 0.0 means clean immediately.

    Unknown age counts as 0, i.e. the full target is waited out — never early.
    """
    age = session_hours(item) or 0.0
    return max(0.0, float(target) - age)