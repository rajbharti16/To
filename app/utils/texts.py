"""Message formatting — $ only, no TG wallet, no prices on buttons."""
from app.utils.filters import session_hours
from app.utils.money import fmt_money


def _remaining(p: dict) -> str:
    left = p["expires_at"] - int(__import__("time").time())
    if left <= 0:
        return "cleaning"
    h, m = divmod(left // 60, 60)
    return f"{h}h {m:02d}m"


def menu_text(s: dict, profile: dict, balance: float, queued: int) -> str:
    return (
        "<b>AccStore</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {profile.get('username', '?')}\n"
        f"💳 <b>{fmt_money(balance, s['currency'])}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'🟢 running' if s['auto_buy'] == '1' else '🔴 stopped'}"
        f" · queue {queued}\n"
        f"price {s['price_min']}–{s['price_max']} · spam {s['spam_mode']}\n"
        f"target {s['session_life_hours']}h · mail {s['mail_mode']} · 2fa {s['password_mode']}\n"
        f"include {s['countries'] or 'all'} · exclude {s['deny_countries'] or '—'}"
    )


def filters_text(s: dict) -> str:
    return (
        "<b>Filters</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"price {s['price_min']} – {s['price_max']}\n"
        f"spam {s['spam_mode']} · mail {s['mail_mode']} · 2fa {s['password_mode']}\n"
        f"min age {s['session_min_hours']}h · target {s['session_life_hours']}h\n"
        f"include {s['countries'] or 'all'}\n"
        f"exclude {s['deny_countries'] or '—'}"
    )


def session_line(p: dict) -> str:
    return f"📱 {p.get('phone') or p['item_id']} · {_remaining(p)}"


def session_detail(p: dict) -> str:
    return (
        f"📱 <b>{p.get('phone') or '—'}</b>\n"
        f"item <code>{p['item_id']}</code> · {p.get('country') or '??'}\n"
        f"bought {fmt_money(p['price'])}\n"
        f"age at buy {p.get('age_at_buy_hours', 0):.2f}h → target {p.get('target_age_hours', 24):g}h\n"
        f"⏳ {_remaining(p)}\n"
        f"📧 {p.get('mail') or '—'}"
    )


def session_file(p: dict) -> str:
    return (
        f"# AccStore session\n"
        f"phone = {p.get('phone')}\n"
        f"item_id = {p['item_id']}\n"
        f"mail = {p.get('mail') or ''}\n"
        f"age_at_buy_hours = {p.get('age_at_buy_hours', 0)}\n\n"
        f"from telethon.sync import TelegramClient\n"
        f"from telethon.sessions import StringSession\n\n"
        f"session = StringSession(\n    \"{p.get('session_string') or ''}\"\n)\n"
        f"client = TelegramClient(session, API_ID, API_HASH)\n"
        f"client.start()\n"
        f"print(client.get_me())\n"
    )


def stats_text(st: dict) -> str:
    return (
        "<b>Stats</b>\n"
        f"trades {st['total']}\n"
        f"spent {fmt_money(st['spent'])}\n"
        f"revenue {fmt_money(st['revenue'])}\n"
        f"net {fmt_money(st['profit'])} ({st['roi']:.1f}% roi)"
    )


def payment_text(p: dict) -> str:
    sign = "+" if (p.get("operation_type") or "") in ("income", "incoming") else "−"
    return (f"{sign} {fmt_money(abs(float(p.get('amount') or 0)), p.get('currency') or 'usd')}"
            f" · {p.get('operation_type') or 'op'} · {(p.get('comment') or '')[:30]}")