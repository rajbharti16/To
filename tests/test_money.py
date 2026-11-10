import pytest

from app.utils.money import fmt_money, parse_balances, parse_user


def test_parse_user_shape():
    u = parse_user({"user": {"user_id": 7, "username": "x", "balance": "12.50",
                             "hold": "1.50", "currency": "USD", "sympathies": 200}})
    assert u["balance"] == 12.5 and u["hold"] == 1.5 and u["currency"] == "usd"
    assert u["username"] == "x"


def test_parse_balances_list():
    b = parse_balances({"balances": [{"balance_id": 1, "currency": "usd", "balance": 5, "hold": 1}]})
    assert b[0]["amount"] == 5.0 and b[0]["hold"] == 1.0


def test_parse_balances_dict():
    b = parse_balances({"balances": {"usd": "3.5", "rub": 900}})
    assert {x["currency"] for x in b} == {"usd", "rub"}


def test_parse_balances_fallback_user():
    b = parse_balances({"user": {"balance": 2, "currency": "eur"}})
    assert b[0]["currency"] == "eur" and b[0]["amount"] == 2.0


def test_parse_balances_empty():
    assert parse_balances({}) == []


def test_parse_garbage_numbers():
    assert parse_balances({"balances": [{"currency": "usd", "balance": "abc"}]})[0]["amount"] == 0.0


@pytest.mark.parametrize("amount,cur,expected", [(1234.5, "usd", "$1,234.50"), (7, "rub", "₽7.00")])
def test_fmt_money(amount, cur, expected):
    assert fmt_money(amount, cur) == expected