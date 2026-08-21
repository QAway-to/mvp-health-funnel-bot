"""Рассылка догоняющих сообщений: что происходит при отправке.

Расписание проверяется отдельно (test_followups.py) — здесь про побочные
эффекты: счётчик двигается ровно один раз, заблокировавший бота выпадает из
очереди навсегда, а сетевая ошибка не съедает шаг.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from telegram.error import Forbidden, TelegramError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.followups import FollowUp  # noqa: E402
from utils.funnel_store import UserState  # noqa: E402
from utils.offer import CtaButton  # noqa: E402

STEPS = (
    FollowUp(1, 1.0, "через час", (CtaButton("gift", "Чек-лист"),)),
    FollowUp(2, 24.0, "через сутки", ()),
)


class FakeBot:
    def __init__(self, error: Exception | None = None):
        self.sent: list[dict] = []
        self._error = error

    async def send_message(self, **kwargs):
        if self._error:
            raise self._error
        self.sent.append(kwargs)


class FakeApp:
    def __init__(self, bot: FakeBot):
        self.bot = bot


@pytest.fixture
def store(monkeypatch):
    """Подменяем хранилище на память: рассылка не должна ходить в Sheets."""
    users: dict[str, UserState] = {}
    events: list[tuple] = []

    def all_users():
        return list(users.values())

    async def save(state, *, immediate=False):
        users[state.chat_id] = state
        return True

    async def event(chat_id, name, **payload):
        events.append((chat_id, name, payload))

    monkeypatch.setattr(bot_module.store, "all_users", all_users)
    monkeypatch.setattr(bot_module.store, "save", save)
    monkeypatch.setattr(bot_module.store, "event", event)
    monkeypatch.setattr(bot_module, "_FOLLOWUPS", STEPS)
    monkeypatch.setattr(bot_module, "is_quiet_hour", lambda now: False)
    return users, events


def waiting_user(chat_id: str = "42") -> UserState:
    """Молчит два часа: первый шаг уже созрел, второй ещё нет."""
    silent_since = datetime.now(timezone.utc) - timedelta(hours=2)
    return UserState(
        chat_id=chat_id,
        bucket="A",
        messages=3,
        last_seen_at=silent_since.isoformat(timespec="seconds"),
        followups_sent=0,
    )


def make_bot(fake_bot: FakeBot) -> bot_module.TelegramBot:
    instance = bot_module.TelegramBot()
    instance._app = FakeApp(fake_bot)
    return instance


@pytest.mark.asyncio
async def test_due_message_goes_out_once_and_is_counted(store):
    users, events = store
    # За один запуск уходит ровно один шаг: цепочка не должна вываливаться
    # на человека тремя сообщениями подряд.
    users["42"] = waiting_user()
    fake = FakeBot()

    result = await make_bot(fake).run_followups()

    assert result["sent"] == 1
    assert len(fake.sent) == 1
    assert fake.sent[0]["chat_id"] == "42"
    assert users["42"].followups_sent == 1
    assert [(cid, name) for cid, name, _ in events] == [("42", "followup_sent")]


@pytest.mark.asyncio
async def test_blocked_user_drops_out_of_the_queue(store):
    users, events = store
    users["42"] = waiting_user()
    fake = FakeBot(error=Forbidden("bot was blocked by the user"))

    result = await make_bot(fake).run_followups()

    assert result["blocked"] == 1
    assert users["42"].followups_sent == len(STEPS)   # больше не пробуем
    assert events[0][1] == "followup_blocked"


@pytest.mark.asyncio
async def test_network_error_keeps_the_step_for_next_run(store):
    """Упавшая отправка не должна выглядеть как доставленная."""
    users, _ = store
    users["42"] = waiting_user()
    fake = FakeBot(error=TelegramError("timeout"))

    result = await make_bot(fake).run_followups()

    assert result["failed"] == 1
    assert users["42"].followups_sent == 0


@pytest.mark.asyncio
async def test_quiet_hours_hold_the_queue(store, monkeypatch):
    users, _ = store
    users["42"] = waiting_user()
    monkeypatch.setattr(bot_module, "is_quiet_hour", lambda now: True)
    fake = FakeBot()

    result = await make_bot(fake).run_followups()

    assert result == {"sent": 0, "reason": "quiet_hours"}
    assert fake.sent == []
    assert users["42"].followups_sent == 0


@pytest.mark.asyncio
async def test_batch_limit_is_respected(store):
    users, _ = store
    for i in range(5):
        users[str(i)] = waiting_user(str(i))
    fake = FakeBot()

    result = await make_bot(fake).run_followups(limit=2)

    assert result["sent"] == 2
    assert len(fake.sent) == 2
