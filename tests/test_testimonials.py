"""Отзывы: чужой опыт рядом с оффером.

Человек верит чужому опыту раньше, чем аргументу. Но отзыв не под ту тему
работает против нас: он показывает, что мы говорим не с ним.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
# Testimonial переименован при импорте: pytest пытается собрать любой класс,
# чьё имя начинается с Test, и ругается на конструктор.
from utils.testimonials import ANY, load_testimonials, pick  # noqa: E402
from utils.testimonials import Testimonial as Review  # noqa: E402

LOADED = load_testimonials()


def test_there_is_social_proof_at_all():
    assert LOADED, "в боте нет ни одного отзыва — оффер держится только на наших словах"


def test_bot_loaded_them():
    assert bot_module._TESTIMONIALS


def test_direction_wins_over_the_general_one():
    items = (
        Review(topic=ANY, text="общий"),
        Review(topic="son", text="про сон"),
    )
    assert pick(items, "son").text == "про сон"


def test_general_one_is_the_fallback():
    items = (Review(topic=ANY, text="общий"),)
    assert pick(items, "zaryadka").text == "общий"


def test_nothing_rather_than_something_irrelevant():
    """Нет ни своего, ни общего — идём без отзыва, а не берём чужой."""
    items = (Review(topic="son", text="про сон"),)
    assert pick(items, "beg") is None


def test_empty_file_is_a_working_state():
    assert pick((), "son") is None


def test_testimonials_are_short_enough_to_read():
    for item in LOADED:
        assert len(item.text) <= 700, f"отзыв «{item.topic}» длиннее, чем читают"


def test_every_testimonial_names_a_person():
    """Безымянный отзыв — это не отзыв, а реклама."""
    for item in LOADED:
        assert "<b>" in item.text, f"отзыв «{item.topic}» без подписи автора"
