import pytest

from app.mail_engine import extract_telegram_code

CASES = [
    ("Your Code - 271513", "271513"),
    ("Your login code is 849201", "849201"),
    ("Login code: 123 456", "123456"),
    ("123456 is your Telegram code", "123456"),
    ("رمزك هو: 16401", "16401"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_extracts(text, expected):
    assert extract_telegram_code(text) == expected


def test_expected_length_respected():
    assert extract_telegram_code("code 123456", expected_length=5) == "12345"


def test_empty():
    assert extract_telegram_code("") is None