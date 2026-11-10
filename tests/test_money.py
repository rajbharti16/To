import pytest

from app.utils.money import (canon, fmt_money, parse_balances, parse_user,
                             pick_for_buy, same_currency, spendable, total_any)

PAYLOAD = {"balances": [
    {"balance_id": 1, "currency": "usdt", "type": "market", "balance": 2.78, "hold": 0},
    {"balance_id": 2, "currency": "usdt", "type": "telegram", "balance": 0, "hold": 0},
]}


def test_alias():
    assert canon("USDT") == "usd"
    assert same_currency("usdt", "usd")
    assert not same_currency("usdt", "rub")


def test_kind_detection():
    b = parse_balances(PAYLOAD)
    assert b[0]["kind"] == "market" and b[0]["usable_for_buy"] is True
    assert b[1]["kind"] == "telegram" and b[1]["usable_for_buy"] is False


def test_spendable_ignores_telegram():
    b = parse_balances(PAYLOAD)
    assert spendable(b, "usd") == 2.78
    assert total_any(b, "usd") == 2.78


def test_pick_for_buy_uses_market():
    b = parse_balances(PAYLOAD)
    chosen = pick_for_buy(b, "usd", 0.5)
    assert chosen["balance_id"] == 1


def test_pick_for_buy_insufficient():
    assert pick_for_buy(parse_balances(PAYLOAD), "usd", 99) is None


def test_pick_never_telegram_only():
    b = parse_balances({"balances": [
        {"balance_id": 9, "currency": "usd", "type": "telegram", "balance": 50}]})
    assert pick_for_buy(b, "usd", 1) is None


def test_fmt():
    assert fmt_money(2.78, "usdt") == "2.78 USDT"
    assert fmt_money(2.5, "usd") == "$2.50"


@pytest.mark.parametrize("amount", ["abc", None])
def test_garbage(amount):
    b = parse_balances({"balances": [{"currency": "usd", "balance": amount}]})
    assert b[0]["amount"] == 0.0


def test_parse_user():
    u = parse_user({"user": {"username": "x", "balance": "1.5", "currency": "USDT"}})
    assert u["currency"] == "usd" and u["balance"] == 1.5