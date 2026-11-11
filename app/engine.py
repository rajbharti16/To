"""Buy loop + session-age queue + expiry worker."""
import asyncio
import logging
import time
from collections import Counter

from app import db
from app.config import TICK
from app.lzt import LztError
from app.mail_engine import TempMailClient
from app.session_manager import change_email, client, login_with_lzt, terminate
from app.utils.filters import (
    clean_delay_hours, country_of, passes, phone_of, search_query, session_hours,
)
from app.utils.money import fmt_money

log = logging.getLogger("engine")

_BAL_WARNED: dict[int, float] = {}
WARN_COOLDOWN = 900.0

# strong refs, warna GC pending task destroy kar deta hai ("Task was destroyed")
_BG: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG.add(task)
    task.add_done_callback(_BG.discard)
    return task


async def drain_bg(timeout: float = 5.0):
    """Shutdown hook: let running login tasks finish instead of killing them."""
    if not _BG:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*list(_BG), return_exceptions=True), timeout)
    except asyncio.TimeoutError:
        log.info(f"shutdown: {len(_BG)} login task(s) still running")


async def _notify(bot, tg_id, text):
    try:
        await bot.send_message(tg_id, text)
    except Exception:
        pass


async def _balance_warn(bot, tg_id, text):
    if time.time() - _BAL_WARNED.get(tg_id, 0.0) < WARN_COOLDOWN:
        return
    _BAL_WARNED[tg_id] = time.time()
    await _notify(bot, tg_id, text)


async def _search_items(lzt, s: dict) -> list[dict]:
    """Search with the server-side age floor applied when one is configured."""
    q = search_query(s)
    if not q:
        return await lzt.search(s)
    try:
        return await lzt.search({**s, **q})
    except TypeError:
        return await lzt.search(s)


async def buy_one(bot, lzt, tg_id: int, item: dict, s: dict):
    item_id = item["item_id"]
    price = db.num(item.get("price"))
    currency = s["currency"]

    try:
        wallet = await lzt.balance_for_buy(currency, price)
    except LztError as e:
        log.info(f"balance: {e}")
        return None
    if wallet is None:
        have = await lzt.balance_total(currency)
        await _balance_warn(bot, tg_id,
                            f"💳 Low balance {fmt_money(have, currency)} — buy paused")
        return None

    try:
        chk = await lzt.check_account(item_id)
    except LztError as e:
        log.info(f"check {item_id}: {e}")
        return None

    # authoritative re-check against the full check-account payload
    fresh = dict(item)
    fresh.update({k: v for k, v in (chk.get("item") or {}).items() if v not in (None, "")})
    ok, why = passes(fresh, s, authoritative=True)
    if not ok:
        log.info(f"skip {item_id}: {why}")
        return None
    if why == "ok_unknown":
        log.info(f"note {item_id}: some fields unknown, server filters relied on")

    try:
        res = await lzt.fast_buy(item_id, price, balance_id=wallet["balance_id"] or None)
    except LztError as e:
        log.info(f"buy {item_id}: {e}")
        return None

    login_data = (res.get("item") or {}).get("loginData") or {}
    phone = login_data.get("login") or phone_of(fresh) or phone_of(item)
    password = login_data.get("password") or fresh.get("telegram_password") or ""

    target = db.num(s.get("session_life_hours"), 24.0)
    age = session_hours(fresh) or 0.0
    delay = clean_delay_hours(fresh, target)
    expires = int(time.time() + delay * 3600)

    pid = await db.add_purchase(
        tg_id, item_id, phone, country_of(fresh), price,
        expires_at=expires, target_age_hours=target, age_at_buy_hours=age, note="bought")

    _spawn(_login_task(bot, lzt, tg_id, pid, item_id, phone, password, s, delay))
    return pid


