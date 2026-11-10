from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.deps import lzt
from app.handlers.menu import live_state, show
from app.lzt import LztError
from app.utils.texts import payment_text, wallet_text

router = Router()

# per-user pending exchange: {"step": "from"|"to"|"amount", "from": id, "to": id, "cur": str}
EXCH: dict[int, dict] = {}


async def _render(cq: CallbackQuery):
    profile, balances = await live_state()
    await show(cq, wallet_text(profile, balances), kb.wallet(profile, balances))


@router.message(Command("wallet"))
async def cmd_wallet(m: Message):
    profile, balances = await live_state()
    await m.answer(wallet_text(profile, balances), reply_markup=kb.wallet(profile, balances))


@router.callback_query(F.data == "m:wallet")
async def cb_wallet(cq: CallbackQuery):
    await _render(cq)
    await cq.answer("live")


@router.callback_query(F.data == "m:payments")
async def cb_payments(cq: CallbackQuery):
    try:
        rows = await lzt.payments(page=1)
    except LztError as e:
        return await show(cq, f"❌ {e}", kb.back("m:wallet"))
    body = "\n".join(payment_text(p) for p in rows[:10]) or "no operations"
    await show(cq, f"📜 <b>Recent payments</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{body}", kb.back("m:wallet"))
    await cq.answer()


@router.callback_query(F.data == "m:exchange")
async def cb_exchange(cq: CallbackQuery):
    _, balances = await live_state()
    if len(balances) < 2:
        return await show(cq, "💱 Need at least two balances", kb.back("m:wallet"))
    EXCH[cq.from_user.id] = {"step": "from"}
    await show(cq, "💱 <b>Exchange — pick source</b>", kb.exchange(balances, "from"))
    await cq.answer()


@router.callback_query(F.data.startswith("x:"))
async def cb_exchange_step(cq: CallbackQuery):
    _, step, bid, cur = cq.data.split(":")
    state = EXCH.setdefault(cq.from_user.id, {"step": "from"})
    _, balances = await live_state()

    if step == "from":
        state.update({"from": int(bid), "cur": cur, "step": "to"})
        pool = [b for b in balances if b["balance_id"] != int(bid)]
        return await show(cq, f"💱 From <b>{cur.upper()}</b> — pick target", kb.exchange(pool, "to"))

    state.update({"to": int(bid), "step": "amount"})
    await show(
        cq,
        f"💱 <b>{state['cur'].upper()} → {cur.upper()}</b>\nSend amount (or pick below)",
        kb.kb([[("10", "xa:10"), ("50", "xa:50"), ("100", "xa:100")],
               [("⬅️ Back", "m:wallet")]]),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("xa:"))
async def cb_exchange_amount(cq: CallbackQuery):
    state = EXCH.get(cq.from_user.id)
    if not state or "to" not in state:
        return await cq.answer("restart", show_alert=True)
    await _do_exchange(cq, float(cq.data.split(":", 1)[1]))


@router.message(F.text, lambda m: EXCH.get(m.from_user.id, {}).get("step") == "amount")
async def on_exchange_amount(m: Message):
    try:
        amount = float(m.text.strip().replace(",", "."))
    except ValueError:
        return await m.answer("❌ Number expected")
    await _do_exchange(m, amount)


async def _do_exchange(src, amount: float):
    uid = src.from_user.id
    state = EXCH.pop(uid, None) or {}
    tg_id = uid
    try:
        await lzt.exchange(state["from"], state["to"], amount)
    except (LztError, KeyError) as e:
        return await src.bot.send_message(tg_id, f"❌ Exchange failed: {e}")

    profile, balances = await live_state()
    await src.bot.send_message(
        tg_id, f"✅ Exchanged {amount:g} {state['cur'].upper()}\n\n" + wallet_text(profile, balances),
        reply_markup=kb.wallet(profile, balances),
    )