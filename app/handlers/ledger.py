import io
import time

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from app import db, keyboards as kb
from app.handlers.menu import show
from app.utils.texts import stats_text

router = Router()


@router.callback_query(F.data == "m:stats")
async def cb_stats(cq: CallbackQuery):
    await show(cq, stats_text(await db.ledger_stats(cq.from_user.id)), kb.back())
    await cq.answer()


@router.callback_query(F.data == "m:ledger")
async def cb_ledger(cq: CallbackQuery):
    rows = await db.ledger_rows(cq.from_user.id)
    if not rows:
        return await show(cq, "📊 <b>Ledger empty</b>", kb.back())
    buf = io.StringIO()
    buf.write("purchase_id,item_id,buy,sell,status,created,closed\n")
    for r in rows:
        buf.write(f"{r['purchase_id']},{r['item_id']},{r['buy_price']},"
                  f"{r['sell_price']},{r['status']},{r['created_at']},{r['closed_at']}\n")
    await cq.message.answer_document(
        BufferedInputFile(buf.getvalue().encode(), filename=f"ledger_{int(time.time())}.csv"))
    await cq.answer()