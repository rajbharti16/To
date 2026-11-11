"""Buy loop + expiry worker + cycle reporting."""
import asyncio
import logging
import time
from collections import Counter

from app import db
from app.config import EXPIRY_LOGIN_GRACE, EXPIRY_RETRY, EXPIRY_RETRY_DELAY, TICK
from app.lzt import LztError
from app.mail_engine import IMAPMailClient, TempMailClient
from app.session_manager import change_email, check_session, client, login_with_lzt, terminate
from app.utils.filters import (
    account_created_ts, age_hours_of, clean_delay_hours, country_of, passes, phone_of,
    search_query,
)
from app.utils.money import fmt_money, free_of, pick_for_buy, spendable

log = logging.getLogger("engine")

_BAL_WARNED: dict[int, float] = {}
WARN_COOLDOWN = 900.0

_BG: set[asyncio.Task] = set()
_NEXT_RUN: dict[int, float] = {}


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG.add(task)
    task.add_done_callback(_BG.discard)
    return task


async def drain_bg(timeout: float = 5.0):
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
    q = search_query(s)
    if not q:
        return await lzt.search(s)
    try:
        return await lzt.search({**s, **q})
    except TypeError:
        return await lzt.search(s)


async def _fast_buy(lzt, item_id: int, price: float, balance_id: int):
    kwargs = {"balance_id": balance_id} if balance_id else {}
    try:
        return await lzt.fast_buy(item_id, price, **kwargs)
    except TypeError:
        return await lzt.fast_buy(item_id, price)


async def buy_one(bot, lzt, tg_id: int, item: dict, s: dict) -> str | None:
    """check → authoritative filter → balance for the *current* price → buy."""
    item_id = item["item_id"]
    search_price = db.num(item.get("price"))
    currency = s["currency"]

    try:
        chk = await lzt.check_account(item_id)
    except LztError as e:
        log.info(f"check {item_id}: {e}")
        return None

    fresh = dict(item)
    fresh.update({k: v for k, v in (chk.get("item") or {}).items() if v not in (None, "")})

    price = db.num(fresh.get("price"), search_price)
    ok, why = passes(fresh, s, authoritative=True)
    if not ok:
        log.info(f"skip {item_id}: {why}")
        return None
    if why == "ok_unknown":
        log.info(f"note {item_id}: fields unknown, relying on server filters")

    try:
        balances = await lzt.balances()
    except LztError as e:
        log.info(f"balance: {e}")
        return None

    wallet = pick_for_buy(balances, currency, price)
    if wallet is None:
        have = spendable(balances, currency)
        await _balance_warn(bot, tg_id,
                            f"💳 Low balance {fmt_money(have, currency)} — buy paused")
        return None

    try:
        res = await _fast_buy(lzt, item_id, price, int(wallet.get("balance_id") or 0))
    except LztError as e:
        log.info(f"buy {item_id}: {e}")
        return None

    login_data = (res.get("item") or {}).get("loginData") or {}
    phone = login_data.get("login") or phone_of(fresh) or phone_of(item)
    password = login_data.get("password") or fresh.get("telegram_password") or ""

    target = db.num(s.get("session_life_hours"), 24.0) or 24.0
    created = account_created_ts(fresh) or 0
    age = age_hours_of(fresh) or 0.0
    delay = clean_delay_hours(fresh, target, s.get("early_clean_if_aged") == "1")
    expires = int(time.time() + delay * 3600)

    pid = await db.add_purchase(
        tg_id, item_id, phone, country_of(fresh), price,
        expires_at=expires, target_age_hours=target, age_at_buy_hours=age,
        account_created_ts=created, note="bought")

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
    try:
        await c.disconnect()
    except Exception:
        pass
    await asyncio.sleep(0)


async def _mail_client_for(p: dict, s: dict):
    """(client, address) — reuse the account mailbox when possible, else temp."""
    current = (p.get("mail") or "").split("@")[-1].lower()
    provider = s.get("mail_provider", "auto")
    if provider in ("auto", "native") and p.get("mail") and p.get("mail_password"):
        try:
            return IMAPMailClient(p["mail"], p["mail_password"]), p["mail"]
        except Exception as e:
            log.info(f"imap unavailable: {e}")
            if provider == "native":
                return None, ""
    mc = TempMailClient()
    return mc, await mc.create_temp_email(exclude_domains=[current] if current else None)


