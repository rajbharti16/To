import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app import db
from app.config import BOT_TOKEN, MONGO_DB, OWNER_IDS
from app.deps import lzt
from app.engine import buy_loop, expiry_loop, drain_bg
from app.handlers import ROUTERS
from app.handlers import filters as filters_h
from app.handlers import wallet as wallet_h


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


async def main():
    await db.init_db()

    for oid in OWNER_IDS:
        await db.ensure_user(oid)

    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    dp = Dispatcher()

    # Wallet first — both wallet and filters use F.text handlers
    dp.include_router(wallet_h.router)
    dp.include_router(filters_h.router)

    # Include remaining routers
    for r in ROUTERS:
        if r not in (wallet_h.router, filters_h.router):
            dp.include_router(r)

    asyncio.create_task(buy_loop(bot, lzt))
    asyncio.create_task(expiry_loop(bot, lzt))

    logging.info(f"bot up (mongo db: {MONGO_DB})")

    try:
        await dp.start_polling(bot)

    finally:
        logging.info("Shutting down bot...")

        await drain_bg()
        await lzt.close()
        await db.close_db()
        await bot.session.close()

        logging.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())