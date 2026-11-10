import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app import db
from app.config import BOT_TOKEN, MONGO_DB, OWNER_IDS
from app.deps import lzt
from app.engine import buy_loop, expiry_loop
from app.handlers import ROUTERS

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main():
    await db.init_db()
    for oid in OWNER_IDS:
        await db.ensure_user(oid)

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    for r in ROUTERS:
        dp.include_router(r)

    asyncio.create_task(buy_loop(bot, lzt))
    asyncio.create_task(expiry_loop(bot, lzt))
    logging.info(f"bot up (mongo db: {MONGO_DB})")
    try:
        await dp.start_polling(bot)
    finally:
        await lzt.close()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())