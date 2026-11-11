"""Pure filter logic — no IO, unit-testable."""
import re

TARGET_FALLBACK = 24.0


def country_of(item: dict) -> str:
    m = re.search(r"\(([A-Z]{2})\)", item.get("title", ""))
    return m.group(1) if m else ""


def phone_of(item: dict) -> str:
    m = re.search(r"\+\d{6,16}", item.get("title", ""))
    return m.group(0) if m else ""


def session_hours(item: dict) -> float:
    v = item.get("telegram_session_age") or item.get("session_age") or 0
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return v / 3600 if v > 1000 else v


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
    price = float(item.get("price") or 0)
    if price < float(s["price_min"]):
        return False, "price_min"
    if price > float(s["price_max"]):
        return False, "price_max"
    if not spam_ok(item, s["spam_mode"]):
        return False, "spam"
    if s["mail_mode"] == "yes" and not has_mail(item):
        return False, "no_mail"
    if s["mail_mode"] == "no" and has_mail(item):
        return False, "has_mail"
    if s["password_mode"] == "yes" and not item.get("telegram_password"):
        return False, "no_2fa"
    if s["password_mode"] == "no" and item.get("telegram_password"):
        return False, "has_2fa"

    cc = country_of(item)
    allow = _codes(s["countries"])
    deny = _codes(s["deny_countries"])
    if allow and cc not in allow:
        return False, "country_not_included"
    if cc and cc in deny:
        return False, "country_excluded"

    # only reject on age when a floor is configured; 24h+ items always pass
    floor = float(s["session_min_hours"] or 0)
    if floor and session_hours(item) < floor:
        return False, "session_too_fresh"

    if s["nsb_only"] == "1" and item.get("nsb") is False:
        return False, "resold"
    return True, "ok"


def clean_delay_hours(item: dict, target: float = TARGET_FALLBACK) -> float:
    """Hours to wait before cleaning. 0.0 means clean immediately."""
    return max(0.0, target - session_hours(item))