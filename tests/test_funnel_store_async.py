"""Async tests for the paths that guard paid access.

Sheets is faked out entirely — these cover what happens when it is slow, down,
or the process is shutting down mid-flush.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import funnel_store  # noqa: E402
from utils.funnel_store import SheetsStore, UserState  # noqa: E402


@pytest.fixture
def fake_sheets(monkeypatch):
    """Records calls; `.fail` makes every call behave as an outage."""

    class Fake:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []
            self.fail = False
            self.hang = False

        async def call(self, action, payload=None):
            self.calls.append((action, payload or {}))
            if self.hang:
                await asyncio.sleep(30)
            return None if self.fail else {"ok": True}

    fake = Fake()
    monkeypatch.setattr(funnel_store.sheets_api, "call", fake.call)
    monkeypatch.setattr(funnel_store.sheets_api, "is_configured", lambda: True)
    monkeypatch.setattr(funnel_store.sheets_api, "close", _noop)
    return fake


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "premium.jsonl"
    monkeypatch.setattr(funnel_store, "_JOURNAL_PATH", path)
    return path


@pytest.mark.asyncio
async def test_failed_flush_keeps_data_for_retry(fake_sheets, journal):
    store = SheetsStore()
    await store.save(UserState(chat_id="77", bucket="A", is_premium=True))

    fake_sheets.fail = True
    await store._flush_once()

    # ничего не потеряли — тот же пользователь ждёт следующей попытки
    assert "77" in store._dirty


@pytest.mark.asyncio
async def test_cancelled_flush_restores_batch(fake_sheets, journal):
    """Отмена посреди отправки не должна съедать батч (CRITICAL из ревью)."""
    store = SheetsStore()
    store.user("55")
    await store.event("55", "start")

    fake_sheets.hang = True
    task = asyncio.create_task(store._flush_once())
    await asyncio.sleep(0.05)  # дать дойти до сетевого вызова
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "55" in store._dirty
    assert len(store._events) == 1


@pytest.mark.asyncio
async def test_successful_flush_clears_state(fake_sheets, journal):
    store = SheetsStore()
    store.user("11")
    await store.event("11", "start")

    await store._flush_once()

    assert store._dirty == set()
    assert len(store._events) == 0
    assert fake_sheets.calls[-1][0] == "flush"


@pytest.mark.asyncio
async def test_premium_survives_sheets_outage_via_journal(fake_sheets, journal):
    """Оплата прошла, Sheets лежит, процесс умер — доступ должен вернуться."""
    fake_sheets.fail = True
    funnel_store.journal_premium("99", "stars", {"charge_id": "abc"})
    dying = SheetsStore()
    await dying.save(UserState(chat_id="99", bucket="A", is_premium=True), immediate=True)

    # новый процесс, кеш пустой, Sheets так и не ответил
    revived = SheetsStore()
    await revived.start()
    try:
        assert revived.user("99").is_premium is True
        assert "99" in revived._dirty  # и будет досинхронизировано
    finally:
        await revived.stop()


@pytest.mark.asyncio
async def test_journal_is_written_before_network(fake_sheets, journal):
    funnel_store.journal_premium("42", "testpay", {})
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["chat_id"] == "42" and lines[0]["reason"] == "testpay"


@pytest.mark.asyncio
async def test_immediate_save_reports_failure_so_caller_can_escalate(fake_sheets, journal):
    """Провал немедленной записи должен быть виден вызывающему — на этом
    держится алерт админу о потерянной оплате."""
    store = SheetsStore()
    state = UserState(chat_id="500", bucket="A", is_premium=True)

    assert await store.save(state, immediate=True) is True

    fake_sheets.fail = True
    assert await store.save(state, immediate=True) is False
    assert "500" in store._dirty


@pytest.mark.asyncio
async def test_event_restore_respects_buffer_cap(fake_sheets, journal):
    store = SheetsStore()
    store._restore(set(), [{"event": f"e{i}"} for i in range(funnel_store._EVENT_BUFFER_MAX + 50)])
    assert len(store._events) == funnel_store._EVENT_BUFFER_MAX
