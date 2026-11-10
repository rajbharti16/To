"""Buy loop + expiry worker, with live balance guard."""
import asyncio
import logging
import time

from app import db
from app.config import TICK
from app.lzt import LztError
from app.mail_engine import TempMailClient
from app.session_manager import change_email, client, login_with_lzt, terminate
from app.utils.filters import country_of, passes, phone_of
from app.utils.money import fmt_money, total_any

log = logging.getLogger("engine")


async def _notify(bot, tg_id, text):
    try:
        await bot.send_message(tg_id, text)
    except Exception:
        pass


async def buy_one(bot, lzt, tg_id: int, item: dict, s: dict):
    item_id = item["item_id"]
    price = float(item["price"])
    currency = s["currency"]

    try:
        wallet = await lzt.balance_for_buy(currency, price)
    except LztError as e:
        log.info(f"balance check: {e}")
        return None

    if wallet is None:
        try:
            have = await lzt.balance_total(currency)
            any_total = total_any(await lzt.balances(), currency)
        except LztError:
            have = any_total = 0.0
        hint = f" (TG-only {fmt_money(any_total, currency)})" if any_total > have else ""
        await _notify(bot, tg_id,
                      f"💳 Insufficient market balance {fmt_money(have, currency)} "
                      f"for {fmt_money(price, currency)}{hint}")
        return None

    try:
        chk = await lzt.check_account(item_id)
    except LztError as e:
        log.info(f"check {item_id}: {e}")
        return None
    if chk.get("telegram_spam_block") is True and s["spam_mode"] == "no":
        return None

    try:
        res = await lzt.fast_buy(item_id, price, balance_id=wallet["balance_id"] or None)
    except LztError as e:
        log.info(f"buy {item_id}: {e}")
        return None

    login_data = (res.get("item") or {}).get("loginData") or {}
    phone = login_data.get("login") or phone_of(item)
    password = login_data.get("password") or item.get("telegram_password") or ""
    expires = int(time.time() + float(s["session_life_hours"] or 24) * 3600)

    pid = await db.add_purchase(tg_id, item_id, phone, country_of(item), price,
                                expires_at=expires, note="bought")
    asyncio.create_task(_login_task(bot, lzt, tg_id, pid, item_id, phone, password, s, expires))
    return pid


async def _login_task(bot, lzt, tg_id, pid, item_id, phone, password, s, expires):
    try:
        c, session_str, _uid = await login_with_lzt(phone, password, item_id, lzt, s["proxy"])
    except Exception as e:
        await db.close_purchase(pid, "login_failed", str(e)[:200])
        await _notify(bot, tg_id, f"⚠️ <b>Login failed</b>\n<code>{phone}</code>\n<code>{e}</code>")
        return

    await db.set_session(pid, session_str)
    await _notify(bot, tg_id,
                  f"✅ <b>Session active</b>\n<code>{phone}</code>\n"
                  f"Expires <code>{time.strftime('%H:%M', time.localtime(expires))}</code> "
                  f"(+{s['session_life_hours']}h)")
    await c.disconnect()


async def expire_purchase(bot, lzt, p: dict):
    s = await db.get_settings(p["tg_id"])
    new_mail, note = "", []

    if p.get("session_string"):
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
                  f"🔒 <b>Session expired — cleaned</b>\n<code>{p['phone']}</code>\n"
                  f"{'; '.join(note)}\nNew mail: <code>{new_mail or '-'}</code>")


async def buy_loop(bot, lzt):
    while True:
        try:
            for u in await db.all_owners():
                tg_id = u["_id"]
                s = await db.get_settings(tg_id)

                if s["auto_buy"] != "1":
                    continue
                if await db.spent_today(tg_id) >= float(s["daily_spend_cap"]):
                    continue

                try:
                    if await lzt.balance_total(s["currency"]) < float(s["price_min"]):
                        await asyncio.sleep(float(s["poll_interval"]))
                        continue
                except LztError:
                    pass

                try:
                    items = await lzt.search(s)
                except LztError as e:
                    log.info(f"search: {e}")
                    await asyncio.sleep(10)
                    continue

                bought = 0
                for it in items[:40]:
                    if not passes(it, s)[0]:
                        continue
                    if await buy_one(bot, lzt, tg_id, it, s):
                        bought += 1
                    if bought >= int(s["max_buy_per_cycle"]):
                        break
                await asyncio.sleep(float(s["poll_interval"]))
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
        await asyncio.sleep(30)