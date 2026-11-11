
app/handlers/wallet.py



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
EXCH: dict[int, dict] = {}


def _wallet_text(balances: list[dict]) -> str:
    if not balances:
        return "<b>Wallet</b>\nno balances"
    lines = "\n".join(
        f"• {b['label']} {fmt_money(b['amount'] - b['hold'], b['currency'])}"
        + ("" if b["usable_for_buy"] else " · not usable")
        for b in balances)
    return f"<b>Wallet</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{lines}"


@router.message(Command("wallet"))
async def cmd_wallet(m: Message):
    balances = await lzt.balances()
    await m.answer(_wallet_text(balances), reply_markup=kb.wallet(balances))


@router.callback_query(F.data == "m:wallet")
async def cb_wallet(cq: CallbackQuery):
    balances = await lzt.balances()
    await show(cq, _wallet_text(balances), kb.wallet(balances))
    await cq.answer()


@router.callback_query(F.data == "m:payments")
async def cb_payments(cq: CallbackQuery):
    try:
        rows = await lzt.payments(page=1)
    except LztError as e:
        return await show(cq, f"error {e}", kb.back("m:wallet"))
    body = "\n".join(payment_text(p) for p in rows[:10]) or "nothing"
    await show(cq, f"<b>Payments</b>\n{body}", kb.back("m:wallet"))
    await cq.answer()


@router.callback_query(F.data == "m:exchange")
async def cb_exchange(cq: CallbackQuery):
    balances = await lzt.balances()
    if len(balances) < 2:
        return await show(cq, "need two balances", kb.back("m:wallet"))
    EXCH[cq.from_user.id] = {}
    await show(cq, "<b>Exchange</b> — source", kb.exchange(balances, "from"))
    await cq.answer()


@router.callback_query(F.data.startswith("x:"))
async def cb_step(cq: CallbackQuery):
    _, step, bid, cur = cq.data.split(":")
    st = EXCH.setdefault(cq.from_user.id, {})
    balances = await lzt.balances()
    if step == "from":
        st.update({"from": int(bid), "cur": cur})
        pool = [b for b in balances if b["balance_id"] != int(bid)]
        return await show(cq, f"from {cur.upper()} — target", kb.exchange(pool, "to"))
    st["to"] = int(bid)
    await show(cq, f"{st['cur'].upper()} → {cur.upper()} — send amount",
               kb.kb([[("10", "xa:10"), ("50", "xa:50"), ("100", "xa:100")],
                      [("Back", "m:wallet")]]))
    await cq.answer()


@router.callback_query(F.data.startswith("xa:"))
async def cb_amount_btn(cq: CallbackQuery):
    await _do(cq.from_user.id, cq.bot, float(cq.data.split(":", 1)[1]))
    await cq.answer("done")


@router.message(F.text, lambda m: m.from_user.id in EXCH and "to" in EXCH[m.from_user.id])
async def on_amount(m: Message):
    try:
        amount = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("number expected")
    await _do(m.from_user.id, m.bot, amount)


async def _do(uid: int, bot, amount: float):
    st = EXCH.pop(uid, {})
    if "from" not in st or "to" not in st:
        return await bot.send_message(uid, "restart exchange")
    try:
        await lzt.exchange(st["from"], st["to"], amount)
    except LztError as e:
        return await bot.send_message(uid, f"failed {e}")
    balances = await lzt.balances()
    await bot.send_message(uid, f"exchanged {amount:g}\n\n" + _wallet_text(balances),
                           reply_markup=kb.wallet(balances))


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
EXCH: dict[int, dict] = {}


def _wallet_text(balances: list[dict]) -> str:
    if not balances:
        return "<b>Wallet</b>\nno balances"
    lines = "\n".join(
        f"• {b['label']} {fmt_money(b['amount'] - b['hold'], b['currency'])}"
        + ("" if b["usable_for_buy"] else " · not usable")
        for b in balances)
    return f"<b>Wallet</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{lines}"


@router.message(Command("wallet"))
async def cmd_wallet(m: Message):
    balances = await lzt.balances()
    await m.answer(_wallet_text(balances), reply_markup=kb.wallet(balances))


@router.callback_query(F.data == "m:wallet")
async def cb_wallet(cq: CallbackQuery):
    balances = await lzt.balances()
    await show(cq, _wallet_text(balances), kb.wallet(balances))
    await cq.answer()


@router.callback_query(F.data == "m:payments")
async def cb_payments(cq: CallbackQuery):
    try:
        rows = await lzt.payments(page=1)
    except LztError as e:
        return await show(cq, f"error {e}", kb.back("m:wallet"))
    body = "\n".join(payment_text(p) for p in rows[:10]) or "nothing"
    await show(cq, f"<b>Payments</b>\n{body}", kb.back("m:wallet"))
    await cq.answer()


@router.callback_query(F.data == "m:exchange")
async def cb_exchange(cq: CallbackQuery):
    balances = await lzt.balances()
    if len(balances) < 2:
        return await show(cq, "need two balances", kb.back("m:wallet"))
    EXCH[cq.from_user.id] = {}
    await show(cq, "<b>Exchange</b> — source", kb.exchange(balances, "from"))
    await cq.answer()


@router.callback_query(F.data.startswith("x:"))
async def cb_step(cq: CallbackQuery):
    _, step, bid, cur = cq.data.split(":")
    st = EXCH.setdefault(cq.from_user.id, {})
    balances = await lzt.balances()
    if step == "from":
        st.update({"from": int(bid), "cur": cur})
        pool = [b for b in balances if b["balance_id"] != int(bid)]
        return await show(cq, f"from {cur.upper()} — target", kb.exchange(pool, "to"))
    st["to"] = int(bid)
    await show(cq, f"{st['cur'].upper()} → {cur.upper()} — send amount",
               kb.kb([[("10", "xa:10"), ("50", "xa:50"), ("100", "xa:100")],
                      [("Back", "m:wallet")]]))
    await cq.answer()


@router.callback_query(F.data.startswith("xa:"))
async def cb_amount_btn(cq: CallbackQuery):
    await _do(cq.from_user.id, cq.bot, float(cq.data.split(":", 1)[1]))
    await cq.answer("done")


@router.message(F.text, lambda m: m.from_user.id in EXCH and "to" in EXCH[m.from_user.id])
async def on_amount(m: Message):
    try:
        amount = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("number expected")
    await _do(m.from_user.id, m.bot, amount)


async def _do(uid: int, bot, amount: float):
    st = EXCH.pop(uid, {})
    if "from" not in st or "to" not in st:
        return await bot.send_message(uid, "restart exchange")
    try:
        await lzt.exchange(st["from"], st["to"], amount)
    except LztError as e:
        return await bot.send_message(uid, f"failed {e}")
    balances = await lzt.balances()
    await bot.send_message(uid, f"exchanged {amount:g}\n\n" + _wallet_text(balances),
                           reply_markup=kb.wallet(balances))