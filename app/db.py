"""MongoDB storage layer (pymongo async)."""
import time

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, AsyncMongoClient

from app.config import MONGO_DB, MONGO_URI

DEFAULTS = {
    "price_min": "0.05", "price_max": "1.00",
    "spam_mode": "no", "mail_mode": "yes", "mail_type": "any", "password_mode": "no",
    "session_min_hours": "0", "session_life_hours": "24",
    "countries": "", "deny_countries": "IR,RU",
    "nsb_only": "1", "max_buy_per_cycle": "2", "daily_spend_cap": "15",
    "poll_interval": "25", "auto_buy": "0",
    "terminate_on_expire": "1", "change_mail_on_expire": "1",
    "verify_spam": "1", "currency": "usd", "proxy": "", "mail_provider": "auto",
}

_client: AsyncMongoClient | None = None
_db = None


def _now() -> int:
    return int(time.time())


def _oid(pid):
    try:
        return ObjectId(str(pid))
    except (InvalidId, TypeError):
        return None


async def init_db():
    global _client, _db
    _client = AsyncMongoClient(MONGO_URI)
    _db = _client[MONGO_DB]
    await _db.purchases.create_index([("status", ASCENDING), ("expires_at", ASCENDING)])
    await _db.purchases.create_index([("tg_id", ASCENDING)])
    await _db.ledger.create_index([("tg_id", ASCENDING), ("created_at", ASCENDING)])
    await _db.settings.create_index([("tg_id", ASCENDING)], unique=True)


async def close_db():
    if _client:
        await _client.close()


async def ensure_user(tg_id: int, username: str = ""):
    await _db.users.update_one(
        {"_id": tg_id}, {"$setOnInsert": {"username": username, "created_at": _now()}}, upsert=True)
    await _db.settings.update_one(
        {"tg_id": tg_id}, {"$setOnInsert": {**DEFAULTS, "tg_id": tg_id}}, upsert=True)


async def get_settings(tg_id: int) -> dict:
    doc = await _db.settings.find_one({"tg_id": tg_id})
    if not doc:
        await _db.settings.insert_one({**DEFAULTS, "tg_id": tg_id})
        return dict(DEFAULTS)
    doc.pop("_id", None)
    doc.pop("tg_id", None)
    return {**DEFAULTS, **doc}


async def set_setting(tg_id: int, key: str, value: str):
    await _db.settings.update_one({"tg_id": tg_id}, {"$set": {key: str(value)}}, upsert=True)


async def all_owners() -> list[dict]:
    return await _db.users.find({}, {"_id": 1}).to_list(None)


async def spent_today(tg_id: int) -> float:
    cursor = await _db.purchases.aggregate([
        {"$match": {"tg_id": tg_id, "started_at": {"$gte": _now() - 86400}}},
        {"$group": {"_id": None, "s": {"$sum": "$price"}}},
    ])
    res = await cursor.to_list(length=1)
    return float(res[0]["s"]) if res else 0.0


async def add_purchase(tg_id, item_id, phone, country, price, mail="", mail_password="",
                       session_string="", expires_at=0, target_age_hours=24.0,
                       age_at_buy_hours=0.0, status="active", note="") -> str:
    now = _now()
    pid = (await _db.purchases.insert_one({
        "tg_id": tg_id, "item_id": item_id, "phone": phone, "country": country,
        "price": float(price), "mail": mail, "mail_password": mail_password,
        "session_string": session_string, "status": status,
        "started_at": now, "expires_at": int(expires_at),
        "target_age_hours": float(target_age_hours), "age_at_buy_hours": float(age_at_buy_hours),
        "closed_at": 0, "note": note,
    })).inserted_id
    await _db.ledger.insert_one({
        "tg_id": tg_id, "purchase_id": pid, "item_id": item_id,
        "buy_price": float(price), "sell_price": 0.0, "status": "open",
        "created_at": now, "closed_at": 0, "extra": note,
    })
    return str(pid)


async def due_purchases() -> list[dict]:
    return await _db.purchases.find(
        {"status": "active", "expires_at": {"$gt": 0, "$lte": _now()}}).to_list(None)


async def active_purchases(tg_id: int) -> list[dict]:
    return await _db.purchases.find({"tg_id": tg_id, "status": "active"}) \
        .sort("expires_at", ASCENDING).to_list(None)


async def queue_count(tg_id: int) -> int:
    return await _db.purchases.count_documents({"tg_id": tg_id, "status": "active"})


async def get_purchase(pid) -> dict | None:
    oid = _oid(pid)
    return await _db.purchases.find_one({"_id": oid}) if oid else None


async def find_by_phone(tg_id: int, needle: str) -> dict | None:
    return await _db.purchases.find_one(
        {"tg_id": tg_id, "phone": {"$regex": needle.lstrip("+")}}, sort=[("_id", -1)])


async def set_session(pid, session_string: str):
    oid = _oid(pid)
    if oid:
        await _db.purchases.update_one({"_id": oid}, {"$set": {"session_string": session_string}})


async def bump_expiry(pid, seconds: int):
    oid = _oid(pid)
    if oid:
        await _db.purchases.update_one({"_id": oid}, {"$inc": {"expires_at": seconds}})


async def close_purchase(pid, status: str, note: str = "", new_mail: str = ""):
    oid = _oid(pid)
    if not oid:
        return
    upd = {"status": status, "closed_at": _now(), "note": note}
    if new_mail:
        upd["mail"] = new_mail
    await _db.purchases.update_one({"_id": oid}, {"$set": upd})
    await _db.ledger.update_one(
        {"purchase_id": oid}, {"$set": {"status": status, "closed_at": _now(), "extra": note}})


async def mark_sold(pid, sell_price: float):
    oid = _oid(pid)
    if not oid:
        return
    await _db.ledger.update_one(
        {"purchase_id": oid},
        {"$set": {"sell_price": float(sell_price), "status": "sold", "closed_at": _now()}})
    await _db.purchases.update_one({"_id": oid}, {"$set": {"status": "sold"}})


async def ledger_rows(tg_id: int) -> list[dict]:
    return await _db.ledger.find({"tg_id": tg_id}).sort("_id", -1).limit(500).to_list(None)


async def ledger_stats(tg_id: int) -> dict:
    cursor = await _db.ledger.aggregate([
        {"$match": {"tg_id": tg_id}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "spent": {"$sum": "$buy_price"},
            "revenue": {"$sum": "$sell_price"}
        }},
    ])

    res = await cursor.to_list(length=1)

    row = res[0] if res else {
        "total": 0,
        "spent": 0.0,
        "revenue": 0.0
    }

    spent = float(row["spent"])
    revenue = float(row["revenue"])
    profit = revenue - spent

    done = await _db.ledger.count_documents({
        "tg_id": tg_id,
        "status": {"$in": ["terminated", "sold"]}
    })

    return {
        "total": int(row["total"]),
        "spent": spent,
        "revenue": revenue,
        "profit": profit,
        "roi": (profit / spent * 100) if spent else 0.0,
        "done": done
    }