from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import db, keyboards as kb
from app.deps import lzt
from app.handlers.menu import show
from app.lzt import LztError
from app.session_manager import client, terminate
from app.utils.texts import session_detail, session_file

router = Router()


async def _list(target) -> None:
    tg_id = target.from_user.id
    rows = await db.active_purchases(tg_id)
    if not rows:
        return await target.answer("no sessions queued", reply_markup=kb.back())
    await target.answer(f"<b>Sessions</b> · {len(rows)}", reply_markup=kb.sessions(rows))


@router.message(Command("session"))
async def cmd_session(m: Message):
    arg = (m.text or "").split(maxsplit=1)
    if len(arg) > 1:
        p = await db.find_by_phone(m.from_user.id, arg[1].strip())
        if not p:
            return await m.answer("not found")
        return await m.answer(session_detail(p), reply_markup=kb.session_detail(p))
    await _list(m)


@router.callback_query(F.data == "m:sessions")
async def cb_sessions(cq: CallbackQuery):
    await _list(cq.message)
    await cq.answer()


@router.callback_query(F.data.startswith("v:"))
async def cb_view(cq: CallbackQuery):
    p = await db.get_purchase(cq.data.split(":", 1)[1])
    if not p:
        return await cq.answer("gone", show_alert=True)
    await show(cq, session_detail(p), kb.session_detail(p))
    await cq.answer()


@router.callback_query(F.data.startswith("f:"))
async def cb_file(cq: CallbackQuery):
    p = await db.get_purchase(cq.data.split(":", 1)[1])
    if not p:
        return await cq.answer("gone", show_alert=True)
    name = (p.get("phone") or str(p["item_id"])).lstrip("+")
    await cq.message.answer_document(
        BufferedInputFile(session_file(p).encode(), filename=f"{name}.py"))
    await cq.answer("sent")


@router.callback_query(F.data.startswith("k:"))
async def cb_kill(cq: CallbackQuery):
    pid = cq.data.split(":", 1)[1]
    p = await db.get_purchase(pid)
    if not p:
        return await cq.answer("gone", show_alert=True)
    await db.close_purchase(pid, "killed", "manual clean")
    if p.get("session_string"):
        try:
            c = client(p["session_string"])
            await c.connect()
            await terminate(c)
        except Exception:
            pass
    try:
        await lzt.reset_authorizations(p["item_id"])
    except LztError:
        pass
    await show(cq, f"cleaned <code>{p.get('phone')}</code>", kb.back("m:sessions"))
    await cq.answer("cleaned")