async def _login_task(bot, lzt, tg_id, pid, item_id, phone, password, s, delay):
    try:
        c, session_str, _uid = await login_with_lzt(phone, password, item_id, lzt, s["proxy"])
    except Exception as e:
        await db.close_purchase(pid, "login_failed", str(e)[:200])
        await _notify(bot, tg_id, f"⚠️ <b>Login failed</b>\n<code>{phone}</code>\n<code>{e}</code>")
        return

    await db.set_session(pid, session_str)
    when = "cleaning now" if delay <= 0 else f"clean in {delay:.2f}h"
    await _notify(bot, tg_id, f"✅ <b>Bought</b> <code>{phone}</code>\n🕒 {when}")
    await c.disconnect()
    await asyncio.sleep(0)  # let telethon's loops settle before the task ends


async def expire_purchase(bot, lzt, p: dict):
    s = await db.get_settings(p["tg_id"])

    # login still running -> push 5 min, retry later
    if not p.get("session_string"):
        if time.time() - p["started_at"] < 900:
            await db.bump_expiry(p["_id"], 300)
            return
        await db.close_purchase(p["_id"], "login_failed", "no session string")
        return

    new_mail, note = "", []
    c = client(p["session_string"], s["proxy"])
    try:
        await c.connect()
        if s["change_mail_on_expire"] == "1":
            try:
                mc = TempMailClient()
                addr = await mc.create_temp_email()
                await change_email(c, addr, mc)
                new_mail = addr
                note.append("mail changed")
            except Exception as e:
                note.append(f"mail fail: {e}")
        if s["terminate_on_expire"] == "1":
            await terminate(c)
            note.append("terminated")
    except Exception as e:
        note.append(f"session err: {e}")
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass

    try:
        await lzt.reset_authorizations(p["item_id"])
        note.append("lzt auth reset")
    except LztError as e:
        note.append(f"reset: {e}")

    await db.close_purchase(p["_id"], "terminated", "; ".join(note)[:300], new_mail=new_mail)
    await _notify(bot, p["tg_id"],
                  f"🧼 <b>Cleaned</b> <code>{p['phone']}</code>\n"
                  f"{'; '.join(note)}\n📧 <code>{new_mail or '-'}</code>")


async def buy_loop(bot, lzt):
    while True:
        try:
            for u in await db.all_owners():
                tg_id = u["_id"]
                s = await db.get_settings(tg_id)
                if s["auto_buy"] != "1":
                    continue
                if await db.spent_today(tg_id) >= db.num(s.get("daily_spend_cap")):
                    continue

                floor = db.num(s.get("session_min_hours"))
                try:
                    if await lzt.balance_total(s["currency"]) < db.num(s.get("price_min")):
                        await asyncio.sleep(db.intval(s.get("poll_interval"), 25))
                        continue
                    items = await _search_items(lzt, s)
                except LztError as e:
                    log.info(f"search: {e}")
                    await asyncio.sleep(10)
                    continue

                reasons = Counter()
                bought = 0
                for it in items[:60]:
                    ok, why = passes(it, s)
                    if not ok:
                        reasons[why] += 1
                        continue
                    if await buy_one(bot, lzt, tg_id, it, s):
                        bought += 1
                        if why != "ok":
                            reasons[f"{why}_bought"] += 1
                    elif why != "ok":
                        reasons[f"{why}_skip"] += 1
                    if bought >= db.intval(s.get("max_buy_per_cycle"), 2):
                        break

                log.info(f"[{tg_id}] scanned={len(items)} bought={bought} "
                         f"floor={floor:.1f}h rejects={dict(reasons.most_common(5))}")
                await asyncio.sleep(db.intval(s.get("poll_interval"), 25))
        except Exception as e:
            log.exception(f"buy_loop: {e}")
        await asyncio.sleep(TICK)


async def expiry_loop(bot, lzt):
    while True:
        try:
            for p in await db.due_purchases():
                await expire_purchase(bot, lzt, p)
        except Exception as e:
            log.exception(f"expiry_loop: {e}")
        await asyncio.sleep(20)