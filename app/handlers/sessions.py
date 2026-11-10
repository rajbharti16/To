from aiogram import F, Router
from aiogram.types import CallbackQuery

from app import db, keyboards as kb
from app.deps import lzt
from app.handlers.menu import show
from app.lzt import LztError
from app.session_manager import client, terminate

router = Router()


@router.callback_query(F.data == "m:sessions")
async def cb_sessions(cq: CallbackQuery):
    rows = await db.active_purchases(cq.from_user.id)
    if not rows:
        return await show(cq, "🧾 <b>No active sessions</b>", kb.back())
    await show(cq, f"🧾 <b>Active sessions ({len(rows)})</b>", kb.sessions(rows))
    await cq.answer()


@router.callback_query(F.data.startswith("k:"))
async def cb_kill(cq: CallbackQuery):
    pid = cq.data.split(":", 1)[1]
    p = await db.get_purchase(pid)
    if not p:
        return await cq.answer("gone", show_alert=True)

    await db.close_purchase(pid, "killed", "manual kill")
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

    await show(cq, f"🔒 Killed <code>{p['phone']}</code>", kb.back())
    await cq.answer("killed")