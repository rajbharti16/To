from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import db, keyboards as kb
from app.config import OWNER_IDS
from app.deps import lzt
from app.lzt import LztError
from app.utils.texts import menu_text

router = Router()


def allowed(tg_id: int) -> bool:
    return not OWNER_IDS or tg_id in OWNER_IDS


async def show(cq: CallbackQuery, text: str, markup):
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except Exception:
        await cq.message.answer(text, reply_markup=markup)


async def render_menu(tg_id: int) -> tuple[str, object]:
    s = await db.get_settings(tg_id)
    try:
        profile = await lzt.profile()
        balance = await lzt.balance_total(s["currency"])
    except LztError:
        profile, balance = {"username": "offline"}, 0.0
    queued = await db.queue_count(tg_id)
    return menu_text(s, profile, balance, queued), kb.main(s)


@router.message(Command("start"))
async def cmd_start(m: Message):
    if not allowed(m.from_user.id):
        return await m.answer(f"Not allowed. id <code>{m.from_user.id}</code>")
    await db.ensure_user(m.from_user.id, m.from_user.username or "")
    text, markup = await render_menu(m.from_user.id)
    await m.answer(text, reply_markup=markup)


@router.callback_query(F.data == "m:main")
async def cb_main(cq: CallbackQuery):
    text, markup = await render_menu(cq.from_user.id)
    await show(cq, text, markup)
    await cq.answer()


@router.callback_query(F.data.startswith("t:"))
async def cb_toggle(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    s = await db.get_settings(cq.from_user.id)
    new = "0" if s[key] == "1" else "1"
    await db.set_setting(cq.from_user.id, key, new)
    if key == "auto_buy":
        text, markup = await render_menu(cq.from_user.id)
        return await show(cq, text, markup)
    s = await db.get_settings(cq.from_user.id)
    from app.utils.texts import filters_text
    await show(cq, filters_text(s), kb.filters(s))
    await cq.answer("saved")