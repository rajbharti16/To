from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import db, keyboards as kb
from app.handlers.menu import show
from app.utils.texts import filters_text

router = Router()
PENDING: dict[int, str] = {}


@router.callback_query(F.data == "m:filters")
async def cb_filters(cq: CallbackQuery):
    s = await db.get_settings(cq.from_user.id)
    await show(cq, filters_text(s), kb.filters(s))
    await cq.answer()


@router.callback_query(F.data == "m:price")
async def cb_price(cq: CallbackQuery):
    await show(cq, "<b>Price</b>\nmax picks top, min picks bottom", kb.price())
    await cq.answer()


@router.callback_query(F.data == "m:spam")
async def cb_spam(cq: CallbackQuery):
    await show(cq, "<b>Spam filter</b>", kb.pick("s:spam_mode", ["no", "yes", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:mail")
async def cb_mail(cq: CallbackQuery):
    await show(cq, "<b>Mail filter</b>", kb.pick("s:mail_mode", ["yes", "no", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:pass")
async def cb_pass(cq: CallbackQuery):
    await show(cq, "<b>2FA filter</b>", kb.pick("s:password_mode", ["no", "yes", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:sess")
async def cb_sess(cq: CallbackQuery):
    await show(cq, "<b>Min session age</b> (0 = any)", kb.floors())
    await cq.answer()


@router.callback_query(F.data == "m:life")
async def cb_life(cq: CallbackQuery):
    await show(cq, "<b>Target age</b>\nreached target → auto clean", kb.targets())
    await cq.answer()


@router.callback_query(F.data.startswith("s:"))
async def cb_set(cq: CallbackQuery):
    _, key, value = cq.data.split(":", 2)
    await db.set_setting(cq.from_user.id, key, value)
    s = await db.get_settings(cq.from_user.id)
    await show(cq, filters_text(s), kb.filters(s))
    await cq.answer("saved")


@router.callback_query(F.data.startswith("in:"))
async def cb_input(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    PENDING[cq.from_user.id] = key
    hint = ("only these countries get bought" if key == "countries"
            else "these countries are skipped")
    await cq.message.answer(
        f"<b>{key.replace('_', ' ')}</b>\n{hint}\n\nSend ISO codes, comma separated "
        f"(e.g. <code>AE,LY,JO</code>)\n<code>all</code> = clear · /cancel",
        reply_markup=kb.kb([[("Cancel", "x")]]))
    await cq.answer()


@router.callback_query(F.data == "x")
async def cb_cancel(cq: CallbackQuery):
    PENDING.pop(cq.from_user.id, None)
    await cq.message.answer("cancelled", reply_markup=kb.back("m:filters"))
    await cq.answer()


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    PENDING.pop(m.from_user.id, None)
    await m.answer("cancelled")


@router.message(F.text)
async def on_text(m: Message):
    key = PENDING.pop(m.from_user.id, None)
    if not key:
        return
    raw = m.text.strip().replace(" ", "")
    if key in ("countries", "deny_countries"):
        if raw.lower() in ("all", "-", "clear"):
            val = ""
        else:
            codes = [c.upper() for c in raw.split(",") if len(c.strip()) == 2 and c.strip().isalpha()]
            if not codes:
                return await m.answer("need ISO codes like AE,LY")
            val = ",".join(dict.fromkeys(codes))
    else:
        try:
            val = f"{float(raw):g}"
        except ValueError:
            return await m.answer("number expected")
    await db.set_setting(m.from_user.id, key, val)
    s = await db.get_settings(m.from_user.id)
    await m.answer(filters_text(s), reply_markup=kb.filters(s))