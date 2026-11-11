from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import db
from app.config import OWNER_IDS

router = Router()


@router.message(Command("addowner"))
async def cmd_addowner(m: Message):
    if OWNER_IDS and m.from_user.id not in OWNER_IDS:
        return
    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await m.answer("Usage: /addowner 123456789")
    await db.ensure_user(int(parts[1]))
    await m.answer(f"✅ Added {parts[1]}")


@router.message(Command("sold"))
async def cmd_sold(m: Message):
    parts = (m.text or "").split()
    if len(parts) < 3:
        return await m.answer("Usage: /sold <purchase_id> <price>")
    try:
        price = float(parts[2])
    except ValueError:
        return await m.answer("❌ Price must be a number")
    if not await db.mark_sold(parts[1], price):
        return await m.answer("❌ purchase not found")
    await m.answer(f"✅ Marked sold for ${price:g}")