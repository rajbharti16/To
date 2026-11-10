"""Pure filter logic — no IO, unit-testable."""
import re


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


def passes(item: dict, s: dict) -> tuple[bool, str]:
    price = float(item.get("price") or 0)
    if price < float(s["price_min"]):
        return False, "below min price"
    if price > float(s["price_max"]):
        return False, "above max price"
    if not spam_ok(item, s["spam_mode"]):
        return False, "spam"
    if s["mail_mode"] == "yes" and not has_mail(item):
        return False, "no mail"
    if s["mail_mode"] == "no" and has_mail(item):
        return False, "mail present"
    if s["password_mode"] == "yes" and not item.get("telegram_password"):
        return False, "no 2fa"
    if s["password_mode"] == "no" and item.get("telegram_password"):
        return False, "2fa present"

    need = float(s["session_min_hours"] or 0)
    if need and session_hours(item) < need:
        return False, f"session {session_hours(item):.1f}h < {need}h"

    cc = country_of(item)
    allow = [x.strip().upper() for x in s["countries"].split(",") if x.strip()]
    deny = [x.strip().upper() for x in s["deny_countries"].split(",") if x.strip()]
    if allow and cc not in allow:
        return False, "country not allowed"
    if cc and cc in deny:
        return False, "country denied"

    if s["nsb_only"] == "1" and item.get("nsb") is False:
        return False, "sold before"
    return True, "ok"