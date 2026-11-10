"""Async LZT Market API client — rate-limited, cached, typed errors."""
import asyncio
import time

import httpx

from app.config import CACHE_TTL, HTTP_TIMEOUT, LZT_BASE, LZT_TOKEN, SEARCH_DELAY
from app.utils.money import parse_balances, parse_user, pick_for_buy, spendable


class LztError(Exception):
    def __init__(self, msg, status=0, errors=None):
        super().__init__(msg)
        self.status, self.errors = status, errors or []

    @property
    def retryable(self) -> bool:
        return "retry" in str(self).lower()


class LztClient:
    def __init__(self, token: str = None):
        self.token = token or LZT_TOKEN
        self._search_lock = asyncio.Semaphore(1)
        self._last_search = 0.0
        self._cache: dict[str, tuple[float, object]] = {}
        self._http = httpx.AsyncClient(
            base_url=LZT_BASE, timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )

    async def close(self):
        await self._http.aclose()

    # ── plumbing ────────────────────────────────────────────────────────────
    def _cached(self, key: str):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        return None

    def _store(self, key: str, value):
        self._cache[key] = (time.time(), value)
        return value

    def invalidate_wallet(self):
        self._cache.pop("balances", None)
        self._cache.pop("profile", None)

    async def _req(self, method: str, path: str, **kw):
        for attempt in range(4):
            try:
                r = await self._http.request(method, path, **kw)
            except httpx.HTTPError as e:
                if attempt == 3:
                    raise LztError(f"network: {e}")
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429:
                await asyncio.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                try:
                    errs = r.json().get("errors", [])
                except Exception:
                    errs = [r.text[:200]]
                raise LztError("; ".join(errs) or f"HTTP {r.status_code}", r.status_code, errs)
            try:
                return r.json()
            except Exception:
                return {}

    async def _search(self, params: dict):
        async with self._search_lock:
            wait = SEARCH_DELAY - (time.time() - self._last_search)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_search = time.time()
            return await self._req("GET", "/telegram", params=params)

    # ── profile / wallet ────────────────────────────────────────────────────
    async def me_raw(self) -> dict:
        return await self._req("GET", "/me")

    async def profile(self) -> dict:
        cached = self._cached("profile")
        if cached is not None:
            return cached
        return self._store("profile", parse_user(await self.me_raw()))

    async def balances_raw(self) -> dict:
        return await self._req("GET", "/balance/exchange")

    async def balances(self) -> list[dict]:
        cached = self._cached("balances")
        if cached is not None:
            return cached
        return self._store("balances", parse_balances(await self.balances_raw()))

    async def balance_total(self, currency: str = "usd") -> float:
        """Spendable (market, non-TG) free amount in the given currency."""
        return spendable(await self.balances(), currency)

    async def balance_for_buy(self, currency: str, price: float) -> dict | None:
        """Balance entry that can cover `price`, or None."""
        return pick_for_buy(await self.balances(), currency, price)

    async def currency(self) -> dict:
        cached = self._cached("currency")
        if cached is not None:
            return cached
        return self._store("currency", await self._req("GET", "/currency"))

    async def exchange(self, from_balance: int, to_balance: int, amount: float) -> dict:
        res = await self._req(
            "POST", "/balance/exchange",
            json={"from_balance": from_balance, "to_balance": to_balance, "amount": amount},
        )
        self.invalidate_wallet()
        return res

    async def payments(self, page: int = 1, operation_type: str | None = None) -> list[dict]:
        key = f"payments:{page}:{operation_type or 'all'}"
        cached = self._cached(key)
        if cached is not None:
            return cached
        params = {"page": page}
        if operation_type:
            params["operation_type"] = operation_type
        data = await self._req("GET", "/user/payments", params=params)
        return self._store(key, data.get("payments") or data.get("operations") or [])

    # ── market ──────────────────────────────────────────────────────────────
    async def search(self, s: dict, cursor: str = None) -> list[dict]:
        p = {
            "pmin": s["price_min"], "pmax": s["price_max"],
            "spam": s["spam_mode"], "email": s["mail_mode"],
            "order_by": "price_to_up", "currency": s["currency"],
        }
        if s["password_mode"] != "any":
            p["password"] = s["password_mode"]
        if s["mail_type"] != "any":
            p["email_type[]"] = [s["mail_type"]]
        if s["nsb_only"] == "1":
            p["nsb"] = "true"
        if s["countries"]:
            p["country[]"] = [c.strip().upper() for c in s["countries"].split(",") if c.strip()]
        if s["deny_countries"]:
            p["not_country[]"] = [c.strip().upper() for c in s["deny_countries"].split(",") if c.strip()]
        hours = float(s["session_min_hours"] or 0)
        if hours >= 48:
            p["session_age"] = int(hours // 24)
            p["session_age_period"] = "day"
        if cursor:
            p["after"] = cursor
        return (await self._search(p)).get("items") or []

    async def item(self, item_id: int) -> dict:
        return (await self._req("GET", f"/{item_id}")).get("item") or {}

    async def check_account(self, item_id: int) -> dict:
        return await self._req("POST", f"/{item_id}/check-account")

    async def fast_buy(self, item_id: int, price: float, balance_id: int | None = None) -> dict:
        body = {"price": price}
        if balance_id:
            body["balance_id"] = balance_id
        for attempt in range(6):
            try:
                res = await self._req("POST", f"/{item_id}/fast-buy", json=body)
                self.invalidate_wallet()
                return res
            except LztError as e:
                if e.retryable and attempt < 5:
                    await asyncio.sleep(2.5)
                    continue
                raise
        raise LztError("fast-buy retries exhausted")

    async def telegram_login_code(self, item_id: int):
        try:
            codes = (await self._req("GET", f"/{item_id}/telegram-login-code")).get("codes") or {}
            return codes.get("code"), codes.get("date")
        except LztError:
            return None, None

    async def reset_authorizations(self, item_id: int):
        return await self._req("POST", f"/{item_id}/telegram-reset-authorizations")

    async def email_code(self, item_id: int):
        try:
            d = await self._req("GET", f"/{item_id}/email-code")
            codes = d.get("codes")
            return codes.get("code") if isinstance(codes, dict) else d.get("code")
        except LztError:
            return None

    async def set_email(self, item_id: int, email_login_data: str, email_type: str = "autoreg"):
        return await self._req(
            "PUT", f"/{item_id}/edit",
            json={"email_login_data": email_login_data, "email_type": email_type},
        )

    async def orders(self, page: int = 1) -> list[dict]:
        data = await self._req("GET", "/user/orders", params={"page": page})
        return data.get("items") or []

    async def tags(self) -> list[dict]:
        data = await self._req("GET", "/user/tags")
        return data.get("tags") or []

    async def me(self) -> dict:
        return await self.me_raw()