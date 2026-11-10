"""Message formatting — price only in menu text, never on buttons."""

def menu_text(s: dict) -> str:
    return (
        "🎛 <b>AccStore — LZT Auto Buyer</b>\n"
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
        f"Spent: ${st['spent']:.2f}\n"
        f"Revenue: ${st['revenue']:.2f}\n"
        f"Net: ${st['profit']:+.2f} ({st['roi']:.1f}% ROI)"
    )