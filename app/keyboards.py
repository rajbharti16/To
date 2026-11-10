"""All screens button driven, no prices on labels."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import QUICK_COUNTRIES
from app.utils.money import fmt_money


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for row in rows:
        for text, data in row:
            b.button(text=text, callback_data=data)
    b.adjust(*[len(r) for r in rows])
    return b.as_markup()


def main(s: dict, balances: list[dict] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [("▶️ Start Auto-Buy" if s["auto_buy"] != "1" else "⏸ Stop Auto-Buy", "t:auto_buy")],
        [("💳 Wallet", "m:wallet"), ("🎛 Filters", "m:filters")],
        [("🧾 Sessions", "m:sessions"), ("📊 Ledger", "m:ledger")],
        [("📈 Stats", "m:stats"), ("🔄 Buy One Now", "go")],
    ]
    return kb(rows)


def wallet(profile: dict, balances: list[dict]) -> InlineKeyboardMarkup:
    rows = [[("🔄 Refresh", "m:wallet"), ("💱 Exchange", "m:exchange")]]
    if balances:
        rows.append([("📜 Payments", "m:payments")])
    rows.append([("⬅️ Back", "m:main")])
    return kb(rows)


def exchange(balances: list[dict], step: str = "from") -> InlineKeyboardMarkup:
    rows, row = [], []
    for b in balances:
        label = f"{b['currency'].upper()} {fmt_money(b['amount'] - b['hold'], b['currency'])}"
        row.append((label, f"x:{step}:{b['balance_id']}:{b['currency']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("⬅️ Back", "m:wallet")])
    return kb(rows)


def filters(s: dict) -> InlineKeyboardMarkup:
    return kb([
        [(f"Price {s['price_min']}–{s['price_max']}", "m:price")],
        [(f"Spam: {s['spam_mode'].upper()}", "m:spam")],
        [(f"Mail: {s['mail_mode'].upper()}", "m:mail")],
        [(f"2FA: {s['password_mode'].upper()}", "m:pass")],
        [(f"Min session age: {s['session_min_hours']}h", "m:sess")],
        [(f"Session life: {s['session_life_hours']}h", "m:life")],
        [(f"Countries: {s['countries'] or 'ALL'}", "m:countries")],
        [(f"Not sold before: {'YES' if s['nsb_only'] == '1' else 'NO'}", "t:nsb_only")],
        [(f"Auto terminate: {'YES' if s['terminate_on_expire'] == '1' else 'NO'}", "t:terminate_on_expire")],
        [(f"Auto change mail: {'YES' if s['change_mail_on_expire'] == '1' else 'NO'}", "t:change_mail_on_expire")],
        [("⬅️ Back", "m:main")],
    ])


def price() -> InlineKeyboardMarkup:
    return kb([
        [(f"Max {v}", f"s:price_max:{v}") for v in ("0.10", "0.20", "0.30")],
        [(f"Max {v}", f"s:price_max:{v}") for v in ("0.50", "1.00", "2.00")],
        [(f"Min {v}", f"s:price_min:{v}") for v in ("0.05", "0.15", "0.25")],
        [("✏️ Custom max", "in:price_max"), ("✏️ Custom min", "in:price_min")],
        [("⬅️ Back", "m:filters")],
    ])


def pick(prefix: str, values: list[str], back: str = "m:filters") -> InlineKeyboardMarkup:
    rows, row = [], []
    for v in values:
        row.append((v, f"{prefix}:{v}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("⬅️ Back", back)])
    return kb(rows)


def session_ages() -> InlineKeyboardMarkup:
    return pick("s:session_min_hours", ["0", "12", "18", "20", "22", "23", "24", "48"])


def session_lives() -> InlineKeyboardMarkup:
    return pick("s:session_life_hours", ["12", "18", "20", "23", "24", "36", "48"])


def countries(current: str) -> InlineKeyboardMarkup:
    cur = {c.strip().upper() for c in current.split(",") if c.strip()}
    rows, row = [], []
    for c in QUICK_COUNTRIES:
        row.append((f"{'✅' if c in cur else '⬜'} {c}", f"c:{c}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("🗑 Clear", "c:CLEAR"), ("✏️ Custom list", "in:countries")])
    rows.append([("⬅️ Back", "m:filters")])
    return kb(rows)


def sessions(items: list[dict]) -> InlineKeyboardMarkup:
    rows = [[(f"🔒 {p.get('phone') or p['item_id']} — kill", f"k:{p['_id']}")] for p in items]
    rows.append([("⬅️ Back", "m:main")])
    return kb(rows)


def back(to: str = "m:main") -> InlineKeyboardMarkup:
    return kb([[("⬅️ Back", to)]])