"""Message formatting — prices only in body text, never on buttons."""
from app.utils.money import fmt_money


def wallet_text(profile: dict, balances: list[dict]) -> str:
    lines = [
        "💳 <b>Wallet</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>{profile.get('username', '?')}</b> · id <code>{profile.get('user_id', 0)}</code>",
        f"💬 Sympathies: {int(profile.get('sympathies', 0))}",
    ]
    if balances:
        for b in balances:
            free = b["amount"] - b["hold"]
            line = f"• {b['currency'].upper()}: <b>{fmt_money(free, b['currency'])}</b>"
            if b["hold"]:
                line += f" (hold {fmt_money(b['hold'], b['currency'])})"
            lines.append(line)
    else:
        lines.append("• no balances returned")
    return "\n".join(lines)


def menu_text(s: dict, profile: dict, balances: list[dict]) -> str:
    head = " · ".join(
        f"{b['currency'].upper()} {fmt_money(b['amount'] - b['hold'], b['currency'])}"
        for b in balances
    ) or "n/a"
    return (
        "🎛 <b>AccStore — LZT Auto Buyer</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{profile.get('username', '?')}</b>\n"
        f"💳 {head}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Auto-buy: {'🟢 RUNNING' if s['auto_buy'] == '1' else '🔴 STOPPED'}\n"
        f"Price: {s['price_min']} – {s['price_max']} {s['currency'].upper()}\n"
        f"Spam: {s['spam_mode'].upper()} · Mail: {s['mail_mode'].upper()}\n"
        f"Min session age: {s['session_min_hours']}h · Life: {s['session_life_hours']}h\n"
        f"Countries: {s['countries'] or 'ALL'}\n"
        f"Daily cap: {s['daily_spend_cap']} {s['currency'].upper()}"
    )


def stats_text(st: dict) -> str:
    return (
        "📈 <b>Ledger stats</b>\n"
        f"Trades: {st['total']}\n"
        f"Spent: {fmt_money(st['spent'])}\n"
        f"Revenue: {fmt_money(st['revenue'])}\n"
        f"Net: {fmt_money(st['profit'])} ({st['roi']:.1f}% ROI)"
    )


def payment_text(p: dict) -> str:
    sign = "+" if (p.get("operation_type") or "") in ("income", "incoming") else "−"
    return (
        f"{sign} {fmt_money(abs(float(p.get('amount') or 0)), p.get('currency') or 'usd')}"
        f" · <code>{p.get('operation_type') or 'op'}</code>"
        f" · {(p.get('comment') or '')[:40]}"
    )