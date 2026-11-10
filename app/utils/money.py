"""Defensive parsers + currency normalisation for LZT profile / balance payloads."""
from decimal import Decimal, InvalidOperation

SYMBOLS = {"usd": "$", "eur": "€", "rub": "₽", "uah": "₴", "gbp": "£",
           "kzt": "₸", "byn": "Br", "cny": "¥", "try": "₺", "jpy": "¥", "brl": "R$"}

ALIASES = {"usdt": "usd", "usdc": "usd", "busd": "usd", "usdtt": "usd",
           "rubr": "rub", "eurc": "eur"}

TELEGRAM_MARKERS = ("telegram", "tg_", "tg-", "tg ")
MARKET_MARKERS = ("market", "trade")


def canon(currency: str) -> str:
    c = (currency or "usd").strip().lower()
    return ALIASES.get(c, c)


def same_currency(a: str, b: str) -> bool:
    return canon(a) == canon(b)


def _num(v, default=0.0) -> float:
    try:
        return float(Decimal(str(v)))
    except (InvalidOperation, TypeError, ValueError):
        return default


def fmt_money(amount: float, currency: str = "usd") -> str:
    cur = (currency or "usd").lower()
    if cur in SYMBOLS:
        return f"{SYMBOLS[cur]}{amount:,.2f}"
    return f"{amount:,.2f} {cur.upper()}"


def parse_user(payload: dict) -> dict:
    u = (payload or {}).get("user") or payload or {}
    return {
        "user_id": u.get("user_id") or u.get("id") or 0,
        "username": u.get("username") or "?",
        "currency": canon(u.get("currency")),
        "balance": _num(u.get("balance")),
        "hold": _num(u.get("hold")),
        "sympathies": _num(u.get("sympathies")),
        "like_count": _num(u.get("like_count")),
        "items_count": _num(u.get("items_count")),
    }


def _kind(entry: dict) -> str:
    """Cosmetic label only — never gates spendability."""
    raw = " ".join(
        str(entry.get(k) or "").lower()
        for k in ("type", "balance_type", "name", "title", "slug", "label")
    )
    if any(m in raw for m in MARKET_MARKERS):
        return "market"
    if any(m in raw for m in TELEGRAM_MARKERS):
        return "telegram"
    return "other"


def _one(entry: dict, fallback_currency: str = "usd") -> dict:
    return {
        "balance_id": int(_num(entry.get("balance_id") or entry.get("id"))),
        "currency": (entry.get("currency") or fallback_currency or "usd").lower(),
        "amount": _num(entry.get("balance") or entry.get("amount") or entry.get("value")),
        "hold": _num(entry.get("hold")),
        "kind": _kind(entry),
    }


def parse_balances(payload: dict) -> list[dict]:
    """
    Normalise any balance-ish payload. Order of attempts:
      balances/wallets list → dict of currency → user object → payload root.
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
                out.append({"balance_id": 0, "currency": cur.lower(), "amount": _num(val),
                            "hold": 0.0, "kind": "other"})

    if not out:
        user = payload.get("user")
        if isinstance(user, dict) and ("balance" in user or "hold" in user):
            out = [_one(user)]

    if not out and any(k in payload for k in ("balance", "hold", "currency")):
        out = [_one(payload)]

    return [b for b in out if b["currency"]]


def _rank(b: dict) -> tuple:
    order = {"market": 0, "other": 1, "telegram": 2}
    return (order.get(b["kind"], 1), -(b["amount"] - b["hold"]))


def spendable(balances: list[dict], currency: str) -> float:
    """Free amount in that currency across every balance."""
    return sum(max(0.0, b["amount"] - b["hold"])
               for b in balances if same_currency(b["currency"], currency))


def pick_for_buy(balances: list[dict], currency: str, price: float) -> dict | None:
    """Cheapest-risk balance able to cover `price` (market labels preferred)."""
    candidates = [
        b for b in sorted(balances, key=_rank)
        if same_currency(b["currency"], currency) and (b["amount"] - b["hold"]) >= price
    ]
    return candidates[0] if candidates else None


def total_any(balances: list[dict], currency: str) -> float:
    return spendable(balances, currency)