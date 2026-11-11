"""LZT Market API client — typed, mapping-corrected, tolerant."""
import logging

import httpx

from app.config import HTTP_TIMEOUT, LZT_BASE, LZT_TOKEN
from app.utils.money import parse_balances, parse_user

log = logging.getLogger("lzt")


class LztError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _message(payload) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "errors"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict) and v:
                first = next(iter(v.values()))
                if isinstance(first, (str, list)):
                    return str(first)
    return ""


class LztClient:
    def __init__(self, token: str = LZT_TOKEN):
        self._token = token
        self._http = httpx.AsyncClient(
            base_url=LZT_BASE,
            timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/json",
                     "User-Agent": "AccStore/2.0"},
        )

    async def close(self):
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            r = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise LztError(f"network: {e}")

        try:
            payload = r.json() if r.content else {}
        except ValueError:
            payload = {}

        if r.status_code >= 400:
            msg = _message(payload) or f"HTTP {r.status_code}"
            raise LztError(msg, r.status_code)

        if isinstance(payload, dict) and payload.get("errors"):
            msg = _message(payload)
            if msg:
                raise LztError(msg, r.status_code)

        return payload if isinstance(payload, dict) else {}

    async def _get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params or {})

    async def _post(self, path: str, params: dict | None = None,
                    json: dict | None = None) -> dict:
        return await self._request("POST", path, params=params or {}, json=json)

    # ── profile / balances ────────────────────────────────────────────────

    async def profile(self) -> dict:
        return parse_user(await self._get("/me"))

    async def balances(self) -> list[dict]:
        return parse_balances(await self._get("/balance/exchange"))

    async def balance_total(self, currency: str = "usd") -> float:
        return parse_user(await self._get("/me"))["balance"]

    async def payments(self, page: int = 1) -> list[dict]:
        data = await self._get("/payments", {"page": page, "limit": 20})
        return data.get("payments") or []

    async def exchange(self, from_id: int, to_id: int, amount: float) -> dict:
        return await self._post("/balance/exchange", {
            "balance_id_from": int(from_id),
            "balance_id_to": int(to_id),
            "amount": float(amount),
        })

    # ── market ────────────────────────────────────────────────────────────

    @staticmethod
    def _enum(value: str) -> str:
        return "nomatter" if value == "any" else value

    def _search_params(self, s: dict) -> dict:
        params: dict = {
            "pmin": s.get("price_min"),
            "pmax": s.get("price_max"),
            "currency": s.get("currency", "usd"),
            "order_by": "price_to_up",
            "spam": self._enum(s.get("spam_mode", "no")),
            "email": self._enum(s.get("mail_mode", "any")),
            "password": self._enum(s.get("password_mode", "any")),
        }
        if s.get("nsb_only") == "1":
            params["nsb"] = "true"

        allow = [c for c in (s.get("countries") or "").split(",") if c]
        deny = [c for c in (s.get("deny_countries") or "").split(",") if c]
        if allow:
            params["country[]"] = allow
        if deny:
            params["not_country[]"] = deny

        if s.get("session_age"):
            params["session_age"] = s["session_age"]
            params["session_age_period"] = s.get("session_age_period", "day")

        return {k: v for k, v in params.items() if v not in (None, "", [])}

    async def search(self, s: dict) -> list[dict]:
        data = await self._get("/telegram", self._search_params(s))
        return data.get("items") or []

    async def check_account(self, item_id: int) -> dict:
        return await self._post(f"/{int(item_id)}/check-account")

    async def fast_buy(self, item_id: int, price: float, balance_id: int | None = None) -> dict:
        params = {"price": float(price)}
        if balance_id:
            params["balance_id"] = int(balance_id)
        return await self._post(f"/{int(item_id)}/fast-buy", params=params)

    async def reset_authorizations(self, item_id: int) -> dict:
        return await self._post(f"/{int(item_id)}/reset-authorizations")

    async def telegram_login_code(self, item_id: int) -> tuple[str, str]:
        data = await self._get(f"/{int(item_id)}/telegram-login-code")
        item = data.get("item") or data
        return str(item.get("code") or ""), str(item.get("mode") or "")