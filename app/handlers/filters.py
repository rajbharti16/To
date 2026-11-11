from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import db, keyboards as kb
from app.handlers.menu import show
from app.utils.texts import filters_text

router = Router()

PENDING_TTL = 300.0
PENDING: dict[int, tuple[str, float]] = {}

# key -> (label, hint, lo, hi, decimals)
NUMERIC = {
    "price_min": ("Min price", "cheapest allowed account price", 0.01, 10_000.0, 2),
    "price_max": ("Max price", "most expensive allowed account price", 0.01, 10_000.0, 2),
    "session_min_hours": ("Min session age", "0 = any · hours (day granularity above 24)",
                          0.0, 8_760.0, 1),
    "session_life_hours": ("Target age", "0 = clean immediately · hours", 0.0, 8_760.0, 1),
    "daily_spend_cap": ("Daily spend cap", "0 = unlimited", 0.0, 100_000.0, 2),
    "max_buy_per_cycle": ("Buys per cycle", "1-50", 1.0, 50.0, 0),
    "poll_interval": ("Poll interval", "seconds, 5-3600", 5.0, 3_600.0, 0),
}

COUNTRY_KEYS = {
    "countries": "only these countries get bought",
    "deny_countries": "these countries are skipped",
}


def _set_pending(uid: int, key: str):
    PENDING[uid] = (key, __import__("time").time())


def _pop_pending(uid: int) -> str | None:
    hit = PENDING.pop(uid, None)
    if not hit:
        return None
    key, ts = hit
    return key if __import__("time").time() - ts <= PENDING_TTL else None


def _fmt(key: str, value: float) -> str:
    return f"{value:.{NUMERIC[key][4]}f}".rstrip("0").rstrip(".") or "0"


@router.callback_query(F.data == "m:filters")
async def cb_filters(cq: CallbackQuery):
    s = await db.get_settings(cq.from_user.id)
    await show(cq, filters_text(s), kb.filters(s))
    await cq.answer()


@router.callback_query(F.data == "m:price")
async def cb_price(cq: CallbackQuery):
    await show(cq, "<b>Price</b>\nmax picks top, min picks bottom", kb.price())
    await cq.answer()


@router.callback_query(F.data == "m:spam")
async def cb_spam(cq: CallbackQuery):
    await show(cq, "<b>Spam filter</b>", kb.pick("s:spam_mode", ["no", "yes", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:mail")
async def cb_mail(cq: CallbackQuery):
    await show(cq, "<b>Mail filter</b>", kb.pick("s:mail_mode", ["yes", "no", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:pass")
async def cb_pass(cq: CallbackQuery):
    await show(cq, "<b>2FA filter</b>", kb.pick("s:password_mode", ["no", "yes", "any"]))
    await cq.answer()


@router.callback_query(F.data == "m:sess")
async def cb_sess(cq: CallbackQuery):
    await show(cq, "<b>Min session age</b> (0 = any)", kb.floors())
    await cq.answer()


@router.callback_query(F.data == "m:life")
async def cb_life(cq: CallbackQuery):
    await show(cq, "<b>Target age</b>\nreached target → auto clean", kb.targets())
    await cq.answer()


@router.callback_query(F.data.startswith("s:"))
async def cb_set(cq: CallbackQuery):
    parts = cq.data.split(":", 2)
    if len(parts) != 3:
        return await cq.answer("bad callback", show_alert=False)
    _, key, value = parts
    stored = await db.set_setting(cq.from_user.id, key, value)
    if stored is None:
        return await cq.answer("unknown setting", show_alert=True)
    s = await db.get_settings(cq.from_user.id)
    await show(cq, filters_text(s), kb.filters(s))
    await cq.answer("saved")


@router.callback_query(F.data.startswith("in:"))
async def cb_input(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    if key in COUNTRY_KEYS:
        hint = COUNTRY_KEYS[key]
        body = (f"Send ISO codes, comma separated (e.g. <code>AE,LY,JO</code>)\n"
                f"<code>all</code> = clear · /cancel")
    elif key in NUMERIC:
        label, hint, lo, hi, _ = NUMERIC[key]
        body = f"Send a number ({lo:g}-{hi:g}) · /cancel"
    else:
        return await cq.answer("unknown setting", show_alert=True)

    _set_pending(cq.from_user.id, key)
    await cq.message.answer(
        f"<b>{NUMERIC.get(key, (key.replace('_', ' '),))[0]}</b>\n{hint}\n\n{body}",
        reply_markup=kb.kb([[("Cancel", "x")]]))
    await cq.answer()


@router.callback_query(F.data == "x")
async def cb_cancel(cq: CallbackQuery):
    PENDING.pop(cq.from_user.id, None)
    await cq.message.answer("cancelled", reply_markup=kb.back("m:filters"))
    await cq.answer()


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    PENDING.pop(m.from_user.id, None)
    await m.answer("cancelled")


@router.message(F.text)
async def on_text(m: Message):
    if (m.text or "").startswith("/"):
        return  # keep the pending value alive across commands
    key = _pop_pending(m.from_user.id)
    if not key:
        return

    raw = m.text.strip().replace(" ", "").replace(",", ".")

    if key in COUNTRY_KEYS:
        if raw.lower() in ("all", "-", "clear"):
            val = ""
        else:
            codes = [c.upper() for c in raw.split(",") if len(c) == 2 and c.isalpha()]
            if not codes:
                _set_pending(m.from_user.id, key)
                return await m.answer("need ISO codes like AE,LY · /cancel")
            val = ",".join(dict.fromkeys(codes))
        stored = await db.set_setting(m.from_user.id, key, val)
    else:
        label, _, lo, hi, _ = NUMERIC[key]
        try:
            number = float(raw)
        except ValueError:
            _set_pending(m.from_user.id, key)
            return await m.answer(f"{label}: number expected · /cancel")
        if not lo <= number <= hi:
            _set_pending(m.from_user.id, key)
            return await m.answer(f"{label}: use {lo:g}-{hi:g} · /cancel")
        stored = await db.set_setting(m.from_user.id, key, _fmt(key, number))

    if stored is None:
        return await m.answer("unknown setting")

    note = ""
    if key == "session_min_hours":
        hours = db.num(stored)
        if 0 < hours < 24:
            note = ("\n⚠️ below 24h the market filter cannot apply (day granularity) — "
                    "those items get checked locally after check-account")
        elif hours:
            note = f"\n⏱ filter sent to market: {hours / 24:.0f} day(s)+"

    s = await db.get_settings(m.from_user.id)
    await m.answer(f"✅ <b>saved</b>: <code>{stored or '-'}</code>{note}",
                   reply_markup=kb.back("m:filters"))
    await m.answer(filters_text(s), reply_markup=kb.filters(s))