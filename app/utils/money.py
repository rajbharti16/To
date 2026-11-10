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
    """
    Normalise GET /balance/exchange. Handles:
      {"balances": [{balance_id, currency, balance, hold}]}
      {"balances": {"usd": 12.5, "rub": 900}}
      {"user": {"balance": ..., "currency": ...}}
    """
    payload = payload or {}
    out: list[dict] = []

    raw = payload.get("balances") or payload.get("wallets")
    if isinstance(raw, list):
        out = [_one(e) for e in raw if isinstance(e, dict)]
    elif isinstance(raw, dict):
        for cur, val in raw.items():
            if isinstance(val, dict):
                out.append(_one(val, cur))
            else:
                out.append({"balance_id": 0, "currency": cur.lower(), "amount": _num(val), "hold": 0.0})

    if not out:
        user = payload.get("user") or {}
        if user:
            out = [_one(user)]

    return [b for b in out if b["currency"]]