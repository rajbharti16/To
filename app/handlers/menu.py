from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import db, keyboards as kb
from app.config import OWNER_IDS
from app.deps import lzt
from app.utils import wallet as wallet_view
from app.utils.texts import menu_text

router = Router()


def allowed(tg_id: int) -> bool:
    return not OWNER_IDS or tg_id in OWNER_IDS


async def show(cq: CallbackQuery, text: str, markup):
    try:
        await cq.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        return
    except Exception:
        pass
    try:
        await cq.message.edit_caption(caption=text, reply_markup=markup)
        return
    except Exception:
        pass
    await cq.message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def render_menu(tg_id: int) -> tuple[str, object]:
    s = await db.get_settings(tg_id)
    snap = await wallet_view.snapshot(lzt, s["currency"])
    try:
        profile = await lzt.profile()
    except Exception:
        profile = {"username": "offline"}

    note = snap["note"]
    if not snap["error"] and snap["spendable"] < db.num(s.get("price_min")):
        hint = f"below min price {s['price_min']}"
        note = f"{note} · {hint}" if note else hint

    queued = await db.queue_count(tg_id)
    return menu_text(s, profile, snap["total"], snap["spendable"], queued, note), kb.main(s)


@router.message(Command("start"))
async def cmd_start(m: Message):
    await db.ensure_user(m.from_user.id, m.from_user.username or "")
    text, markup = await render_menu(m.from_user.id)
    await m.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.callback_query(F.data == "m:main")
async def cb_main(cq: CallbackQuery):
    text, markup = await render_menu(cq.from_user.id)
    await show(cq, text, markup)
    await cq.answer()


@router.callback_query(F.data.startswith("t:"))
async def cb_toggle(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    s = await db.get_settings(cq.from_user.id)
    if key not in s:
        return await cq.answer("unknown setting", show_alert=True)
    await db.set_setting(cq.from_user.id, key, "0" if s[key] == "1" else "1")
    from app.handlers.filters import render_screen
    await render_screen(cq, key)
    await cq.answer("saved")