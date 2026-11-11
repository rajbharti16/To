import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import CallbackQuery, Message

from app import db
from app.config import BOT_TOKEN, MONGO_DB, OWNER_IDS
from app.deps import lzt
from app.engine import buy_loop, drain_bg, expiry_loop
from app.handlers import ROUTERS
from app.handlers.menu import allowed

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def access_mw(handler, event, data):
    user = getattr(event, "from_user", None)
    if user is None:
        return await handler(event, data)
    if not allowed(user.id):
        if isinstance(event, CallbackQuery):
            await event.answer(f"Not allowed. id {user.id}", show_alert=True)
        elif isinstance(event, Message):
            await event.answer(f"Not allowed. id <code>{user.id}</code>")
        return None
    await db.ensure_user(user.id, user.username or "")
    return await handler(event, data)


async def main():
    await db.init_db()
    for oid in OWNER_IDS:
        await db.ensure_user(oid)

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.message.outer_middleware(access_mw)
    dp.callback_query.outer_middleware(access_mw)

    for r in ROUTERS:
        dp.include_router(r)

    tasks = [asyncio.create_task(buy_loop(bot, lzt)),
             asyncio.create_task(expiry_loop(bot, lzt))]

    logging.info(f"bot up (mongo db: {MONGO_DB})")
    try:
        await dp.start_polling(bot)
    finally:
        logging.info("Shutting down bot...")
        for t in tasks:
            t.cancel()
        await drain_bg()
        await lzt.close()
        await db.close_db()
        await bot.session.close()
        logging.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())