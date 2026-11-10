from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import db, keyboards as kb
from app.config import OWNER_IDS
from app.deps import lzt
from app.engine import buy_one
from app.lzt import LztError
from app.utils.filters import passes
from app.utils.texts import menu_text

router = Router()


def allowed(tg_id: int) -> bool:
    return not OWNER_IDS or tg_id in OWNER_IDS


async def show(cq: CallbackQuery, text: str, markup):
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except Exception:
        await cq.message.answer(text, reply_markup=markup)


@router.message(Command("start"))
async def cmd_start(m: Message):
    if not allowed(m.from_user.id):
        return await m.answer(f"⛔️ Not allowed. Your id: <code>{m.from_user.id}</code>")
    await db.ensure_user(m.from_user.id, m.from_user.username or "")
    s = await db.get_settings(m.from_user.id)
    await m.answer(menu_text(s), reply_markup=kb.main(s))


@router.callback_query(F.data == "m:main")
async def cb_main(cq: CallbackQuery):
    s = await db.get_settings(cq.from_user.id)
    await show(cq, menu_text(s), kb.main(s))
    await cq.answer()


@router.callback_query(F.data.startswith("t:"))
async def cb_toggle(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    s = await db.get_settings(cq.from_user.id)
    new = "0" if s[key] == "1" else "1"
    await db.set_setting(cq.from_user.id, key, new)
    s = await db.get_settings(cq.from_user.id)
    await show(cq, menu_text(s), kb.main(s) if key == "auto_buy" else kb.filters(s))
    await cq.answer(f"{key}: {'ON' if new == '1' else 'OFF'}")


@router.callback_query(F.data == "go")
async def cb_go(cq: CallbackQuery):
    await cq.answer("scanning…")
    s = await db.get_settings(cq.from_user.id)
    try:
        items = await lzt.search(s)
    except LztError as e:
        return await cq.message.answer(f"❌ Search failed: {e}")
    for it in items[:40]:
        if not passes(it, s)[0]:
            continue
        if await buy_one(cq.bot, lzt, cq.from_user.id, it, s):
            return await cq.message.answer(f"✅ Bought {it['item_id']}")
    await cq.message.answer("😕 No matching account right now")