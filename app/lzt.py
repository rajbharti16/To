"""Async LZT Market API client — rate-limited, cached, typed errors."""
import asyncio
import time

import httpx

from app.config import CACHE_TTL, HTTP_TIMEOUT, LZT_BASE, LZT_TOKEN, SEARCH_DELAY
from app.utils.filters import search_query
from app.utils.money import (parse_balances, parse_user, pick_for_buy,
                             same_currency, spendable)

CACHE_MAX = 200
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LztError(Exception):
    def __init__(self, msg, status=0, errors=None):
        super().__init__(msg)
        self.status, self.errors = status, errors or []

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE_STATUS or "retry" in str(self).lower()


class LztClient:
    def __init__(self, token: str = None):
        self.token = token or LZT_TOKEN
        self._search_lock = asyncio.Semaphore(1)
        self._last_search = 0.0
        self._cache: dict[str, tuple[float, object]] = {}
        self._raw_balances: dict = {}
        self._http = httpx.AsyncClient(
            base_url=LZT_BASE, timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )

    async def close(self):
        await self._http.aclose()

    def _cached(self, key: str):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        return None

    def _store(self, key: str, value):
        if len(self._cache) >= CACHE_MAX:
            now = time.time()
            for k in [k for k, (ts, _) in self._cache.items() if now - ts >= CACHE_TTL]:
                self._cache.pop(k, None)
            if len(self._cache) >= CACHE_MAX:
                self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = (time.time(), value)
        return value

    def invalidate_wallet(self):
        self._cache.pop("balances", None)
        self._cache.pop("profile", None)

    @staticmethod
    def _retry_after(r: httpx.Response, attempt: int) -> float:
        try:
            return max(1.0, float(r.headers.get("Retry-After")))
        except (TypeError, ValueError):
            return 5.0 * (attempt + 1)

    async def _req(self, method: str, path: str, **kw):
        last = "request failed"
        for attempt in range(4):
            try:
                r = await self._http.request(method, path, **kw)
            except httpx.HTTPError as e:
                last = f"network: {e}"
                if attempt == 3:
                    raise LztError(last)
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429:
                last = "retry: 429 too many requests"
                if attempt == 3:
                    raise LztError(last, 429)
                await asyncio.sleep(self._retry_after(r, attempt))
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
        raise LztError(last, 429)

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
        data = await self._req("GET", "/balance/exchange")
        self._raw_balances = data if isinstance(data, dict) else {"raw": data}
        return self._raw_balances

    async def balances(self) -> list[dict]:
        cached = self._cached("balances")
        if cached is not None:
            return cached
        parsed = parse_balances(await self.balances_raw())
        return self._store("balances", parsed)

    async def balance_total(self, currency: str = "usd") -> float:
        """Spendable market amount; falls back to the profile balance."""
        total = spendable(await self.balances(), currency)
        if total > 0:
            return total
        try:
            prof = await self.profile()
        except LztError:
            return 0.0
        if same_currency(prof["currency"], currency):
            return max(0.0, prof["balance"] - prof["hold"])
        return 0.0

    async def balance_for_buy(self, currency: str, price: float) -> dict | None:
        chosen = pick_for_buy(await self.balances(), currency, price)
        if chosen:
            return chosen
        if await self.balance_total(currency) >= price:
            return {"balance_id": 0, "currency": currency, "amount": price,
                    "hold": 0.0, "kind": "other", "label": "Profile balance",
                    "usable_for_buy": True}
        return None

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
            # API enums are yes / no / nomatter — "any" must be translated
            "spam": "nomatter" if s["spam_mode"] == "any" else s["spam_mode"],
            "email": "nomatter" if s["mail_mode"] == "any" else s["mail_mode"],
            "order_by": "price_to_up", "currency": s["currency"],
        }
        if s.get("password_mode") not in (None, "", "any"):
            p["password"] = s["password_mode"]
        if s.get("mail_type") not in (None, "", "any"):
            p["email_type[]"] = [s["mail_type"]]
        if s.get("nsb_only") == "1":
            p["nsb"] = "true"
        if s.get("countries"):
            p["country[]"] = [c.strip().upper() for c in s["countries"].split(",") if c.strip()]
        if s.get("deny_countries"):
            p["not_country[]"] = [c.strip().upper() for c in s["deny_countries"].split(",") if c.strip()]
        # single source of truth for the age floor (day/month granularity only)
        p.update(search_query(s))
        if cursor:
            p["after"] = cursor
        return (await self._search(p)).get("items") or []

    async def item(self, item_id: int) -> dict:
        return (await self._req("GET", f"/{item_id}")).get("item") or {}

    async def check_account(self, item_id: int) -> dict:
        for attempt in range(3):
            try:
                return await self._req("POST", f"/{item_id}/check-account")
            except LztError as e:
                if e.retryable and attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise
        raise LztError("check-account retries exhausted")

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