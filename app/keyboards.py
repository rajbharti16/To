"""Clean button-only navigation."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.money import fmt_money


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for row in rows:
        for text, data in row:
            b.button(text=text, callback_data=data)
    b.adjust(*[len(r) for r in rows])
    return b.as_markup()


def main(s: dict) -> InlineKeyboardMarkup:
    return kb([
        [("⏸ Stop" if s["auto_buy"] == "1" else "▶️ Start", "t:auto_buy")],
        [("Filters", "m:filters"), ("Sessions", "m:sessions")],
        [("Wallet", "m:wallet"), ("Stats", "m:stats")],
    ])


def filters(s: dict) -> InlineKeyboardMarkup:
    return kb([
        [(f"Price {s['price_min']}–{s['price_max']}", "m:price")],
        [(f"Spam: {s['spam_mode']}", "m:spam"), (f"Mail: {s['mail_mode']}", "m:mail")],
        [(f"2FA: {s['password_mode']}", "m:pass"), (f"Target: {s['session_life_hours']}h", "m:life")],
        [("Include countries", "in:countries"), ("Exclude countries", "in:deny_countries")],
        [(f"Min age {s['session_min_hours']}h", "m:sess"),
         (f"Resold {'on' if s['nsb_only'] == '1' else 'off'}", "t:nsb_only")],
        [("Back", "m:main")],
    ])


def price() -> InlineKeyboardMarkup:
    return kb([
        [(f"{v}", f"s:price_max:{v}") for v in ("0.10", "0.30", "1.00")],
        [(f"{v}", f"s:price_min:{v}") for v in ("0.05", "0.15", "0.25")],
        [("custom max", "in:price_max"), ("custom min", "in:price_min")],
        [("Back", "m:filters")],
    ])


def pick(prefix: str, values: list[str]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for v in values:
        row.append((v, f"{prefix}:{v}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("Back", "m:filters")])
    return kb(rows)


def targets() -> InlineKeyboardMarkup:
    return pick("s:session_life_hours", ["12", "20", "23", "24", "36", "48"])


def floors() -> InlineKeyboardMarkup:
    return pick("s:session_min_hours", ["0", "12", "18", "23", "24"])


def sessions(items: list[dict]) -> InlineKeyboardMarkup:
    rows = [[(f"📱 {p.get('phone') or p['item_id']}", f"v:{p['_id']}")] for p in items]
    rows.append([("Back", "m:main")])
    return kb(rows)


def session_detail(p: dict) -> InlineKeyboardMarkup:
    return kb([
        [("Session file", f"f:{p['_id']}")],
        [("Clean now", f"k:{p['_id']}")],
        [("Back", "m:sessions")],
    ])


def wallet(balances: list[dict]) -> InlineKeyboardMarkup:
    rows = [[("Refresh", "m:wallet"), ("Payments", "m:payments")]]
    if len(balances) > 1:
        rows.append([("Exchange", "m:exchange")])
    rows.append([("Back", "m:main")])
    return kb(rows)


def exchange(balances: list[dict], step: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for b in balances:
        row.append((f"{fmt_money(b['amount'] - b['hold'], b['currency'])} {b['currency'].upper()}",
                    f"x:{step}:{b['balance_id']}:{b['currency']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("Back", "m:wallet")])
    return kb(rows)


def back(to: str = "m:main") -> InlineKeyboardMarkup:
    return kb([[("Back", to)]])