import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import db, engine
from app.config import OWNER_IDS
from app.deps import lzt
from app.utils import wallet as wallet_view
from app.utils.money import fmt_money

router = Router()


def _owner(m: Message) -> bool:
    return not OWNER_IDS or m.from_user.id in OWNER_IDS


@router.message(Command("addowner"))
async def cmd_addowner(m: Message):
    if not _owner(m):
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


@router.message(Command("buy"))
async def cmd_buy(m: Message):
    """Force one cycle right now."""
    if not _owner(m):
        return
    await db.set_setting(m.from_user.id, "auto_buy", "1")
    await m.answer("▶️ cycle started")
    asyncio.create_task(_run_once(m.bot, m.from_user.id))


async def _run_once(bot, tg_id: int):
    s = await db.get_settings(tg_id)
    await engine._cycle(bot, lzt, tg_id, s)
    row = (await db.recent_reports(tg_id, 1) or [{}])[0]
    bits = []
    if row.get("error"):
        bits.append(f"⚠️ {row['error']}")
    if row.get("note"):
        bits.append(row["note"])
    if row.get("scanned"):
        bits.append(f"scan {row['scanned']} · buy {row.get('bought', 0)}")
    reasons = row.get("reasons") or {}
    if reasons:
        top = ", ".join(f"{k}×{v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:4])
        bits.append(top)
    try:
        await bot.send_message(tg_id, "cycle: " + (" · ".join(bits) or "no data"))
    except Exception:
        pass


@router.message(Command("diag"))
async def cmd_diag(m: Message):
    """Show exactly what the buyer sees, so a blocked cycle is obvious."""
    if not _owner(m):
        return
    s = await db.get_settings(m.from_user.id)
    snap = await wallet_view.snapshot(lzt, s["currency"])
    spent = await db.spent_today(m.from_user.id)
    kinds = ", ".join(f"{b['kind']}:{b['amount']:g}" for b in snap["entries"]) or "none"
    await m.answer(
        "<b>diag</b>\n"
        f"auto_buy {s['auto_buy']} · cap ${s['daily_spend_cap']} · spent {spent:.2f}\n"
        f"price {s['price_min']}–{s['price_max']} · currency {s['currency']}\n"
        f"total {fmt_money(snap['total'], s['currency'])}"
        f" · spendable {fmt_money(snap['spendable'], s['currency'])}\n"
        f"entries {kinds}\n"
        f"note {snap['note'] or '—'}\n"
        f"error {snap['error'] or '—'}"
    )