async def expire_purchase(bot, lzt, p: dict):
    s = await db.get_settings(p["tg_id"])
    tries = int(p.get("expiry_tries") or 0)

    if not p.get("session_string"):
        young = time.time() - p["started_at"] < EXPIRY_LOGIN_GRACE
        if tries < EXPIRY_RETRY and young:
            await db.bump_expiry(p["_id"], EXPIRY_RETRY_DELAY, inc_tries=True)
            return
        await db.close_purchase(p["_id"], "login_failed", "no session string")
        await _notify(bot, p["tg_id"], f"⚠️ <b>No session</b> <code>{p['phone']}</code>")
        return

    new_mail, note = "", []
    hard_fail = False
    c = client(p["session_string"], s["proxy"])
    try:
        await c.connect()
        if not await c.is_user_authorized():
            note.append("session dead")
            hard_fail = True
        else:
            if s["change_mail_on_expire"] == "1":
                mc, addr = await _mail_client_for(p, s)
                if mc is None:
                    note.append("mail skipped")
                else:
                    try:
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
        hard_fail = True
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass

    if hard_fail and tries < 3:
        await db.bump_expiry(p["_id"], EXPIRY_RETRY_DELAY, inc_tries=True)
        return

    try:
        await lzt.reset_authorizations(p["item_id"])
        note.append("lzt auth reset")
    except LztError as e:
        note.append(f"reset: {e}")

    await db.close_purchase(p["_id"], "terminated", "; ".join(note)[:300], new_mail=new_mail)
    await _notify(bot, p["tg_id"],
                  f"🧼 <b>Cleaned</b> <code>{p['phone']}</code>\n"
                  f"{'; '.join(note)}\n📧 <code>{new_mail or '-'}</code>")


async def _cycle(bot, lzt, tg_id: int, s: dict):
    cap = db.num(s.get("daily_spend_cap"))
    if cap > 0 and await db.spent_today(tg_id) >= cap:
        await db.save_report(tg_id, note="daily cap reached")
        return

    currency = s["currency"]
    floor_price = db.num(s.get("price_min"))

    try:
        balances = await lzt.balances()
    except LztError as e:
        await db.save_report(tg_id, error=f"balances: {e}")
        return

    have = spendable(balances, currency)
    if have < floor_price:
        await _balance_warn(bot, tg_id,
                            f"💳 Low balance {fmt_money(have, currency)} — buy paused")
        await db.save_report(tg_id, note=f"low balance {have:.2f}")
        return

    try:
        items = await _search_items(lzt, s)
    except LztError as e:
        await db.save_report(tg_id, error=f"search: {e}")
        return

    reasons: Counter = Counter()
    bought = 0
    max_buys = max(1, db.intval(s.get("max_buy_per_cycle"), 2))

    for it in items[:80]:
        ok, why = passes(it, s)
        if not ok:
            reasons[why] += 1
            continue
        if await buy_one(bot, lzt, tg_id, it, s):
            bought += 1
        else:
            reasons["buy_failed"] += 1
        if bought >= max_buys:
            break
        if cap > 0 and await db.spent_today(tg_id) >= cap:
            reasons["cap_hit"] += 1
            break

    log.info(f"[{tg_id}] scanned={len(items)} bought={bought} "
             f"rejects={dict(reasons.most_common(5))}")
    await db.save_report(tg_id, scanned=len(items), bought=bought, reasons=dict(reasons))


async def buy_loop(bot, lzt):
    while True:
        try:
            now = time.time()
            for u in await db.all_owners():
                tg_id = u["_id"]
                if _NEXT_RUN.get(tg_id, 0.0) > now:
                    continue
                s = await db.get_settings(tg_id)
                if s["auto_buy"] != "1":
                    _NEXT_RUN[tg_id] = now + TICK
                    continue
                _NEXT_RUN[tg_id] = now + max(5, db.intval(s.get("poll_interval"), 25))
                await _cycle(bot, lzt, tg_id, s)
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