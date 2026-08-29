"""Почта из живой реплики.

Человек не заполняет форму — он пишет в чат. Адрес приходит с запятой,
в скобках, в кавычках, посреди фразы, и от того, вытащим мы его или нет,
зависит, получит ли он доступ, за который заплатил.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.purchase import email_in, offer_for  # noqa: E402


def test_plain_address():
    assert email_in("ivan@example.com") == "ivan@example.com"


def test_address_inside_a_sentence():
    assert email_in("оплатил, почта ivan@example.com, жду доступ") == "ivan@example.com"


def test_trailing_period_is_not_part_of_the_address():
    assert email_in("моя почта ivan@example.com.") == "ivan@example.com"


def test_address_in_brackets_and_quotes():
    assert email_in('платил с "ivan.petrov@mail.ru" (основная)') == "ivan.petrov@mail.ru"


def test_case_is_normalised():
    """В кассе адрес лежит как ввёл покупатель — сравнивать надо одинаково."""
    assert email_in("IVAN@Example.COM") == "ivan@example.com"


def test_plus_and_dashes_survive():
    assert email_in("ivan+lava@my-mail.co.uk") == "ivan+lava@my-mail.co.uk"


def test_no_address():
    for text in ("оплатил", "", "собака@ но без домена", "просто текст"):
        assert email_in(text) == "", text


def test_offer_lookup():
    offers = {"buy_base": "aaa", "buy_premium": "bbb"}
    assert offer_for("buy_premium", offers) == "bbb"
    assert offer_for("buy_pro", offers) == ""
