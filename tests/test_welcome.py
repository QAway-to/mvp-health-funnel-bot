"""Приветствие подбирается по направлению, с которого человек пришёл.

Ошибка здесь тихая и дорогая: человек со страницы про сон получает первым
сообщением речь о беге босиком, закрывает чат и не возвращается. Ни исключения,
ни строчки в логах при этом не будет — поэтому проверки тут.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.welcome import DEFAULT_KEY, Welcome, load_welcome, welcome_for  # noqa: E402

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
    "samomassazh",
    "massazh",
)

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
