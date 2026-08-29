"""Картинка приветствия ищется файлом, а не идентификатором Telegram.

file_id действителен только для того бота, который его получил. Один переезд
между ботами это уже доказал: картинка исчезла у всех, а в логе осталась одна
строчка «Wrong file identifier».
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import photos  # noqa: E402


def test_existing_image_is_found():
    assert photos.photo_path("mountain.jpg") is not None


def test_missing_image_is_not_invented():
    assert photos.photo_path("нет-такой.jpg") is None


def test_file_id_is_not_mistaken_for_a_file():
    """Старое значение из welcome.txt не должно притвориться путём."""
    assert photos.photo_path("AgACAgIAAxkDAAIBlGpEjyrhn3nTmkDj9hU9fh0Jek") is None


def test_paths_do_not_escape_the_image_folder():
    for value in ("../../config.py", "..\config.py", "site/public/img/mountain.jpg"):
        assert photos.photo_path(value) is None, value


def test_empty_value():
    assert photos.photo_path("") is None
    assert photos.photo_path("   ") is None


def test_cache_returns_what_was_remembered():
    cache = photos.PhotoCache()
    assert cache.get("mountain.jpg") is None
    cache.remember("mountain.jpg", "FILE_ID_1")
    assert cache.get("mountain.jpg") == "FILE_ID_1"


def test_cache_ignores_empty_values():
    cache = photos.PhotoCache()
    cache.remember("mountain.jpg", "")
    cache.remember("", "FILE_ID")
    assert len(cache) == 0


def test_every_photo_in_welcome_resolves():
    """Каждое имя из welcome.txt должно находиться файлом.

    Опечатка в имени не падает, а тихо уходит в Telegram как file_id и
    возвращается «Wrong file identifier» — в лог, который никто не читает.
    Здесь она падает сразу.
    """
    welcome = Path(__file__).resolve().parents[1] / "prompts" / "welcome.txt"
    names = [
        line.split(":", 1)[1].strip()
        for line in welcome.read_text(encoding="utf-8").splitlines()
        if line.startswith("photo:")
    ]
    assert names, "в приветствиях не осталось ни одной картинки"
    for name in names:
        assert photos.photo_path(name) is not None, f"нет файла {name}"
