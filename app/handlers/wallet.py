import html
import math
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.deps import lzt
from app.handlers.menu import show
from app.lzt import LztError
from app.utils.money import fmt_money
from app.utils.texts import payment_text

router = Router()

EXCH_TTL = 300.0
EXCH: dict[int, dict] = {}


def _st(uid: int) -> dict:
    st = EXCH.get(uid)
    if not st:
        return {}
    if time.time() - st.get("ts", 0.0) > EXCH_TTL:
        EXCH.pop(uid, None)
        return {}
    return st


def _touch(st: dict):
    st["ts"] = time.time()


def _usable(balances: list[dict]) -> list[dict]:
    return [b for b in balances if b.get("usable_for_buy")]


def _wallet_text(balances: list[dict]) -> str:
    if not balances:
        return "<b>Wallet</b>\nno balances"
    lines, totals = [], {}
    for b in balances:
        free = b.get("amount", 0.0) - b.get("hold", 0.0)
        totals[b["currency"]] = totals.get(b["currency"], 0.0) + free
        row = f"• {b['label']} {fmt_money(free, b['currency'])}"
        if b.get("hold"):
            row += f" · hold {fmt_money(b['hold'], b['currency'])}"
        if not b.get("usable_for_buy"):
            row += " · not usable"
        lines.append(row)
    total_line = " · ".join(f"{fmt_money(v, c)}" for c, v in totals.items() if v > 0)
    head = f"<b>Wallet</b>\n━━━━━━━━━━━━━━━━━━━━━━"
    if total_line:
        head += f"\nfree: {total_line}"
    return head + "\n" + "\n".join(lines)


async def _balances_or_reply(target, edit: bool = False) -> list[dict] | None:
    try:
        return await lzt.balances()
    except LztError as e:
        text = f"error <code>{html.escape(str(e))}</code>"
        if edit:
            await show(target, text, kb.back("m:menu"))
        else:
            await target.answer(text)
        return None


@router.message(Command("wallet"))
async def cmd_wallet(m: Message):
    EXCH.pop(m.from_user.id, None)
    balances = await _balances_or_reply(m)
    if balances is None:
        return
    await m.answer(_wallet_text(balances), reply_markup=kb.wallet(balances))


@router.callback_query(F.data == "m:wallet")
async def cb_wallet(cq: CallbackQuery):
    EXCH.pop(cq.from_user.id, None)
    balances = await _balances_or_reply(cq, edit=True)
    if balances is None:
        return await cq.answer()
    await show(cq, _wallet_text(balances), kb.wallet(balances))
    await cq.answer()


@router.callback_query(F.data == "m:payments")
async def cb_payments(cq: CallbackQuery):
    try:
        rows = await lzt.payments(page=1)
    except LztError as e:
        await show(cq, f"error <code>{html.escape(str(e))}</code>", kb.back("m:wallet"))
        return await cq.answer()
    body = "\n".join(payment_text(p) for p in rows[:10]) or "nothing"
    await show(cq, f"<b>Payments</b>\n{body}", kb.back("m:wallet"))
    await cq.answer()


@router.callback_query(F.data == "m:exchange")
async def cb_exchange(cq: CallbackQuery):
    balances = await _balances_or_reply(cq, edit=True)
    if balances is None:
        return await cq.answer()
    usable = _usable(balances)
    if len(usable) < 2:
        await show(cq, "need two usable balances", kb.back("m:wallet"))
        return await cq.answer()
    EXCH[cq.from_user.id] = {"ts": time.time()}
    await show(cq, "<b>Exchange</b> — source balance", kb.exchange(usable, "from"))
    await cq.answer()


@router.callback_query(F.data.startswith("x:"))
async def cb_step(cq: CallbackQuery):
    parts = cq.data.split(":", 3)
    if len(parts) < 4:
        return await cq.answer("bad callback", show_alert=True)
    _, step, bid_raw, cur = parts
    try:
        bid = int(bid_raw)
    except ValueError:
        return await cq.answer("bad balance id", show_alert=True)

    st = _st(cq.from_user.id)
    if not st:
        return await cq.answer("restart exchange", show_alert=True)
    _touch(st)

    balances = await _balances_or_reply(cq, edit=True)
    if balances is None:
        return await cq.answer()
    if not any(b["balance_id"] == bid for b in balances):
        return await cq.answer("balance gone, restart", show_alert=True)

    if step == "from":
        st.update({"from": bid, "cur": cur.upper(), "busy": False})
        st.pop("to", None)
        pool = [b for b in _usable(balances) if b["balance_id"] != bid]
        if not pool:
            return await cq.answer("no target balance", show_alert=True)
        await show(cq, f"from <b>{cur.upper()}</b> — pick target", kb.exchange(pool, "to"))
        return await cq.answer()

    if step != "to":
        return await cq.answer("bad step", show_alert=True)
    st["to"] = bid
    st["to_cur"] = cur.upper()
    src = next((b for b in balances if b["balance_id"] == st["from"]), {})
    avail = max(0.0, src.get("amount", 0.0) - src.get("hold", 0.0))
    await show(
        cq,
        f"<b>{st['cur']} → {st['to_cur']}</b>\n"
        f"available: {fmt_money(avail, st['cur'])}\n\n"
        f"Send amount in <b>{st['cur']}</b>, or tap:",
        kb.kb([[("10", "xa:10"), ("50", "xa:50"), ("100", "xa:100")],
               [("Max", "xa:max"), ("Cancel", "xc")]]),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("xa:"))
