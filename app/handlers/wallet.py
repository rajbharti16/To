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
from app.utils.money import fmt_money, free_of
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


def has_pending(uid: int) -> bool:
    return bool(_st(uid)) and "to_id" in _st(uid)


def _usable(balances: list[dict]) -> list[dict]:
    return [b for b in balances if b.get("usable_for_buy") and free_of(b) > 0]


def _wallet_text(balances: list[dict]) -> str:
    usable = _usable(balances)
    hidden = len(balances) - len(usable)
    head = "<b>Wallet</b> · spendable\n━━━━━━━━━━━━━━━━━━━━━━"
    if not usable:
        return head + "\nno spendable market balance"
    lines, totals = [], {}
    for b in usable:
        free = free_of(b)
        totals[b["currency"]] = totals.get(b["currency"], 0.0) + free
        row = f"• {b['label']} {fmt_money(free, b['currency'])}"
        if b.get("hold"):
            row += f" · hold {fmt_money(b['hold'], b['currency'])}"
        lines.append(row)
    total_line = " · ".join(fmt_money(v, c) for c, v in totals.items() if v > 0)
    if total_line:
        head += f"\nfree: <b>{total_line}</b>"
    body = head + "\n" + "\n".join(lines)
    if hidden:
        body += f"\n<i>{hidden} non-spendable balance(s) hidden</i>"
    return body


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


async def _deliver(bot, uid: int, amount: float, chat_id: int = 0, message_id: int = 0):
    msg = await _do(uid, bot, amount)
    text, markup = msg, kb.back("m:wallet")
    if chat_id and message_id:
        try:
            await bot.edit_message_text(text=text, chat_id=chat_id,
                                        message_id=message_id, reply_markup=markup,
                                        disable_web_page_preview=True)
            return
        except Exception:
            pass
    await bot.send_message(chat_id or uid, text, reply_markup=markup,
                           disable_web_page_preview=True)


@router.message(Command("wallet"))
async def cmd_wallet(m: Message):
    EXCH.pop(m.from_user.id, None)
    balances = await _balances_or_reply(m)
    if balances is None:
        return
    await m.answer(_wallet_text(balances), reply_markup=kb.wallet(_usable(balances)))


@router.callback_query(F.data == "m:wallet")
async def cb_wallet(cq: CallbackQuery):
    EXCH.pop(cq.from_user.id, None)
    balances = await _balances_or_reply(cq, edit=True)
    if balances is None:
        return await cq.answer()
    await show(cq, _wallet_text(balances), kb.wallet(_usable(balances)))
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
    pool = _usable(balances)
    if len(pool) < 2:
        await show(cq, "need two spendable balances", kb.back("m:wallet"))
        return await cq.answer()
    EXCH[cq.from_user.id] = {"ts": time.time(), "pool": pool}
    await show(cq, "<b>Exchange</b> — source balance", kb.exchange(pool, "from"))
    await cq.answer()


@router.callback_query(F.data.startswith("x:"))
async def cb_step(cq: CallbackQuery):
    parts = cq.data.split(":")
    if len(parts) != 3:
        return await cq.answer("bad callback", show_alert=True)
    _, step, idx_raw = parts
    st = _st(cq.from_user.id)
    if not st:
        return await cq.answer("restart exchange", show_alert=True)
    try:
        idx = int(idx_raw)
    except ValueError:
        return await cq.answer("bad index", show_alert=True)

    balances = await _balances_or_reply(cq, edit=True)
    if balances is None:
        return await cq.answer()

    live = {b["balance_id"]: b for b in _usable(balances) if b.get("balance_id")}
    pool = [b for b in st.get("pool") or [] if b.get("balance_id") in live]
    if not pool:
        EXCH.pop(cq.from_user.id, None)
        return await cq.answer("balances changed, restart", show_alert=True)
    st["pool"] = pool
    if idx >= len(pool):
        return await cq.answer("pick again", show_alert=True)

    _touch(st)
    pick = pool[idx]

    if step == "from":
        st["from_id"] = pick["balance_id"]
        st["cur"] = pick["currency"]
        st.pop("to_id", None)
        targets = [b for b in pool if b["balance_id"] != st["from_id"]]
        if not targets:
            return await cq.answer("no target balance", show_alert=True)
        await show(cq, f"from <b>{st['cur'].upper()}</b> — pick target",
                   kb.exchange(targets, "to"))
        return await cq.answer()

    if step != "to":
        return await cq.answer("bad step", show_alert=True)
    if "from_id" not in st:
        return await cq.answer("pick a source first", show_alert=True)

    st["to_id"] = pick["balance_id"]
    st["to_cur"] = pick["currency"]
    src = live.get(st["from_id"])
    avail = free_of(src) if src else 0.0
    msg = await cq.message.edit_text(
        f"<b>{st['cur']} → {st['to_cur']}</b>\n"
        f"available: {fmt_money(avail, st['cur'])}\n\n"
        f"Send amount in <b>{st['cur']}</b>, or tap:",
        reply_markup=kb.kb([[("10", "xa:10"), ("50", "xa:50"), ("100", "xa:100")],
                            [("Max", "xa:max"), ("Cancel", "xc")]]))
    st["prompt"] = (msg.chat.id, msg.message_id)
    await cq.answer()


