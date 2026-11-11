"""Button-only navigation — every screen edits the current message."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.money import free_of, fmt_money


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    widths = []
    for row in rows:
        if not row:
            continue
        for text, data in row:
            b.button(text=text, callback_data=data)
        widths.append(len(row))
    if widths:
        b.adjust(*widths)
    return b.as_markup()


def main(s: dict) -> InlineKeyboardMarkup:
    return kb([
        [("⏸ Stop" if s["auto_buy"] == "1" else "▶️ Start", "t:auto_buy")],
        [("Filters", "m:filters"), ("Sessions", "m:sessions")],
        [("Wallet", "m:wallet"), ("Report", "m:report")],
        [("Stats", "m:stats")],
    ])


def filters(s: dict) -> InlineKeyboardMarkup:
    return kb([
        [(f"Price {s['price_min']}–{s['price_max']}", "m:price")],
        [(f"Spam: {s['spam_mode']}", "m:spam"), (f"Mail: {s['mail_mode']}", "m:mail")],
        [(f"2FA: {s['password_mode']}", "m:pass"), (f"Target: {s['session_life_hours']}h", "m:life")],
        [(f"Min age {s['session_min_hours']}h", "in:session_min_hours"),
         (f"Max age {s['session_max_hours']}h", "in:session_max_hours")],
        [("Include countries", "in:countries"), ("Exclude countries", "in:deny_countries")],
        [(f"Resold {'on' if s['nsb_only'] == '1' else 'off'}", "t:nsb_only"),
         ("Limits", "m:limits")],
        [("Back", "m:main")],
    ])


def price() -> InlineKeyboardMarkup:
    return kb([
        [(f"{v}", f"s:price_max:{v}") for v in ("0.10", "0.30", "1.00")],
        [(f"{v}", f"s:price_min:{v}") for v in ("0.05", "0.15", "0.25")],
        [("custom max", "in:price_max"), ("custom min", "in:price_min")],
        [("Back", "m:filters")],
    ])


def limits(s: dict) -> InlineKeyboardMarkup:
    return kb([
        [(f"Daily cap ${s['daily_spend_cap']}", "in:daily_spend_cap")],
        [(f"Buys/cycle {s['max_buy_per_cycle']}", "in:max_buy_per_cycle"),
         (f"Poll {s['poll_interval']}s", "in:poll_interval")],
        [(f"Early clean {'on' if s['early_clean_if_aged'] == '1' else 'off'}",
          "t:early_clean_if_aged"),
         (f"Terminate {'on' if s['terminate_on_expire'] == '1' else 'off'}",
          "t:terminate_on_expire")],
        [(f"Change mail {'on' if s['change_mail_on_expire'] == '1' else 'off'}",
          "t:change_mail_on_expire"),
         (f"Mail src {s['mail_provider']}", "m:mailprov")],
        [("Back", "m:filters")],
    ])


def pick(prefix: str, values: list[str], back_to: str = "m:filters") -> InlineKeyboardMarkup:
    rows, row = [], []
    for v in values:
        row.append((v, f"{prefix}:{v}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("Back", back_to)])
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
        [("Session file", f"f:{p['_id']}"), ("Check", f"c:{p['_id']}")],
        [("Clean now", f"k:{p['_id']}"), ("Refresh", f"v:{p['_id']}")],
        [("Back", "m:sessions")],
    ])


def wallet(balances: list[dict]) -> InlineKeyboardMarkup:
    rows = [[("Refresh", "m:wallet"), ("Payments", "m:payments")]]
    if len(balances) > 1:
        rows.append([("Exchange", "m:exchange")])
    rows.append([("Back", "m:main")])
    return kb(rows)


def exchange(pool: list[dict], step: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, b in enumerate(pool):
        row.append((f"{fmt_money(free_of(b), b['currency'])} {b['currency'].upper()}",
                    f"x:{step}:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("Back", "m:wallet")])
    return kb(rows)


def report() -> InlineKeyboardMarkup:
    return kb([[("Refresh", "r:view")], [("Export ledger", "l:csv")], [("Back", "m:main")]])


def back(to: str = "m:main") -> InlineKeyboardMarkup:
    return kb([[("Back", to)]])