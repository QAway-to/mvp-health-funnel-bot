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


# --- расшифровка ------------------------------------------------------------
#
# Локальная модель здесь не поднимается ни разу: она весит сотни мегабайт и
# считает секундами. Проверяется развилка — кто из двух путей отвечает и когда
# управление уходит второму, — а не сам разбор звука.


@pytest.fixture
def two_paths(monkeypatch):
    """Подменить оба пути расшифровки и записывать, кого позвали."""
    from notes import transcribe as module

    called: list[str] = []

    async def remote(audio, suffix):
        called.append("remote")
        return remote.answer

    async def local(audio, suffix):
        called.append("local")
        return "локально"

    remote.answer = "из облака"
    monkeypatch.setattr(module, "_remote", remote)
    monkeypatch.setattr(module, "_local", local)
    monkeypatch.setattr(module.config, "GROQ_API_KEY", "gsk_ключ")
    return module, called, remote


@pytest.mark.asyncio
async def test_the_cloud_is_tried_first(two_paths):
    module, called, _ = two_paths

    assert await module.transcribe(b"OggS...") == "из облака"
    assert called == ["remote"]


@pytest.mark.asyncio
async def test_silence_from_the_cloud_is_not_retried_locally(two_paths):
    """Пустой ответ — это тишина, а не отказ.

    Разница дорогая: переспроси мы тишину у слабой локальной модели, она
    ответила бы не пустотой, а выдуманной фразой.
    """
    module, called, remote = two_paths
    remote.answer = ""

    assert await module.transcribe(b"OggS...") == ""
    assert called == ["remote"]


@pytest.mark.asyncio
async def test_a_dead_cloud_falls_back_to_the_local_model(two_paths):
    module, called, remote = two_paths
    remote.answer = None

    assert await module.transcribe(b"OggS...") == "локально"
    assert called == ["remote", "local"]


@pytest.mark.asyncio
async def test_without_a_key_nothing_leaves_the_process(two_paths):
    module, called, _ = two_paths
    module.config.GROQ_API_KEY = ""

    assert await module.transcribe(b"OggS...") == "локально"
    assert called == ["local"]


@pytest.mark.asyncio
async def test_an_oversized_file_does_not_go_to_the_cloud(monkeypatch):
    """Слишком большое отправляется на локальную модель, а не в ошибку."""
    from notes import transcribe as module

    monkeypatch.setattr(module.config, "GROQ_MAX_BYTES", 10)
    assert await module._remote(b"x" * 100, ".oga") is None


def test_the_local_decoder_gets_no_primer():
    """Затравка на маленькой модели вставляет свои же слова в расшифровку.

    Проверяется текстом, а не поведением: соблазн вернуть `initial_prompt`
    выглядит разумно ровно до того момента, когда в заметке появляется слово,
    которого никто не говорил.
    """
    source = (NOTES / "transcribe.py").read_text(encoding="utf-8")
    call = source.split("model.transcribe(", 1)[1].split("\n    )", 1)[0]
    assert "initial_prompt" not in call


# --- разговор с облаком -----------------------------------------------------


class FakeResponse:
    """Ответ Groq. Ровно те три метода, которыми пользуется `_remote`."""

    def __init__(self, status: int, payload=None):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return "тело ответа"


class FakeSession:
    def __init__(self, response: FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def post(self, *_args, **kwargs):
        # Заодно единственное место, где видно отправляемое: ключ уходит
        # заголовком и ничем иным.
        FakeSession.last_headers = kwargs.get("headers", {})
        return self._response


@pytest.fixture
def cloud(monkeypatch):
    """Подставить ответ облака вместо сети."""
    from notes import transcribe as module

    monkeypatch.setattr(module.config, "GROQ_API_KEY", "gsk_ключ")

    def answer(status: int, payload=None):
        response = FakeResponse(status, payload)
        monkeypatch.setattr(module.aiohttp, "ClientSession", lambda **_kw: FakeSession(response))
        return module

    return answer


@pytest.mark.asyncio
async def test_the_cloud_answer_is_the_note(cloud):
    module = cloud(200, {"text": "  Мысль про монетизацию.  "})

    assert await module._remote(b"OggS...", ".oga") == "Мысль про монетизацию."


@pytest.mark.asyncio
async def test_a_wrong_key_falls_back_instead_of_failing(cloud):
    """401 — самый вероятный отказ здесь: ключ xAI вместо ключа Groq."""
    module = cloud(401)

    assert await module._remote(b"OggS...", ".oga") is None


@pytest.mark.asyncio
async def test_a_two_hundred_of_the_wrong_shape_does_not_raise(cloud):
    """Двести с чужим телом приходит от прокси, а не от Groq.

    Разбирать там нечего, но и падать нельзя: заметка ушла бы в ошибку вместо
    локальной расшифровки — ровно то, ради чего запасной путь и держится.
    """
    module = cloud(200, ["не", "объект"])

    assert await module._remote(b"OggS...", ".oga") is None


@pytest.mark.asyncio
async def test_the_key_travels_in_the_header_and_nowhere_else(cloud):
    module = cloud(200, {"text": "ок"})
    await module._remote(b"OggS...", ".oga")

    assert FakeSession.last_headers["Authorization"] == "Bearer gsk_ключ"
