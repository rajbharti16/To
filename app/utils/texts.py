"""Message formatting — $ only, no TG wallet, no prices on buttons."""
from app.config import API_HASH, API_ID
from app.utils.filters import account_created_ts
from app.utils.money import fmt_money
from app.utils.timeutil import fmt_age, fmt_dt, fmt_left, now


def _age_at_buy(p: dict) -> str:
    created = p.get("account_created_ts") or account_created_ts(p)
    return fmt_dt(created) if created else "unknown"


def menu_text(s: dict, profile: dict, balance: float, queued: int) -> str:
    return (
        "<b>AccStore</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {profile.get('username', '?')}\n"
        f"💵 <b>{fmt_money(balance, s['currency'])}</b> spendable\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'🟢 running' if s['auto_buy'] == '1' else '🔴 stopped'}"
        f" · queue {queued}\n"
        f"price {s['price_min']}–{s['price_max']} · spam {s['spam_mode']}\n"
        f"age {s['session_min_hours']}–{s['session_max_hours'] or '∞'}h"
        f" · life {s['session_life_hours']}h\n"
        f"mail {s['mail_mode']} · 2fa {s['password_mode']}\n"
        f"include {s['countries'] or 'all'} · exclude {s['deny_countries'] or '—'}"
    )


def filters_text(s: dict) -> str:
    return (
        "<b>Filters</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"price {s['price_min']} – {s['price_max']}\n"
        f"spam {s['spam_mode']} · mail {s['mail_mode']} · 2fa {s['password_mode']}\n"
        f"min age {s['session_min_hours']}h · max age {s['session_max_hours'] or '∞'}h\n"
        f"lifetime after buy {s['session_life_hours']}h\n"
        f"include {s['countries'] or 'all'}\n"
        f"exclude {s['deny_countries'] or '—'}"
    )


def limits_text(s: dict) -> str:
    return (
        "<b>Limits</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"daily cap ${s['daily_spend_cap']} (0 = unlimited)\n"
        f"buys per cycle {s['max_buy_per_cycle']} · poll {s['poll_interval']}s\n"
        f"early clean {s['early_clean_if_aged']}\n"
        f"terminate {s['terminate_on_expire']} · change mail {s['change_mail_on_expire']}\n"
        f"mail source {s['mail_provider']}"
    )


def session_line(p: dict) -> str:
    return f"📱 {p.get('phone') or p['item_id']} · {fmt_left(p.get('expires_at'))}"


def session_detail(p: dict, checked: str = "") -> str:
    created = p.get("account_created_ts") or 0
    age = p.get("age_at_buy_hours") or 0.0
    body = (
        f"📱 <b>{p.get('phone') or '—'}</b>\n"
        f"item <code>{p['item_id']}</code> · {p.get('country') or '??'}\n"
        f"created {fmt_dt(created) if created else 'unknown'}"
        f" · age {fmt_age(age)} at buy\n"
        f"bought {fmt_dt(p.get('started_at'))} for {fmt_money(p['price'])}\n"
        f"lifetime {p.get('target_age_hours', 24):g}h"
        f" · closes {fmt_dt(p.get('expires_at'))}\n"
        f"⏳ {fmt_left(p.get('expires_at'))}\n"
        f"session {p.get('session_state') or 'pending'}"
        f" · checked {fmt_dt(p.get('checked_at')) if p.get('checked_at') else '—'}\n"
        f"📧 {p.get('mail') or '—'}"
    )
    if checked:
        body += f"\n\n{checked}"
    if p.get("note"):
        body += f"\n📝 {p['note'][:200]}"
    return body


def session_file(p: dict) -> str:
    created = p.get("account_created_ts") or 0
    return (
        f"# AccStore session\n"
        f"phone = {p.get('phone')}\n"
        f"item_id = {p['item_id']}\n"
        f"mail = {p.get('mail') or ''}\n"
        f"account_created = {fmt_dt(created) if created else 'unknown'}\n"
        f"age_at_buy_hours = {p.get('age_at_buy_hours', 0)}\n"
        f"bought_at = {fmt_dt(p.get('started_at'))}\n"
        f"expires_at = {fmt_dt(p.get('expires_at'))}\n\n"
        f"from telethon.sync import TelegramClient\n"
        f"from telethon.sessions import StringSession\n\n"
        f"API_ID = {API_ID}\n"
        f"API_HASH = \"{API_HASH}\"\n\n"
        f"session = StringSession(\n    \"{p.get('session_string') or ''}\"\n)\n"
        f"client = TelegramClient(session, API_ID, API_HASH)\n"
        f"client.start()\n"
        f"print(client.get_me())\n"
    )


def stats_text(st: dict) -> str:
    return (
        "<b>Stats</b>\n"
        f"trades {st['total']} · closed {st['done']}\n"
        f"spent {fmt_money(st['spent'])}\n"
        f"revenue {fmt_money(st['revenue'])}\n"
        f"net {fmt_money(st['profit'])} ({st['roi']:.1f}% roi)"
    )


def report_text(rows: list[dict]) -> str:
    if not rows:
        return "<b>Report</b>\nno cycles yet"
    lines = ["<b>Report</b> · last cycles", "━━━━━━━━━━━━━━━━━━━━━━"]
    for r in rows:
        stamp = fmt_dt(r.get("ts"))
        if r.get("error"):
            lines.append(f"{stamp} · ⚠️ {r['error'][:80]}")
            continue
        if r.get("note"):
            lines.append(f"{stamp} · {r['note'][:60]}")
            continue
        top = ", ".join(f"{k}×{v}" for k, v in
                        sorted((r.get("reasons") or {}).items(), key=lambda x: -x[1])[:3])
        lines.append(f"{stamp} · scan {r.get('scanned', 0)}"
                     f" · buy {r.get('bought', 0)} · skip {r.get('skipped', 0)}"
                     + (f" · {top}" if top else ""))
    return "\n".join(lines)


def payment_text(p: dict) -> str:
    sign = "+" if (p.get("operation_type") or "") in ("income", "incoming") else "−"
    return (f"{sign} {fmt_money(abs(float(p.get('amount') or 0)), p.get('currency') or 'usd')}"
            f" · {p.get('operation_type') or 'op'} · {(p.get('comment') or '')[:30]}")