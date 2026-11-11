from app.utils.filters import clean_delay_hours, passes, session_hours
from conftest import BASE


def item(**kw):
    base = {"item_id": 1, "price": 0.2, "title": "Jordan (JO) — +962792671573",
            "telegram_session_age": 23.5 * 3600, "telegram_email": "a@b.c", "nsb": True}
    base.update(kw)
    return base


S = {**BASE, "session_min_hours": "0"}


def test_ok():
    assert passes(item(), S)[0] is True


def test_price():
    assert passes(item(price=5), S) == (False, "price_max")


def test_spam():
    assert passes(item(telegram_spam_block=True), S)[0] is False


def test_include_only():
    assert passes(item(), {**S, "countries": "AE"}) == (False, "country_not_included")
    assert passes(item(), {**S, "countries": "JO"})[0] is True


def test_exclude():
    assert passes(item(), {**S, "deny_countries": "JO"}) == (False, "country_excluded")


def test_floor_off_by_default():
    fresh = item(telegram_session_age=1 * 3600)
    assert passes(fresh, S)[0] is True
    assert passes(fresh, {**S, "session_min_hours": "20"}) == (False, "session_too_fresh")


def test_above_target_cleans_now():
    old = item(telegram_session_age=30 * 3600)
    assert passes(old, S)[0] is True
    assert clean_delay_hours(old, 24) == 0.0


def test_queue_waits_remaining():
    assert clean_delay_hours(item(telegram_session_age=23 * 3600), 24) == 1.0
    assert clean_delay_hours(item(telegram_session_age=23 * 3600 + 2400), 24) == pytest_almost(1 / 3.6)


def pytest_almost(v):
    return round(v, 4)


def test_session_hours_units():
    assert session_hours({"telegram_session_age": 7200}) == 2
    assert session_hours({"telegram_session_age": 2}) == 2