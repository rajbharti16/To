"""Async LZT Market API client with rate-limit guards."""
import asyncio
import time

import httpx

from app.config import HTTP_TIMEOUT, LZT_BASE, LZT_TOKEN, SEARCH_DELAY


class LztError(Exception):
    def __init__(self, msg, status=0, errors=None):
        super().__init__(msg)
        self.status, self.errors = status, errors or []


class LztClient:
    def __init__(self, token: str = None):
        self.token = token or LZT_TOKEN
        self._search_lock = asyncio.Semaphore(1)
        self._last_search = 0.0
        self._http = httpx.AsyncClient(
            base_url=LZT_BASE, timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )

    async def close(self):
        await self._http.aclose()

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
        raise LztError("rate limited")

    async def _search(self, params: dict):
        async with self._search_lock:
            wait = SEARCH_DELAY - (time.time() - self._last_search)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_search = time.time()
            return await self._req("GET", "/telegram", params=params)

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

    async def fast_buy(self, item_id: int, price: float) -> dict:
        for attempt in range(6):
            try:
                return await self._req("POST", f"/{item_id}/fast-buy", json={"price": price})
            except LztError as e:
                if "retry" in str(e).lower() and attempt < 5:
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

    async def me(self) -> dict:
        return await self._req("GET", "/me")