async def cb_amount_btn(cq: CallbackQuery):
    raw = cq.data.split(":", 1)[1]
    st = _st(cq.from_user.id)
    if not st or "to" not in st:
        return await cq.answer("restart exchange", show_alert=True)
    if st.get("busy"):
        return await cq.answer("busy…")

    if raw == "max":
        balances = await _balances_or_reply(cq, edit=True)
        if balances is None:
            return await cq.answer()
        src = next((b for b in balances if b["balance_id"] == st["from"]), None)
        if not src:
            return await cq.answer("source gone, restart", show_alert=True)
        amount = max(0.0, src.get("amount", 0.0) - src.get("hold", 0.0))
    else:
        try:
            amount = float(raw)
        except ValueError:
            return await cq.answer("bad amount", show_alert=True)

    msg = await _do(cq.from_user.id, cq.bot, amount)
    await cq.answer("done" if not msg.startswith("⚠️") else "failed", show_alert=False)
    await cq.message.answer(msg)


@router.callback_query(F.data == "xc")
async def cb_exch_cancel(cq: CallbackQuery):
    EXCH.pop(cq.from_user.id, None)
    await show(cq, "exchange cancelled", kb.back("m:wallet"))
    await cq.answer()


@router.message(Command("amount"))
async def cmd_amount(m: Message):
    """Order-independent amount entry: /amount 25"""
    arg = (m.text or "").split(maxsplit=1)
    if len(arg) < 2:
        return await m.answer("usage: <code>/amount 25</code>")
    try:
        amount = float(arg[1].replace(",", ".").strip())
    except ValueError:
        return await m.answer("number expected")
    await m.answer(await _do(m.from_user.id, m.bot, amount))


# NOTE: register this router BEFORE handlers/filters.py — its catch-all F.text
# would otherwise swallow the amount. /amount works regardless of order.
@router.message(F.text, lambda m: bool(_st(m.from_user.id)) and "to" in _st(m.from_user.id))
async def on_amount(m: Message):
    if (m.text or "").startswith("/"):
        return
    try:
        amount = float(m.text.replace(",", ".").strip())
    except ValueError:
        return await m.answer("number expected · /cancel")
    await m.answer(await _do(m.from_user.id, m.bot, amount))


async def _do(uid: int, bot, amount: float) -> str:
    st = _st(uid)
    if not st or "from" not in st or "to" not in st:
        return "⚠️ restart exchange"
    if st.get("busy"):
        return "⚠️ already processing"
    if not math.isfinite(amount) or amount <= 0:
        return "⚠️ amount must be a positive number"

    try:
        balances = await lzt.balances()
    except LztError as e:
        return f"⚠️ {html.escape(str(e))}"
    src = next((b for b in balances if b["balance_id"] == st["from"]), None)
    if not src:
        EXCH.pop(uid, None)
        return "⚠️ source balance gone, restart"
    avail = max(0.0, src.get("amount", 0.0) - src.get("hold", 0.0))
    if amount < 0.01:
        return f"⚠️ minimum is {fmt_money(0.01, st['cur'])}"
    if amount > avail + 1e-9:
        return f"⚠️ only {fmt_money(avail, st['cur'])} available"

    st["busy"] = True
    try:
        await lzt.exchange(st["from"], st["to"], amount)
    except LztError as e:
        st["busy"] = False          # state survives a failure → user can retry
        return f"⚠️ failed: {html.escape(str(e))}"

    EXCH.pop(uid, None)
    fresh = await lzt.balances()
    return (f"✅ exchanged {fmt_money(amount, st['cur'])} → {st['to_cur']}\n\n"
            + _wallet_text(fresh))