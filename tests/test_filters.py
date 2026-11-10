from app.utils.filters import country_of, passes, session_hours
from conftest import BASE


def item(**kw):
    base = {"item_id": 1, "price": 0.2, "title": "Jordan (JO) — +962792671573",
            "telegram_session_age": 25 * 3600, "telegram_email": "a@b.c",
            "nsb": True}
    base.update(kw)
    return base


def test_pass_clean_item():
    assert passes(item(), BASE)[0] is True


def test_price_bounds():
    assert passes(item(price=0.05), BASE)[0] is False
    assert passes(item(price=5), BASE)[0] is False


def test_spam_filtered():
    assert passes(item(telegram_spam_block=True), BASE) == (False, "spam")
    assert passes(item(telegram_spam_block=True), {**BASE, "spam_mode": "any"})[0] is True


def test_mail_required():
    assert passes(item(telegram_email=None, email_type="no"), BASE)[0] is False
    assert passes(item(telegram_email=None, email_type="no"),
                  {**BASE, "mail_mode": "no"})[0] is True


def test_session_age():
    assert passes(item(telegram_session_age=10 * 3600), BASE)[0] is False
    assert session_hours({"telegram_session_age": 7200}) == 2


def test_country_allow_and_deny():
    assert passes(item(), {**BASE, "countries": "AE"})[0] is False
    assert passes(item(title="Iran (IR) — +98912"), BASE)[0] is False
    assert country_of(item()) == "JO"


def test_nsb():
    assert passes(item(nsb=False), BASE)[0] is False
    assert passes(item(nsb=False), {**BASE, "nsb_only": "0"})[0] is True