"""MongoDB storage layer (pymongo async)."""
import time

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, AsyncMongoClient

from app.config import MONGO_DB, MONGO_URI

DEFAULTS = {
    "price_min": "0.05", "price_max": "0.50",
    "spam_mode": "no", "mail_mode": "yes", "mail_type": "any", "password_mode": "any",
    "session_min_hours": "20", "session_life_hours": "24",
    "countries": "", "deny_countries": "",
    "nsb_only": "1", "max_buy_per_cycle": "3", "daily_spend_cap": "15",
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


# --- pymongo-async cursor helpers -------------------------------------------
# aggregate() is a coroutine in the async API and resolves to a cursor, while
# find() returns the cursor directly. These helpers keep that asymmetry in one
# place instead of scattering `await` in the wrong spot.

async def _agg_one(collection, pipeline: list) -> dict | None:
    cursor = await collection.aggregate(pipeline)
    rows = await cursor.to_list(1)
    return rows[0] if rows else None


async def _find_all(cursor, limit=None) -> list[dict]:
    return await cursor.to_list(limit)


# ---------------------------------------------------------------------------

async def init_db():
    global _client, _db
    _client = AsyncMongoClient(MONGO_URI)
    _db = _client[MONGO_DB]
    await _db.purchases.create_index([("status", ASCENDING), ("expires_at", ASCENDING)])
    await _db.purchases.create_index([("tg_id", ASCENDING), ("started_at", ASCENDING)])
    await _db.purchases.create_index([("tg_id", ASCENDING), ("status", ASCENDING)])
    await _db.ledger.create_index([("tg_id", ASCENDING), ("created_at", ASCENDING)])
    await _db.ledger.create_index([("purchase_id", ASCENDING)])
    await _db.settings.create_index([("tg_id", ASCENDING)], unique=True)


async def close_db():
    global _client, _db
    if _client:
        await _client.close()
    _client = None
    _db = None


async def ensure_user(tg_id: int, username: str = ""):
    await _db.users.update_one(
        {"_id": tg_id},
        {"$setOnInsert": {"username": username, "created_at": _now()}},
        upsert=True,
    )
    await _db.settings.update_one(
        {"tg_id": tg_id}, {"$setOnInsert": {**DEFAULTS, "tg_id": tg_id}}, upsert=True
    )


async def get_settings(tg_id: int) -> dict:
    doc = await _db.settings.find_one({"tg_id": tg_id})
    if not doc:
        await _db.settings.update_one(
            {"tg_id": tg_id}, {"$setOnInsert": {**DEFAULTS, "tg_id": tg_id}}, upsert=True
        )
        return dict(DEFAULTS)
    doc.pop("_id", None)
    doc.pop("tg_id", None)
    return {**DEFAULTS, **doc}


async def set_setting(tg_id: int, key: str, value: str):
    await _db.settings.update_one(
        {"tg_id": tg_id}, {"$set": {key: str(value)}}, upsert=True
    )


async def all_owners() -> list[dict]:
    return await _find_all(_db.users.find({}, {"_id": 1}))


async def spent_today(tg_id: int) -> float:
    row = await _agg_one(_db.purchases, [
        {"$match": {"tg_id": tg_id, "started_at": {"$gte": _now() - 86400}}},
        {"$group": {"_id": None, "s": {"$sum": "$price"}}},
    ])
    return float(row["s"]) if row else 0.0


async def add_purchase(tg_id, item_id, phone, country, price, mail="", mail_password="",
                       session_string="", expires_at=0, status="active", note="") -> str:
    now = _now()
    pid = (await _db.purchases.insert_one({
        "tg_id": tg_id, "item_id": item_id, "phone": phone, "country": country,
        "price": float(price), "mail": mail, "mail_password": mail_password,
        "session_string": session_string, "status": status,
        "started_at": now, "expires_at": int(expires_at), "closed_at": 0, "note": note,
    })).inserted_id
    await _db.ledger.insert_one({
        "tg_id": tg_id, "purchase_id": pid, "item_id": item_id,
        "buy_price": float(price), "sell_price": 0.0, "status": "open",
        "created_at": now, "closed_at": 0, "extra": note,
    })
    return str(pid)


async def due_purchases() -> list[dict]:
    return await _find_all(_db.purchases.find(
        {"status": "active", "expires_at": {"$gt": 0, "$lte": _now()}}
    ))


async def active_purchases(tg_id: int) -> list[dict]:
    return await _find_all(
        _db.purchases.find({"tg_id": tg_id, "status": "active"}).sort("expires_at", ASCENDING)
    )


async def get_purchase(pid) -> dict | None:
    oid = _oid(pid)
    return await _db.purchases.find_one({"_id": oid}) if oid else None


async def set_session(pid, session_string: str):
    oid = _oid(pid)
    if oid:
        await _db.purchases.update_one(
            {"_id": oid}, {"$set": {"session_string": session_string}}
        )


async def close_purchase(pid, status: str, note: str = "", new_mail: str = ""):
    oid = _oid(pid)
    if not oid:
        return
    upd = {"status": status, "closed_at": _now(), "note": note}
    if new_mail:
        upd["mail"] = new_mail
    await _db.purchases.update_one({"_id": oid}, {"$set": upd})
    await _db.ledger.update_one(
        {"purchase_id": oid}, {"$set": {"status": status, "closed_at": _now(), "extra": note}}
    )


async def mark_sold(pid, sell_price: float):
    oid = _oid(pid)
    if not oid:
        return
    await _db.ledger.update_one(
        {"purchase_id": oid},
        {"$set": {"sell_price": float(sell_price), "status": "sold", "closed_at": _now()}},
    )
    await _db.purchases.update_one({"_id": oid}, {"$set": {"status": "sold"}})


async def ledger_rows(tg_id: int) -> list[dict]:
    return await _find_all(_db.ledger.find({"tg_id": tg_id}).sort("_id", -1).limit(500))


async def ledger_stats(tg_id: int) -> dict:
    # Single round trip: totals and the "done" count come back in one $facet.
    row = await _agg_one(_db.ledger, [
        {"$match": {"tg_id": tg_id}},
        {"$facet": {
            "agg": [
                {"$group": {"_id": None, "total": {"$sum": 1},
                            "spent": {"$sum": "$buy_price"},
                            "revenue": {"$sum": "$sell_price"}}},
            ],
            "done": [
                {"$match": {"status": {"$in": ["terminated", "sold"]}}},
                {"$count": "n"},
            ],
        }},
    ])

    agg = (row or {}).get("agg") or [{}]
    agg = agg[0]
    done = ((row or {}).get("done") or [{}])[0].get("n", 0)

    spent = float(agg.get("spent", 0.0) or 0.0)
    revenue = float(agg.get("revenue", 0.0) or 0.0)
    profit = revenue - spent
    return {
        "total": int(agg.get("total", 0) or 0),
        "spent": spent,
        "revenue": revenue,
        "profit": profit,
        "roi": (profit / spent * 100) if spent else 0.0,
        "done": int(done),
    }