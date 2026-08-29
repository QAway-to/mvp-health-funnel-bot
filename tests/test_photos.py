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
