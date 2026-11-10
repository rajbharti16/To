from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import db, keyboards as kb
from app.handlers.menu import show

router = Router()
PENDING: dict[int, str] = {}


@router.callback_query(F.data == "m:filters")
async def cb_filters(cq: CallbackQuery):
    s = await db.get_settings(cq.from_user.id)
    await show(cq, "🎛 <b>Filters</b>", kb.filters(s))
    await cq.answer()


@router.callback_query(F.data == "m:price")
async def cb_price(cq: CallbackQuery):
    await show(cq, "💵 <b>Price range</b>", kb.price())
    await cq.answer()


@router.callback_query(F.data == "m:spam")
async def cb_spam(cq: CallbackQuery):
    await show(cq, "🚦 <b>Spam filter</b>", kb.pick("s:spam_mode", ["no", "yes", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:mail")
async def cb_mail(cq: CallbackQuery):
    await show(cq, "📧 <b>Mail filter</b>", kb.pick("s:mail_mode", ["yes", "no", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:pass")
async def cb_pass(cq: CallbackQuery):
    await show(cq, "🔐 <b>2FA filter</b>", kb.pick("s:password_mode", ["no", "yes", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:sess")
async def cb_sess(cq: CallbackQuery):
    await show(cq, "⏳ <b>Minimum session age</b>", kb.session_ages())
    await cq.answer()


@router.callback_query(F.data == "m:life")
async def cb_life(cq: CallbackQuery):
    await show(cq, "⌛️ <b>Session lifetime before terminate</b>", kb.session_lives())
    await cq.answer()


@router.callback_query(F.data == "m:countries")
async def cb_countries(cq: CallbackQuery):
    s = await db.get_settings(cq.from_user.id)
    await show(cq, "🌍 <b>Allowed countries</b>", kb.countries(s["countries"]))
    await cq.answer()


@router.callback_query(F.data.startswith("s:"))
async def cb_set(cq: CallbackQuery):
    _, key, value = cq.data.split(":", 2)
    await db.set_setting(cq.from_user.id, key, value)
    s = await db.get_settings(cq.from_user.id)
    await show(cq, f"✅ {key} = {value}", kb.filters(s))
    await cq.answer("saved")


@router.callback_query(F.data.startswith("c:"))
async def cb_country(cq: CallbackQuery):
    code = cq.data.split(":", 1)[1]
    s = await db.get_settings(cq.from_user.id)
    cur = [c.strip().upper() for c in s["countries"].split(",") if c.strip()]
    if code == "CLEAR":
        cur = []
    elif code in cur:
        cur.remove(code)
    else:
        cur.append(code)
    await db.set_setting(cq.from_user.id, "countries", ",".join(cur))
    await show(cq, "🌍 <b>Allowed countries</b>", kb.countries(",".join(cur)))
    await cq.answer()


@router.callback_query(F.data.startswith("in:"))
async def cb_input(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    PENDING[cq.from_user.id] = key
    await cq.message.answer(f"✏️ Send value for <b>{key}</b>\n/cancel to abort",
                            reply_markup=kb.kb([[("✖️ Cancel", "x")]]))
    await cq.answer()


@router.callback_query(F.data == "x")
async def cb_cancel(cq: CallbackQuery):
    PENDING.pop(cq.from_user.id, None)
    await cq.message.answer("Cancelled", reply_markup=kb.back())
    await cq.answer()


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    PENDING.pop(m.from_user.id, None)
    await m.answer("Cancelled")


@router.message(F.text)
async def on_text(m: Message):
    key = PENDING.pop(m.from_user.id, None)
    if not key:
        return
    val = m.text.strip().replace(" ", "")
    if key == "countries":
        val = ",".join(x.upper() for x in val.split(",") if x)
    else:
        try:
            float(val)
        except ValueError:
            return await m.answer("❌ Number expected")
    await db.set_setting(m.from_user.id, key, val)
    await m.answer(f"✅ {key} = {val}", reply_markup=kb.back("m:filters"))