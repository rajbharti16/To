"""Pure filter logic — no IO, unit-testable.

Age comes from the real account creation time first, then session-age fields,
then the title. Anything unreadable stays "unknown" and never rejects.
"""
from __future__ import annotations

import re
import time

from app.utils.timeutil import age_hours, parse_ts

TARGET_FALLBACK = 24.0

_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
_COUNTRY_RE = re.compile(r"\(([A-Z]{2})\)")
_PHONE_RE = re.compile(r"\+\d{6,16}")

_CREATED_KEYS = (
    "created_at", "creation_date", "registration_date", "telegram_registration_date",
    "telegram_created_at", "registered_at", "item_created_at", "account_created_at",
)
_CREATED_NESTED = ("item_origin", "origin", "telegram", "item", "meta", "account")

_AGE_NUM_KEYS = ("telegram_session_age", "session_age", "session_age_hours",
                 "session_age_seconds")
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

_AGE_TEXT_RES = (
    re.compile(r"(?:session\s*age|возраст\s*сесси[ия]|сесси[яи])\s*[:\-–—]?\s*"
               r"(\d+(?:[.,]\d+)?)\s*([A-Za-zА-Яа-я]+)?"),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*([A-Za-zА-Яа-я]+)?\s*(?:session|сесси[ия])"),
)

_TRUE = {"1", "true", "yes", "y", "on", "да", "blocked", "ban", "spam"}
_FALSE = {"0", "false", "no", "n", "off", "", "none", "nomatter", "-"}


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _flag(value) -> bool | None:
    """Explicit flag → bool; ambiguous text (a date, an address) → None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        for key in ("is_blocked", "blocked", "status", "value", "result"):
            if key in value:
                return _flag(value[key])
        return None
    if isinstance(value, str):
        t = value.strip().lower()
        if t in _TRUE:
            return True
        if t in _FALSE:
            return False
    return None


def _flag_to_iso(match) -> str:
    return "".join(chr(ord(ch) - 0x1F1E6 + 65) for ch in match.group(0))


def country_of(item: dict) -> str:
    for key in ("country", "country_code", "telegram_country"):
        explicit = str(item.get(key) or "").strip().upper()
        if len(explicit) == 2 and explicit.isalpha():
            return explicit
    text = f"{item.get('title') or ''} {item.get('description') or ''}"
    flag = _FLAG_RE.search(text)
    if flag:
        return _flag_to_iso(flag)
    m = _COUNTRY_RE.search(text)
    return m.group(1) if m else ""


def phone_of(item: dict) -> str:
    m = _PHONE_RE.search(item.get("title", "") or "")
    return m.group(0) if m else ""


def account_created_ts(item: dict, depth: int = 0) -> int | None:
    if depth > 3 or not isinstance(item, dict):
        return None
    for key in _CREATED_KEYS:
        if key in item:
            ts = parse_ts(item[key])
            if ts and ts <= time.time() + 86_400:
                return ts
    for key in _CREATED_NESTED:
        nested = item.get(key)
        if isinstance(nested, dict):
            ts = account_created_ts(nested, depth + 1)
            if ts:
                return ts
    return None


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
            if unit in ("", "s"):
                return amount * 24.0
    return None


def session_hours(item: dict) -> float | None:
    for key in _AGE_NUM_KEYS:
        raw = item.get(key)
        v = _num(raw)
        if v is None or v <= 0:
            continue
        mult = _period_hours(item) or _unit_from_key(key)
        if mult:
            return v * mult
        if v > 100_000:
            return v / 3600
        if v > 1_000:
            return v
        return v * 24.0
    return _age_from_text(item)


def age_hours_of(item: dict, at: int | None = None) -> float | None:
    created = account_created_ts(item)
    if created:
        return age_hours(created, at)
    return session_hours(item)


def search_query(s: dict) -> dict:
    """Server-side age floor only (day granularity is all the API supports)."""
    floor = _num(s.get("session_min_hours")) or 0.0
    days = int(floor // 24)
    if days < 1:
        return {}
    if days % 30 == 0:
        return {"session_age": days // 30, "session_age_period": "month"}
    return {"session_age": days, "session_age_period": "day"}


def spam_state(item: dict) -> bool | None:
    for key in ("telegram_spam_block", "spam_block", "is_spam_blocked", "spam"):
        if key in item:
            state = _flag(item[key])
            if state is not None:
                return state
    return None


def mail_state(item: dict) -> bool | None:
    for key in ("telegram_email", "email", "has_email"):
        if key not in item:
            continue
        raw = item[key]
        if isinstance(raw, str) and "@" in raw:
            return True
        state = _flag(raw)
        if state is not None:
            return state
    if "email_type" in item:
        et = str(item.get("email_type") or "").strip().lower()
        return et not in ("", "no", "none")
    return None


def pass_state(item: dict) -> bool | None:
    for key in ("telegram_password", "password", "has_password"):
        if key not in item:
            continue
        raw = item[key]
        if isinstance(raw, str) and raw.strip() and raw.strip().lower() not in _FALSE:
            return True
        state = _flag(raw)
        if state is not None:
            return state
    return None


def _codes(raw: str) -> set[str]:
    return {c.strip().upper() for c in (raw or "").split(",") if c.strip()}


def passes(item: dict, s: dict, authoritative: bool = False) -> tuple[bool, str]:
    """Returns (ok, reason). Unknown fields never reject."""
    price = _num(item.get("price")) or 0.0
    if price < (_num(s.get("price_min")) or 0.0):
        return False, "price_min"
    if price > (_num(s.get("price_max")) or float("inf")):
        return False, "price_max"

    if s.get("nsb_only") == "1" and _flag(item.get("nsb")) is False:
        return False, "resold"

    floor = _num(s.get("session_min_hours")) or 0.0
    cap = _num(s.get("session_max_hours")) or 0.0
    if floor or cap:
        age = age_hours_of(item)
        if age is not None:
            if floor and age < floor:
                return False, "too_fresh"
            if cap and age > cap:
                return False, "too_old"

    if not authoritative:
        return True, "ok"

    unknown = False

    spam = spam_state(item)
    mode = s.get("spam_mode", "no")
    if spam is None:
        unknown = True
    elif mode == "yes" and spam is False:
        return False, "spam_missing"
    elif mode == "no" and spam is True:
        return False, "spam"

    mail = mail_state(item)
    mode = s.get("mail_mode", "any")
    if mail is None:
        unknown = True
    elif mode == "yes" and mail is False:
        return False, "no_mail"
    elif mode == "no" and mail is True:
        return False, "has_mail"

    has_pw = pass_state(item)
    mode = s.get("password_mode", "any")
    if has_pw is None:
        unknown = True
    elif mode == "yes" and has_pw is False:
        return False, "no_2fa"
    elif mode == "no" and has_pw is True:
        return False, "has_2fa"

    cc = country_of(item)
    if cc:
        if cc in _codes(s.get("deny_countries", "")):
            return False, "country_excluded"
        allow = _codes(s.get("countries", ""))
        if allow and cc not in allow:
            return False, "country_not_included"
    else:
        unknown = True

    if floor and age_hours_of(item) is None:
        unknown = True

    return True, ("ok_unknown" if unknown else "ok")


def clean_delay_hours(item: dict, target: float = TARGET_FALLBACK,
                      early: bool = True) -> float:
    target = max(0.0, float(target))
    if not early:
        return target
    age = age_hours_of(item) or 0.0
    return min(target, max(0.0, target - age))