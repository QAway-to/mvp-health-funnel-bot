"""Приветствие подбирается по направлению, с которого человек пришёл.

Ошибка здесь тихая и дорогая: человек со страницы про сон получает первым
сообщением речь о беге босиком, закрывает чат и не возвращается. Ни исключения,
ни строчки в логах при этом не будет — поэтому проверки тут.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.welcome import (  # noqa: E402
    DEFAULT_KEY,
    TOPIC_LABEL_LIMIT,
    Welcome,
    load_welcome,
    welcome_for,
)

# Метки, которые шлёт сайт (src/lib/leadLink.ts). У каждой должен быть свой
# текст: `default` для них — это молчаливая потеря, а не запасной вариант.
SITE_SEGMENTS = (
    "beg",
    "komfort",
    "sila",
    "son",
    "zakalivanie",
    "vrednye-privychki",
    "zaryadka",
    "massazh",
)

#: Прежний слаг -> действующий раздел. Ссылки с ним уже разошлись по рекламе и
#: по чужим постам, поэтому вести их в общее приветствие нельзя.
ALIASES = {"samomassazh": "massazh"}

TELEGRAM_MESSAGE_LIMIT = 4096

WELCOME = load_welcome()


def test_default_exists():
    assert DEFAULT_KEY in WELCOME, "без default приходящим по прямой ссылке нечего показать"


def test_every_site_segment_has_its_own_text():
    missing = [segment for segment in SITE_SEGMENTS if segment not in WELCOME]
    assert not missing, f"нет приветствия для направлений: {missing}"


def test_texts_differ_from_each_other():
    """Скопированный текст — та же потеря, только незаметная."""
    texts = {segment: WELCOME[segment].text for segment in SITE_SEGMENTS}
    assert len(set(texts.values())) == len(texts), "два направления приветствуют одинаково"


def test_unknown_source_falls_back_to_default():
    for source in ("", "home", "demo", "gift", "checklist", "мусор"):
        greeting = welcome_for(WELCOME, source)
        assert greeting is not None
        assert greeting.key == DEFAULT_KEY, f"{source!r} не ушёл в default"


def test_photo_is_inherited_from_default():
    """Своё фото под каждое направление снимать необязательно."""
    default_photo = WELCOME[DEFAULT_KEY].photo
    assert default_photo, "у default нет картинки — наследовать нечего"
    for segment in SITE_SEGMENTS:
        assert welcome_for(WELCOME, segment).photo, f"{segment} остался без картинки"


def test_own_photo_wins_over_default():
    sections = {
        DEFAULT_KEY: Welcome(key=DEFAULT_KEY, text="общее", photo="общая"),
        "son": Welcome(key="son", text="про сон", photo="своя"),
    }
    assert welcome_for(sections, "son").photo == "своя"


def test_texts_fit_one_telegram_message():
    for key, greeting in WELCOME.items():
        assert len(greeting.text) <= TELEGRAM_MESSAGE_LIMIT, f"{key} длиннее одного сообщения"


def test_no_markdown_leaked_in():
    """Telegram здесь разбирает HTML: звёздочки приедут читателю как звёздочки."""
    for key, greeting in WELCOME.items():
        assert "**" not in greeting.text, f"в {key} остался markdown"


def test_bot_loaded_the_sections():
    assert bot_module._WELCOME, "бот не прочитал welcome.txt"
    assert DEFAULT_KEY in bot_module._WELCOME


def test_empty_sections_give_nothing_to_send():
    """Пустой файл — не повод падать: бот отправит запасной текст."""
    assert welcome_for({}, "son") is None
    assert bot_module._WELCOME_FALLBACK.strip()


def test_every_greeting_offers_topic_buttons():
    """Список тем строками просили перепечатать. Кнопку достаточно нажать."""
    for key, greeting in WELCOME.items():
        assert greeting.topics, f"в {key} нет кнопок с темами"
        assert 3 <= len(greeting.topics) <= 6, f"в {key} кнопок {len(greeting.topics)}"


def test_topic_labels_fit_a_button():
    for key, greeting in WELCOME.items():
        for label in greeting.topics:
            assert len(label) <= TOPIC_LABEL_LIMIT, f"в {key} подпись длиннее кнопки: {label}"


def test_topic_callbacks_fit_telegram_limit():
    """У callback_data 64 байта, и кириллица в UTF-8 съедает их вдвое быстрее."""
    for key, greeting in WELCOME.items():
        for index in range(len(greeting.topics)):
            data = f"{bot_module._TOPIC_CALLBACK}{key}:{index}"
            assert len(data.encode("utf-8")) <= 64, f"callback_data не влезает: {data}"


def test_keyboard_puts_the_gift_last():
    greeting = welcome_for(WELCOME, "son")
    keyboard = bot_module.TelegramBot._welcome_keyboard(greeting)
    rows = keyboard.inline_keyboard
    assert len(rows) == len(greeting.topics) + 1, "кнопок не столько, сколько тем"
    assert all(len(row) == 1 for row in rows), "по одной кнопке в ряд, иначе Telegram режет подписи"
    assert rows[-1][0].callback_data == bot_module._GIFT_CALLBACK


def test_keyboard_survives_a_missing_greeting():
    keyboard = bot_module.TelegramBot._welcome_keyboard(None)
    assert keyboard is None or len(keyboard.inline_keyboard) == 1


def test_topics_are_not_left_in_the_text():
    """Строка «@topic ...» — разметка кнопки, а не текст сообщения."""
    for key, greeting in WELCOME.items():
        assert "@topic" not in greeting.text, f"в {key} разметка кнопки попала в текст"


def test_callback_round_trips_to_the_topic():
    """Кнопка и её разбор — это одна пара. Разъедутся — клик ничего не сделает."""
    greeting = welcome_for(WELCOME, "zakalivanie")
    keyboard = bot_module.TelegramBot._welcome_keyboard(greeting)
    for row, expected in zip(keyboard.inline_keyboard, greeting.topics):
        parsed = bot_module.topic_from_callback(row[0].callback_data)
        assert parsed == ("zakalivanie", expected)


def test_stale_or_broken_callback_is_ignored():
    """Кнопка из приветствия, которое переписали, не должна ронять обработчик."""
    for data in ("gift", "t:", "t:нет-такого:0", "t:son:99", "t:son:x", "мусор"):
        assert bot_module.topic_from_callback(data) is None


def test_old_slug_still_lands_on_the_merged_greeting():
    """Массаж и самомассаж слиты. Старая ссылка не должна вести в никуда."""
    for old, current in ALIASES.items():
        greeting = welcome_for(WELCOME, old)
        assert greeting is not None
        assert greeting.key == current, f"{old} ушёл не туда: {greeting.key}"
        assert greeting.key != DEFAULT_KEY, f"{old} свалился в общее приветствие"


def test_alias_callbacks_carry_the_current_slug():
    """Кнопки под старой ссылкой должны быть с действующим слагом, а не с её."""
    greeting = welcome_for(WELCOME, "samomassazh")
    keyboard = bot_module.TelegramBot._welcome_keyboard(greeting)
    for row in keyboard.inline_keyboard[:-1]:
        assert row[0].callback_data.startswith(f"{bot_module._TOPIC_CALLBACK}massazh:")
