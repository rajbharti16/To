"""
Mail engine: permutations, temp mail (Mail.tm → Tempmail.plus fallback), IMAP fetcher.
"""
import asyncio
import email as emaillib
import email.header
import heapq
import imaplib
import itertools
import json
import logging
import os
import random
import re
import string
import time
import urllib.error
import urllib.request

from app.config import DATA_DIR

VAULT = os.path.join(DATA_DIR, "temp_mail_vault.json")


class PermutationGenerator:
    GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

    def __init__(self, base_email: str):
        self.base_email = base_email.strip()
        parts = self.base_email.split("@")
        if len(parts) != 2:
            raise ValueError(f"Invalid email format: {base_email}")
        self.local_part, self.domain = parts[0], parts[1].lower()
        self.is_gmail = self.domain in self.GMAIL_DOMAINS
        clean = self.local_part.replace(".", "") if self.is_gmail else self.local_part
        letters = sum(1 for c in clean if c.isalpha())
        dot_combos = 2 ** (len(clean) - 1) if (self.is_gmail and len(clean) > 1) else 1
        self._total = (2 ** letters) * dot_combos
        self._cache: list[str] = []
        self._gen = self._build_stream()
        self._exhausted = False

    def _build_stream(self):
        clean = self.local_part.replace(".", "") if self.is_gmail else self.local_part
        slots = len(clean) - 1

        def choices_at(dot_set):
            out = []
            for i, ch in enumerate(clean):
                c = [ch.upper(), ch.lower()] if ch.isalpha() else [ch]
                out.append([x + "." for x in c] if i in dot_set else c)
            return out

        if not self.is_gmail or slots <= 0:
            for combo in itertools.product(*choices_at(set())):
                yield f"{''.join(combo)}@{self.domain}"
            return

        for k in range(slots + 1):
            if k == 0:
                for combo in itertools.product(*choices_at(set())):
                    yield f"{''.join(combo)}@{self.domain}"
                continue
            gens = []
            for dots in itertools.combinations(range(slots), k):
                ds = set(dots)
                gens.append(
                    (f"{''.join(c)}@{self.domain}" for c in itertools.product(*choices_at(ds)))
                )
            yield from heapq.merge(*gens)

    def _ensure(self, n):
        while len(self._cache) < n and not self._exhausted:
            try:
                self._cache.append(next(self._gen))
            except StopIteration:
                self._exhausted = True

    @property
    def total_permutations(self) -> int:
        return self._total

    def get_permutation(self, index: int) -> str:
        if not 0 <= index < self._total:
            raise IndexError(f"index {index} / max {self._total}")
        self._ensure(index + 1)
        return self._cache[index]

    def get_next_unused(self, used: list) -> str:
        used_set = set(used)
        for p in self._cache:
            if p not in used_set:
                return p
        while not self._exhausted:
            try:
                item = next(self._gen)
            except StopIteration:
                self._exhausted = True
                break
            self._cache.append(item)
            if item not in used_set:
                return item
        raise ValueError("All permutations exhausted")

    def remaining_count(self, used: list) -> int:
        return max(0, self._total - len(set(used)))


def extract_telegram_code(text: str, expected_length: int = None):
    if not text:
        return None
    t = text.replace("&nbsp;", " ").replace("\u00a0", " ").replace("\u200b", " ")
    t = re.sub(r"<[^>]+>", " ", t)
    ctx = (r"(?:your\s+(?:telegram\s+)?code|verification\s+code|login\s+code|telegram\s+code"
           r"|security\s+code|confirm(?:ation)?\s+code|código|код|رمز\w*)")
    for pat in (
        ctx + r"(?:\s+(?:is|was|to|هو))?[\s:=-]{1,10}(\d{3})[\s-](\d{3})\b",
        ctx + r"(?:\s+(?:is|was|to|هو))?[\s:=-]{1,10}(\d{5,6})\b",
        r"\b(\d{3})[\s-](\d{3})\b\s+(?:is\s+your\s+(?:telegram|verification|login|code))",
        r"\b(\d{5,6})\b\s+(?:is\s+your\s+(?:telegram|verification|login|code))",
    ):
        m = re.search(pat, t, re.I)
        if m:
            cand = "".join(m.groups())
            if expected_length is None or len(cand) == expected_length:
                return cand
    m = re.search(r"\b(\d{3})[\s-](\d{3})\b", t)
    if m and (expected_length is None or len(m.group(1) + m.group(2)) == expected_length):
        return m.group(1) + m.group(2)
    for c in re.findall(r"\b(\d{5,6})\b", t):
        if expected_length is None or len(c) == expected_length:
            return c
    return None


