import pytest

from app.utils.money import (canon, fmt_money, parse_balances, parse_user,
                             pick_for_buy, same_currency, spendable)

# exact shape unknown -> parser must find entries anywhere
NESTED = {"data": {"balances": {"items": [
    {"balance_id": 1, "currency": "usdt", "title": "Market balance", "balance": 2.78},
    {"balance_id": 2, "currency": "usdt", "title": "TG wallet", "balance": 0},
]}}}

FLAT = {"balances": [
    {"balance_id": 1, "currency": "usdt", "type": "market", "balance": 2.78},
    {"balance_id": 2, "currency": "usdt", "type": "telegram", "balance": 0},
]}


def test_alias():
    assert canon("USDT") == "usd"
    assert same_currency("usdt", "usd")


def test_nested_discovery():
    b = parse_balances(NESTED)
    assert len(b) == 2 and b[0]["kind"] == "market"


def test_flat_kind():
    b = parse_balances(FLAT)
    assert b[0]["usable_for_buy"] is True and b[1]["usable_for_buy"] is False


def test_spendable():
    assert spendable(parse_balances(FLAT), "usd") == 2.78


def test_pick_prefers_market():
    assert pick_for_buy(parse_balances(FLAT), "usd", 0.5)["balance_id"] == 1


def test_pick_insufficient():
    assert pick_for_buy(parse_balances(FLAT), "usd", 99) is None


def test_profile_fallback():
    b = parse_balances({"user": {"currency": "usdt", "balance": "3.5"}})
    assert b[0]["amount"] == 3.5


def test_unlabelled_is_usable():
    b = parse_balances({"balances": [{"currency": "usd", "balance": 5}]})
    assert b[0]["usable_for_buy"] is True


def test_dedupe():
    one = {"balances": [{"balance_id": 1, "currency": "usd", "balance": 1}]}
    one["balances"].append(dict(one["balances"][0]))
    assert len(parse_balances(one)) == 1


def test_fmt():
    assert fmt_money(2.78, "usdt") == "2.78 USDT"


@pytest.mark.parametrize("amount", ["abc", None])
def test_garbage(amount):
    assert parse_balances({"balances": [{"currency": "usd", "balance": amount}]})[0]["amount"] == 0.0


def test_parse_user():
    u = parse_user({"user": {"username": "x", "balance": "1.5", "currency": "USDT"}})
    assert u["currency"] == "usd" and u["balance"] == 1.5