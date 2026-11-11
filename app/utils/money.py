"""Balance parsing that survives unknown payload shapes."""
from decimal import Decimal, InvalidOperation

SYMBOLS = {"usd": "$", "eur": "€", "rub": "₽", "uah": "₴", "gbp": "£",
           "kzt": "₸", "byn": "Br", "cny": "¥", "try": "₺", "jpy": "¥", "brl": "R$"}

ALIASES = {"usdt": "usd", "usdc": "usd", "busd": "usd", "usdtt": "usd",
           "rubr": "rub", "eurc": "eur"}

TELEGRAM_MARKERS = ("telegram", "tg", "wallet")
MARKET_MARKERS = ("market", "main", "trade", "spend")

CUR_KEYS = ("currency", "cur", "code", "currency_code")
AMT_KEYS = ("balance", "amount", "value", "sum", "available", "free")
HOLD_KEYS = ("hold", "held", "frozen", "pending", "locked")
ID_KEYS = ("balance_id", "id", "wallet_id", "balanceid")

# only these describe what a balance *is* — avoids "tg" matching inside usernames
_ID_FIELDS = ("balance_type", "type", "kind", "slug", "title", "name", "label",
              "description", "payment_method")


def canon(currency: str) -> str:
    c = (currency or "usd").strip().lower()
    return ALIASES.get(c, c)


def same_currency(a: str, b: str) -> bool:
    return canon(a) == canon(b)


def _num(v, default=None):
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
        "balance": _num(u.get("balance"), 0.0),
        "hold": _num(u.get("hold"), 0.0),
        "sympathies": _num(u.get("sympathies"), 0.0),
        "like_count": _num(u.get("like_count"), 0.0),
        "items_count": _num(u.get("items_count"), 0.0),
    }


def _is_currency(v) -> bool:
    return isinstance(v, str) and 2 <= len(v) <= 5 and v.replace("_", "").isalpha()


def _pick(d: dict, keys) -> tuple[str | None, object]:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return k, d[k]
    return None, None


def _kind(d: dict) -> str:
    """Classify by identity fields only; everything else is generic."""
    raw = " ".join(str(d.get(k)).lower() for k in _ID_FIELDS if d.get(k) not in (None, ""))
    if not raw:
        raw = " ".join(str(v).lower() for v in d.values() if isinstance(v, str))
    if any(m in raw for m in TELEGRAM_MARKERS):
        return "telegram"
    if any(m in raw for m in MARKET_MARKERS):
        return "market"
    return "other"


def _label(d: dict) -> str:
    for k in ("title", "name", "label", "type", "balance_type", "slug", "description"):
        v = d.get(k)
        if isinstance(v, str) and v.strip() and not _is_currency(v):
            return v.strip()[:24]
    return ""


def _entry(d: dict, currency: str) -> dict:
    kind = _kind(d)
    _, hold = _pick(d, HOLD_KEYS)
    _, bid = _pick(d, ID_KEYS)
    return {
        "balance_id": int(_num(bid, 0) or 0),
        "currency": (currency or "usd").lower(),
        "amount": _num(_pick(d, AMT_KEYS)[1], 0.0),
        "hold": _num(hold, 0.0),
        "kind": kind,
        "label": _label(d) or {"market": "Market balance", "telegram": "TG wallet"}.get(kind, "Balance"),
        "usable_for_buy": kind != "telegram",
    }


def _walk(node, out: list, depth: int = 0):
    if depth > 6:
        return
    if isinstance(node, dict):
        _, cur = _pick(node, CUR_KEYS)
        if _is_currency(cur) and _pick(node, AMT_KEYS)[1] is not None:
            out.append(_entry(node, cur))
            return
        for v in node.values():
            _walk(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out, depth + 1)


def parse_balances(payload: dict) -> list[dict]:
    """Find every {currency, amount} object anywhere in the payload, deduped."""
    out: list[dict] = []
    _walk(payload or {}, out)

    seen, unique = set(), []
    for b in out:
        key = (b["balance_id"], b["currency"], round(b["amount"], 6), b["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(b)

    if not unique:
        user = (payload or {}).get("user") or {}
        if _is_currency(user.get("currency")) and user.get("balance") is not None:
            unique = [_entry(user, user["currency"])]
    return unique


def free_of(b: dict) -> float:
    return max(0.0, float(b.get("amount", 0.0)) - float(b.get("hold", 0.0)))


def _rank(b: dict) -> tuple:
    order = {"market": 0, "other": 1, "telegram": 2}
    has_id = 0 if b.get("balance_id") else 1
    return (order.get(b["kind"], 1), has_id, -free_of(b))


def spendable(balances: list[dict], currency: str) -> float:
    return sum(free_of(b) for b in balances
               if b["usable_for_buy"] and same_currency(b["currency"], currency))


def total_of(payload: dict, currency: str) -> float:
    """Real free money straight from the user object."""
    user = parse_user(payload)
    if same_currency(user["currency"], currency):
        return max(0.0, user["balance"] - user["hold"])
    return 0.0


def pick_for_buy(balances: list[dict], currency: str, price: float) -> dict | None:
    """Best balance covering `price`. Real ids and market funds first."""
    cands = [b for b in sorted(balances, key=_rank)
             if b["usable_for_buy"] and same_currency(b["currency"], currency)
             and free_of(b) >= price]
    return cands[0] if cands else None