@router.callback_query(F.data.startswith("xa:"))
async def cb_amount_btn(cq: CallbackQuery):
    raw = cq.data.split(":", 1)[1]
    st = _st(cq.from_user.id)
    if not st or "to_id" not in st:
        return await cq.answer("restart exchange", show_alert=True)
    if st.get("busy"):
        return await cq.answer("busy…")

    if raw == "max":
        balances = await _balances_or_reply(cq, edit=True)
        if balances is None:
            return await cq.answer()
        src = next((b for b in balances if b["balance_id"] == st.get("from_id")), None)
        if not src:
            return await cq.answer("source gone, restart", show_alert=True)
        amount = free_of(src)
    else:
        try:
            amount = float(raw)
        except ValueError:
            return await cq.answer("bad amount", show_alert=True)

    chat_id, message_id = st.get("prompt") or (cq.message.chat.id, cq.message.message_id)
    await _deliver(cq.bot, cq.from_user.id, amount, chat_id, message_id)
    await cq.answer("done")


@router.callback_query(F.data == "xc")
async def cb_exch_cancel(cq: CallbackQuery):
    EXCH.pop(cq.from_user.id, None)
    balances = await _balances_or_reply(cq, edit=True)
    if balances is None:
        return await cq.answer()
    await show(cq, _wallet_text(balances), kb.wallet(_usable(balances)))
    await cq.answer("cancelled")


@router.message(Command("amount"))
async def cmd_amount(m: Message):
    arg = (m.text or "").split(maxsplit=1)
    if len(arg) < 2:
        return await m.answer("usage: <code>/amount 25</code>")
    try:
        amount = float(arg[1].replace(",", ".").strip())
    except ValueError:
        return await m.answer("number expected")
    st = _st(m.from_user.id)
    chat_id, message_id = st.get("prompt") or (0, 0)
    await _deliver(m.bot, m.from_user.id, amount, chat_id, message_id)


@router.message(F.text, lambda m: has_pending(m.from_user.id))
async def on_amount(m: Message):
    if (m.text or "").startswith("/"):
        return
    try:
        amount = float(m.text.replace(",", ".").strip())
    except ValueError:
        return await m.answer("number expected · /cancel")
    st = _st(m.from_user.id)
    chat_id, message_id = st.get("prompt") or (0, 0)
    await _deliver(m.bot, m.from_user.id, amount, chat_id, message_id)


async def _do(uid: int, bot, amount: float) -> str:
    st = _st(uid)
    if not st or "from_id" not in st or "to_id" not in st:
        return "⚠️ restart exchange"
    if st.get("busy"):
        return "⚠️ already processing"
    if not math.isfinite(amount) or amount <= 0:
        return "⚠️ amount must be a positive number"

    try:
        balances = await lzt.balances()
    except LztError as e:
        return f"⚠️ {html.escape(str(e))}"

    src = next((b for b in balances if b["balance_id"] == st["from_id"]), None)
    if not src:
        EXCH.pop(uid, None)
        return "⚠️ source balance gone, restart"
    avail = free_of(src)
    if amount < 0.01:
        return f"⚠️ minimum is {fmt_money(0.01, st['cur'])}"
    if amount > avail + 1e-9:
        return f"⚠️ only {fmt_money(avail, st['cur'])} available"

    st["busy"] = True
    try:
        await lzt.exchange(st["from_id"], st["to_id"], amount)
    except LztError as e:
        st["busy"] = False
        return f"⚠️ failed: {html.escape(str(e))}"

    EXCH.pop(uid, None)
    fresh = await lzt.balances()
    return (f"✅ exchanged {fmt_money(amount, st['cur'])} → {st['to_cur']}\n\n"
            + _wallet_text(fresh))