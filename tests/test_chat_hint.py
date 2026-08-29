"""Подпись «Пиши мне прямо сюда» и кнопки под ответом.

Кнопки удобны, но создают ощущение анкеты: человек кликает и не догадывается,
что можно спросить своими словами. А именно свой вопрос переводит разговор из
меню в диалог — и дальше в продажу.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.welcome import welcome_for  # noqa: E402

HINT = "Пиши мне прямо сюда — в чат, этот диалог живой"


def test_hint_is_appended():
    assert bot_module.with_hint("Ответ").endswith(f"<b>{HINT}</b>")


def test_hint_is_not_doubled():
    """Текст может прийти уже с подписью — две строки подряд читаются как сбой."""
    once = bot_module.with_hint("Ответ")
    assert bot_module.with_hint(once) == once


def test_empty_text_stays_empty():
    assert bot_module.with_hint("") == ""


def test_hint_is_bold():
    assert "<b>" in bot_module._CHAT_HINT and "</b>" in bot_module._CHAT_HINT


def test_hint_speaks_informally():
    """Бот на «ты» — подпись под каждым сообщением тем более."""
    assert "пишите" not in bot_module._CHAT_HINT.lower()


# --- кнопки под ответом -----------------------------------------------------


def test_answer_offers_a_few_topics_not_the_whole_menu():
    keyboard = bot_module.TelegramBot._topics_keyboard("zakalivanie")
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) <= bot_module._TOPICS_AFTER_ANSWER


def test_topics_come_from_the_persons_direction():
    keyboard = bot_module.TelegramBot._topics_keyboard("son")
    for row in keyboard.inline_keyboard:
        assert row[0].callback_data.startswith(f"{bot_module._TOPIC_CALLBACK}son:")


def test_the_topic_just_discussed_is_not_offered_again():
    """Предложить её следующей строкой — показать, что бот не слушал."""
    greeting = welcome_for(bot_module._WELCOME, "zakalivanie")
    just_asked = greeting.topics[0]
    keyboard = bot_module.TelegramBot._topics_keyboard("zakalivanie", exclude=just_asked)
    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert just_asked not in labels


def test_unknown_source_still_gets_the_general_menu():
    assert bot_module.TelegramBot._topics_keyboard("") is not None


def test_callbacks_stay_valid():
    """Кнопка обязана разбираться обратно в ту же тему."""
    keyboard = bot_module.TelegramBot._topics_keyboard("son")
    for row in keyboard.inline_keyboard:
        assert bot_module.topic_from_callback(row[0].callback_data) is not None
