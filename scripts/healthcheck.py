"""Docker healthcheck: mongo reachable + LZT token valid."""
import asyncio
import sys

from app import db
from app.deps import lzt
from app.lzt import LztError


async def main() -> int:
    try:
        await db.init_db()
        await db.all_owners()
        await lzt.me()
    except LztError:
        pass          # mongo ok, LZT hiccup is not fatal
    except Exception as e:
        print(f"unhealthy: {e}")
        return 1
    finally:
        await db.close_db()
        await lzt.close()
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))