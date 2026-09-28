"""Переиндексация должна не только добавлять, но и забывать.

Раньше она умела только добавлять. Пост, удалённый из канала, оставался в
индексе навсегда, и бот продолжал отдавать людям `copy_message` на
несуществующее сообщение — молча, потому что ошибка отправки гасится уровнем
выше. Это всплыло при перезаливке библиотеки: старые посты сносятся пачкой,
и без забывания индекс после этого состоял бы наполовину из призраков.

Обратная ошибка дороже: удалить запись из-за flood limit или сетевого сбоя
значит потерять живой ролик, а вернуть его можно только повторной
переиндексацией по тому же диапазону. Поэтому забываем ровно тогда, когда
Telegram прямо ответил «не найдено».
"""

import sys
from pathlib import Path

import pytest
from telegram.error import BadRequest, NetworkError, RetryAfter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils import content_library  # noqa: E402
from utils.content_library import TIER_FREE, ContentItem, ContentLibrary  # noqa: E402


class FakeBot:
    """Канал, в котором часть постов удалена, а часть отвечает сбоем."""

    def __init__(self, alive: dict[int, str], errors: dict[int, Exception]):
        self.alive, self.errors = alive, errors
        self.deleted: list[int] = []

    async def forward_message(self, chat_id, from_chat_id, message_id):
        if message_id in self.errors:
            raise self.errors[message_id]
        if message_id not in self.alive:
            raise BadRequest("Message to forward not found")

        class Msg:
            def __init__(self, caption):
                self.message_id = 9000 + message_id
                self.caption = caption
                self.video = object()
                self.video_note = None
                self.animation = None

        return Msg(self.alive[message_id])

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


@pytest.fixture
def library(monkeypatch) -> ContentLibrary:
    lib = ContentLibrary()
    lib._items = {
        1: ContentItem(1, ("снег",), TIER_FREE, "Был и остался"),
        2: ContentItem(2, ("вода",), TIER_FREE, "Удалён из канала"),
        3: ContentItem(3, ("бокс",), TIER_FREE, "Сбой сети на этом посте"),
    }
    monkeypatch.setattr(bot_module, "library", lib)
    return lib


@pytest.fixture
def quiet(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.asyncio, "sleep", noop)
    monkeypatch.setattr(content_library.sheets_api, "call", noop)


def _run(telegram_bot, fake):
    import asyncio

    telegram_bot._app = type("App", (), {"bot": fake})()
    return asyncio.run(telegram_bot.reindex_range("42", 1, 4))


def test_a_deleted_post_leaves_the_index(library, quiet):
    """Ради чего всё: пост удалён — записи о нём быть не должно."""
    fake = FakeBot(alive={1: "#снег\nБыл и остался"}, errors={})
    _run(bot_module.TelegramBot(), fake)
    assert 2 not in library
    assert 1 in library


def test_a_network_error_never_drops_a_clip(library, quiet):
    """Сбой сети — не доказательство, что поста нет."""
    fake = FakeBot(alive={1: "#снег\nБыл"}, errors={3: NetworkError("boom")})
    _run(bot_module.TelegramBot(), fake)
    assert 3 in library, "ролик выпал из индекса из-за сетевого сбоя"


def test_flood_limit_never_drops_a_clip(library, quiet):
    """Та же история: Telegram просит подождать, а не сообщает об удалении."""
    fake = FakeBot(alive={1: "#снег\nБыл"}, errors={3: RetryAfter(30)})
    _run(bot_module.TelegramBot(), fake)
    assert 3 in library


def test_a_wrong_channel_id_does_not_wipe_the_library(library, quiet):
    """Самый дорогой случай из всех.

    Неверный CONTENT_CHANNEL_ID даёт «Chat not found» — тот же BadRequest и те
    же слова «not found», что у удалённого поста, но на КАЖДОМ посте
    диапазона. Проверка по одной подстроке стёрла бы здесь всю библиотеку
    разом, и вернуть её можно было бы только повторной переиндексацией по
    живому каналу.
    """
    fake = FakeBot(alive={}, errors={i: BadRequest("Chat not found") for i in range(1, 5)})
    _run(bot_module.TelegramBot(), fake)
    assert set(library._items) == {1, 2, 3}, "библиотека вычищена из-за неверного канала"


def test_a_storage_failure_does_not_swallow_the_scan(library, quiet, monkeypatch):
    """Сбой хранилища на удалении не должен уносить только что найденное.

    Без этого исключение из remove() пролетало мимо upsert_many, и весь
    урожай прохода терялся молча — вместе с записью, которую убирали.
    """
    async def boom(name, payload=None):
        if name == "content_delete":
            raise RuntimeError("Sheets прилегли")

    monkeypatch.setattr(content_library.sheets_api, "call", boom)
    fake = FakeBot(alive={1: "#снег\nБыл", 4: "#роса\nНовый"}, errors={})
    count = _run(bot_module.TelegramBot(), fake)
    assert count == 2, "найденные посты потерялись из-за сбоя на удалении"
    assert 2 in library, "запись исчезла из памяти, хотя в хранилище осталась"


def test_a_gap_in_numbering_costs_nothing(library, quiet, monkeypatch):
    """id 4 в индексе никогда не было — трогать хранилище незачем."""
    calls: list[tuple] = []

    async def spy(name, payload=None):
        calls.append((name, payload))

    monkeypatch.setattr(content_library.sheets_api, "call", spy)
    fake = FakeBot(alive={1: "#снег\nБыл"}, errors={})
    _run(bot_module.TelegramBot(), fake)
    deleted = [payload for name, payload in calls if name == "content_delete"]
    assert all(p["message_id"] != 4 for p in deleted), "дырка в нумерации пошла в хранилище"


def test_surviving_posts_are_still_indexed(library, quiet):
    """Забывание не должно мешать основной работе переиндексации."""
    fake = FakeBot(alive={1: "#снег\nБыл и остался", 4: "#роса\nНовый пост"}, errors={})
    count = _run(bot_module.TelegramBot(), fake)
    assert count == 2
    assert 4 in library


def test_membership_takes_a_post_number_and_says_so(library):
    """`item in library` вместо `item.message_id in library` должно падать,
    а не отвечать «нет такого»: молчаливое «нет» уводит от ошибки."""
    with pytest.raises(TypeError):
        library._items[1] in library
    with pytest.raises(TypeError):
        "1" in library
