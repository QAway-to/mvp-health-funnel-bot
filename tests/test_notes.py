"""Личный бот заметок: граница с проектом, разбор дат, разбор сообщений.

Главный тест здесь — первый. Модуль заметок лежит в чужом ему репозитории, и
единственное, что удерживает его от прорастания в проект, — договорённость.
Договорённости проверяются тестом, а не памятью.
"""

import ast
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NOTES = ROOT / "notes"


# --- граница ----------------------------------------------------------------


def imported_modules(source: str) -> set[str]:
    """Верхнеуровневые имена всего, что модуль импортирует."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


#: Каталоги и модули проекта, до которых заметкам дела нет.
PROJECT = {"bot", "config", "main", "utils", "tools", "prompts"}


def test_notes_do_not_import_the_project():
    """Иначе «отдельный модуль» станет частью воронки на первой же правке."""
    for path in NOTES.glob("*.py"):
        leaked = imported_modules(path.read_text(encoding="utf-8")) & PROJECT
        assert not leaked, f"{path.name} импортирует из проекта: {sorted(leaked)}"


def test_the_project_does_not_import_notes_except_in_main():
    """Обратное направление: заметки подключаются ровно в одном месте."""
    for path in list(ROOT.glob("*.py")) + list((ROOT / "utils").glob("*.py")):
        if path.name == "main.py":
            continue
        assert "notes" not in imported_modules(path.read_text(encoding="utf-8")), (
            f"{path.name} импортирует модуль заметок"
        )


def test_notes_are_mounted_before_the_site_catch_all():
    """Маршрут-ловушка сайта забрала бы вебхук себе."""
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    mounted = source.index("include_router")
    catch_all = source.index('@app.get("/{url_path:path}")')
    assert mounted < catch_all, "вебхук заметок подключён после раздачи сайта"


def test_the_module_is_off_until_configured():
    from notes import config

    assert config.is_configured() is False or config.BOT_TOKEN


# --- заголовок и адрес ------------------------------------------------------


def test_title_is_the_first_sentence():
    from notes.text import title_from

    assert title_from("Меняем модель. Дальше не важно.") == "Меняем модель"
    assert title_from("") == "Без названия"


def test_long_title_is_cut_not_wrapped():
    from notes.text import title_from

    title = title_from("а" * 200)
    assert len(title) <= 71 and title.endswith("…")


def test_slug_is_latin_and_safe_for_a_path():
    from notes.text import slugify

    slug = slugify("Монетизация приложения: подписка или разовая")
    assert re.fullmatch(r"[a-z0-9-]+", slug), slug
    assert "monetizatsiya" in slug


def test_empty_title_still_yields_a_filename():
    from notes.text import slugify

    assert slugify("!!!") == "zametka"


# --- даты -------------------------------------------------------------------


NOW = datetime(2026, 9, 4, 12, 0)


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("в календарь: 5 сентября 14:00 созвон", datetime(2026, 9, 5, 14, 0)),
        ("встреча 05.09 9:30", datetime(2026, 9, 5, 9, 30)),
        ("напомни 05.09.2027 18:00", datetime(2027, 9, 5, 18, 0)),
        ("завтра 8:00 пробежка", datetime(2026, 9, 5, 8, 0)),
        ("сегодня 18:30", datetime(2026, 9, 4, 18, 30)),
        ("послезавтра 10:00", datetime(2026, 9, 6, 10, 0)),
    ],
)
def test_dates_we_promise_to_understand(phrase, expected):
    from notes.text import parse_when

    assert parse_when(phrase, NOW) == expected


def test_a_past_month_means_the_next_year():
    """«5 января» в сентябре — это январь, который впереди, а не позади."""
    from notes.text import parse_when

    assert parse_when("5 января 10:00", NOW) == datetime(2027, 1, 5, 10, 0)


@pytest.mark.parametrize("phrase", ["напомни как-нибудь на неделе", "в календарь", ""])
def test_vague_dates_are_admitted_not_guessed(phrase):
    from notes.text import parse_when

    assert parse_when(phrase, NOW) is None


def test_impossible_dates_do_not_become_events():
    from notes.text import parse_when

    assert parse_when("30 февраля 10:00", NOW) is None
    assert parse_when("5 сентября 99:99", NOW) is None


def test_calendar_link_carries_title_and_span():
    from notes.text import calendar_link

    link = calendar_link("Созвон", datetime(2026, 9, 5, 14, 0))
    assert "dates=20260905T140000/20260905T150000" in link
    assert link.startswith("https://calendar.google.com/")


# --- разбор сообщения -------------------------------------------------------


def test_voice_is_found_in_a_plain_message():
    from notes.router import _audio_of

    kind, payload = _audio_of({"voice": {"file_id": "abc", "duration": 12}})
    assert kind == "voice" and payload["file_id"] == "abc"


def test_voice_is_found_in_a_forwarded_message():
    """Пересланное устроено так же — ради этого всё и затевалось."""
    from notes.router import _audio_of

    kind, _ = _audio_of(
        {
            "voice": {"file_id": "xyz", "duration": 30},
            "forward_origin": {"type": "user", "sender_user": {"first_name": "Богдан"}},
        }
    )
    assert kind == "voice"


def test_the_original_author_of_a_forward_is_recorded():
    from notes.router import _meta

    meta = _meta(
        {
            "forward_origin": {
                "type": "user",
                "sender_user": {"first_name": "Богдан", "username": "bogdan"},
                "date": 1757000000,
            }
        },
        "",
        0,
    )
    assert meta["Переслано от"] == "Богдан (@bogdan)"
    assert "Сказано" in meta


def test_a_hidden_forwarder_is_named_not_dropped():
    from notes.router import _meta

    meta = _meta({"forward_origin": {"type": "hidden_user", "sender_user_name": "Аноним"}}, "", 0)
    assert meta["Переслано от"] == "Аноним"


def test_calendar_is_only_on_request():
    from notes.router import _wants_calendar

    assert _wants_calendar("в календарь", "") is True
    assert _wants_calendar("", "напомни мне про это") is True
    assert _wants_calendar("", "просто мысль про монетизацию") is False


def test_strangers_are_not_served():
    from notes import config
    from notes.router import _from_owner

    config.OWNER_ID = "111"
    assert _from_owner({"from": {"id": 111}}) is True
    assert _from_owner({"from": {"id": 222}}) is False


def test_note_path_sorts_by_time():
    from notes.archive import note_path

    early = note_path(datetime(2026, 9, 4, 9, 5), "a")
    late = note_path(datetime(2026, 9, 4, 21, 5), "b")
    assert early < late
