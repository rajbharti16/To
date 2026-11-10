"""Defensive parsers for LZT profile / balance payloads."""
from decimal import Decimal, InvalidOperation

SYMBOLS = {"usd": "$", "eur": "€", "rub": "₽", "uah": "₴", "gbp": "£",
           "kzt": "₸", "byn": "Br", "cny": "¥", "try": "₺", "jpy": "¥", "brl": "R$"}


def _num(v, default=0.0) -> float:
    try:
        return float(Decimal(str(v)))
    except (InvalidOperation, TypeError, ValueError):
        return default


def fmt_money(amount: float, currency: str = "usd") -> str:
    cur = (currency or "usd").lower()
    return f"{SYMBOLS.get(cur, cur.upper() + ' ')}{amount:,.2f}"


def parse_user(payload: dict) -> dict:
    """Extract the useful parts of GET /me, tolerating shape changes."""
    u = (payload or {}).get("user") or payload or {}
    return {
        "user_id": u.get("user_id") or u.get("id") or 0,
        "username": u.get("username") or "?",
        "currency": (u.get("currency") or "usd").lower(),
        "balance": _num(u.get("balance")),
        "hold": _num(u.get("hold")),
        "sympathies": _num(u.get("sympathies")),
        "like_count": _num(u.get("like_count")),
        "items_count": _num(u.get("items_count")),
    }


def _one(entry: dict, fallback_currency: str = "usd") -> dict:
    return {
        "balance_id": int(_num(entry.get("balance_id") or entry.get("id"))),
        "currency": (entry.get("currency") or fallback_currency).lower(),
        "amount": _num(entry.get("balance") or entry.get("amount")),
        "hold": _num(entry.get("hold")),
    }


def parse_balances(payload: dict) -> list[dict]:
    """Parse LZT balance response with converted values."""
    payload = payload or {}
    out = []

    raw = payload.get("to") or payload.get("from") or {}

    if isinstance(raw, dict):
        for key, item in raw.items():
            if not isinstance(item, dict):
                continue

            out.append({
                "balance_id": item.get("balance_id", key),
                "currency": (
                    item.get("custom_title")
                    or item.get("title")
                    or str(key)
                ),
                "amount": _num(item.get("balance")),
                "hold": _num(item.get("hold")),
                "converted_amount": _num(item.get("convertedBalance")),
            })

    return out