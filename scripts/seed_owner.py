"""Create the first owner + default settings. Usage: python -m scripts.seed_owner 123456789"""
import asyncio
import sys

from app import db


async def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print("usage: python -m scripts.seed_owner <tg_id>")
        return
    await db.init_db()
    await db.ensure_user(int(sys.argv[1]))
    print(f"seeded {sys.argv[1]}")
    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())