class TempMailClient:
    MAILTM = "https://api.mail.tm"
    PLUS = "https://tempmail.plus/api"
    PLUS_DOMAINS = ["fexbox.org", "fexpost.com", "mailbox.in.ua", "chitthi.in",
                    "rover.info", "mailto.plus", "fextemp.com", "anyalias.com"]
    _cooldown_until = 0.0

    def __init__(self):
        self._email = None
        self._token = None
        self._provider = None

    def _http(self, url, data=None, headers=None, method=None):
        hdrs = {"User-Agent": "Mozilla/5.0 (AccStore/1.0)", "Content-Type": "application/json"}
        hdrs.update(headers or {})
        body = json.dumps(data).encode() if isinstance(data, dict) else data
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            logging.warning(f"[MAIL] HTTP {e.code} {url}")
            raise

    async def _ahttp(self, *a, **k):
        return await asyncio.get_running_loop().run_in_executor(None, lambda: self._http(*a, **k))

    async def create_temp_email(self, exclude_domains: list = None) -> str:
        exclude = {d.lower().strip() for d in (exclude_domains or [])}

        if time.time() >= TempMailClient._cooldown_until:
            try:
                r = await self._ahttp(f"{self.MAILTM}/domains")
                doms = [d["domain"] for d in r.get("hydra:member", [])
                        if d.get("isActive") and d["domain"].lower() not in exclude]
                if doms:
                    addr = "tg_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
                    addr += "@" + random.choice(doms)
                    pw = "AccStore_" + "".join(random.choices(string.ascii_letters + string.digits, k=14))
                    await self._ahttp(f"{self.MAILTM}/accounts", {"address": addr, "password": pw})
                    tok = await self._ahttp(f"{self.MAILTM}/token", {"address": addr, "password": pw})
                    self._email, self._token, self._provider = addr, tok.get("token"), "mailtm"
                    self._persist(addr, pw)
                    return addr
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    TempMailClient._cooldown_until = time.time() + 600
            except Exception as e:
                logging.warning(f"[MAIL] mail.tm failed: {e}")

        doms = [d for d in self.PLUS_DOMAINS if d.lower() not in exclude] or self.PLUS_DOMAINS
        addr = "tg_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        addr += "@" + random.choice(doms)
        self._email, self._provider = addr, "plus"
        return addr

    def _persist(self, addr, pw):
        try:
            vault = {}
            if os.path.exists(VAULT):
                with open(VAULT, encoding="utf-8") as f:
                    vault = json.load(f)
            vault[addr] = {"password": pw, "provider": "mailtm",
                           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            with open(VAULT, "w", encoding="utf-8") as f:
                json.dump(vault, f, indent=2)
        except Exception as e:
            logging.warning(f"[MAIL] vault write failed: {e}")

    async def fetch_verification_code(self, target_email: str = None, timeout: int = 120,
                                     poll_interval: float = 3.0, expected_length: int = None) -> str:
        target = target_email or self._email
        if not target:
            raise ValueError("no active mailbox")
        start = time.time()
        while time.time() - start < timeout:
            try:
                code = await self._check_inbox(target, expected_length)
                if code:
                    return code
            except Exception as e:
                logging.warning(f"[MAIL] inbox error: {e}")
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"no code in {timeout}s for {target}")

    async def _check_inbox(self, target: str, expected_length=None):
        if self._provider == "mailtm" and self._token:
            return await self._check_mailtm(expected_length)
        return await self._check_plus(target, expected_length)

    async def _check_mailtm(self, expected_length=None):
        h = {"Authorization": f"Bearer {self._token}"}
        for m in (await self._ahttp(f"{self.MAILTM}/messages", headers=h)).get("hydra:member", []):
            if not m.get("id"):
                continue
            full = await self._ahttp(f"{self.MAILTM}/messages/{m['id']}", headers=h)
            code = extract_telegram_code(
                f"{full.get('subject','')} {full.get('text','') or full.get('html','')}",
                expected_length)
            if code:
                return code
        return None

    async def _check_plus(self, target: str, expected_length=None):
        r = await self._ahttp(f"{self.PLUS}/mails?email={target}&epin=&limit=15")
        for m in r.get("mail_list", []) or []:
            if m.get("id") is None:
                continue
            full = await self._ahttp(f"{self.PLUS}/mails/{m['id']}?email={target}&epin=")
            code = extract_telegram_code(f"{full.get('subject','')} {full.get('text','')}",
                                         expected_length)
            if code:
                return code
        return None


HOSTS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
         "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com",
         "live.com": "outlook.office365.com", "yandex.com": "imap.yandex.com",
         "yandex.ru": "imap.yandex.com", "mail.ru": "imap.mail.ru"}


class IMAPMailClient:
    def __init__(self, addr: str, password: str, host: str = None, port: int = 993):
        self.addr, self.password = addr, password
        self.host = host or HOSTS.get(addr.split("@")[-1].lower())
        self.port = port
        if not self.host:
            raise ValueError(f"no IMAP host known for {addr}")

    def _blocking(self, timeout: int):
        m = imaplib.IMAP4_SSL(self.host, self.port)
        try:
            m.login(self.addr, self.password)
            m.select("INBOX")
            end = time.time() + timeout
            while time.time() < end:
                _typ, data = m.search(None, "UNSEEN")
                for uid in reversed(data[0].split() if data and data[0] else []):
                    typ, msg_data = m.fetch(uid, "(RFC822)")
                    if typ != "OK" or not msg_data:
                        continue
                    msg = emaillib.message_from_bytes(msg_data[0][1])
                    subj = str(email.header.make_header(
                        email.header.decode_header(msg["Subject"] or "")))
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += part.get_payload(decode=True).decode("utf-8", "replace")
                    else:
                        body = (msg.get_payload(decode=True) or b"").decode("utf-8", "replace")
                    code = extract_telegram_code(f"{subj} {body}")
                    if code:
                        return code
                time.sleep(3)
            return None
        finally:
            try:
                m.logout()
            except Exception:
                pass

    async def fetch_verification_code(self, timeout: int = 120, expected_length=None) -> str:
        code = await asyncio.get_running_loop().run_in_executor(None, self._blocking, timeout)
        if not code:
            raise TimeoutError(f"no IMAP code in {timeout}s")
        return code