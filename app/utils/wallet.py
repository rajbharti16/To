"""Balance snapshot: authoritative market total + spendable entries.

`balances()` alone is not enough — the real money lives on the user object, and
the per-balance list can be empty or hold only the TG wallet. The total is
therefore read independently and the list only refines it.
"""
import logging

from app.utils.money import free_of, spendable, total_of

log = logging.getLogger("wallet")


def _coerce(entry) -> list[dict]:
    return [b for b in (entry or []) if isinstance(b, dict)]


async def snapshot(lzt, currency: str) -> dict:
    """{'total', 'spendable', 'entries', 'currency', 'note', 'error'}"""
    snap = {"total": 0.0, "spendable": 0.0, "entries": [], "currency": currency,
            "note": "", "error": ""}

    entries: list[dict] = []
    try:
        entries = _coerce(await lzt.balances())
    except Exception as e:
        snap["error"] = str(e)
        log.info(f"balances: {e}")

    spend = spendable(entries, currency)

    total = spend
    try:
        total = max(total, float(await lzt.balance_total(currency)))
    except AttributeError:
        try:
            total = max(total, total_of(await lzt.profile(), currency))
        except Exception as e:
            if not snap["error"]:
                snap["error"] = str(e)
    except Exception as e:
        if not snap["error"]:
            snap["error"] = str(e)

    if total > 0 and not any(b["usable_for_buy"] and free_of(b) >= total for b in entries):
        if not entries:
            entries = [{
                "balance_id": 0, "currency": currency, "amount": total, "hold": 0.0,
                "kind": "market", "label": "Market balance", "usable_for_buy": True,
            }]
            snap["note"] = "no balance ids exposed"

    others = {b["currency"] for b in entries if b["currency"]}
    if others and currency not in others:
        snap["note"] = f"balances in {', '.join(sorted(others))}, settings say {currency}"

    snap["entries"] = entries
    snap["spendable"] = spend
    snap["total"] = max(total, spend)
    return snap


def usable_entries(snap: dict) -> list[dict]:
    return [b for b in snap["entries"] if b["usable_for_buy"]]


def exchangable(snap: dict) -> list[dict]:
    return [b for b in snap["entries"] if b["usable_for_buy"] and free_of(b) > 0]