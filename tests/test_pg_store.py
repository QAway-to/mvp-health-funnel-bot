"""Хранилище в Postgres.

Живой базы в тестах нет — она и не нужна: проверяем то, что ломается молча.
Разбор адреса (Render отдаёт два разных формата), раскладку состояния по
колонкам и главное — что недоступная база не роняет бота, а честно отвечает
«не записал», чтобы батч вернулся в очередь.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.funnel_store import UserState  # noqa: E402
from utils.pg_store import PostgresStore, normalize_dsn  # noqa: E402


# --- адрес базы ------------------------------------------------------------


def test_internal_render_url_stays_as_is_and_needs_no_tls():
    dsn, tls = normalize_dsn("postgresql://user:pass@dpg-abc-a/health_funnel")
    assert dsn == "postgresql://user:pass@dpg-abc-a/health_funnel"
    assert tls is False


def test_sslmode_moves_out_of_the_dsn():
    """asyncpg не принимает sslmode в строке и падает на подключении."""
    dsn, tls = normalize_dsn(
        "postgresql://user:pass@dpg-abc-a.oregon-postgres.render.com/db?sslmode=require"
    )
    assert "sslmode" not in dsn
    assert tls is True


def test_disable_sslmode_is_honoured():
    dsn, tls = normalize_dsn("postgres://u:p@host/db?sslmode=disable")
    assert tls is False
    assert "sslmode" not in dsn


def test_other_query_params_survive():
    dsn, _ = normalize_dsn("postgres://u:p@host/db?sslmode=require&application_name=bot")
    assert "application_name=bot" in dsn


def test_surrounding_whitespace_is_trimmed():
    """Адрес копируют из дашборда — перевод строки приезжает вместе с ним."""
    dsn, _ = normalize_dsn("  postgres://u:p@host/db\n")
    assert dsn == "postgres://u:p@host/db"


# --- раскладка состояния по колонкам --------------------------------------


def test_user_params_match_the_insert_order():
    state = UserState(
        chat_id="42",
        bucket="B",
        is_premium=True,
        messages=7,
        cta_shown=2,
        source="komfort",
        seen_content=(10, 11),
        created_at="2026-08-21T10:00:00+00:00",
        last_seen_at="2026-08-21T12:00:00+00:00",
        followups_sent=1,
    )

    assert PostgresStore._user_params(state) == (
        "42",
        "B",
        True,
        7,
        2,
        "komfort",
        "10,11",          # список ролики хранится строкой, как и в таблице
        "2026-08-21T10:00:00+00:00",
        "2026-08-21T12:00:00+00:00",
        1,
    )


# --- недоступная база ------------------------------------------------------


@pytest.fixture
def store_without_db(monkeypatch):
    """Пул не поднимется: проверяем, что это не авария, а отказ."""
    store = PostgresStore(dsn="")

    async def no_pool():
        return None

    monkeypatch.setattr(store, "_ensure_pool", no_pool)
    return store


@pytest.mark.asyncio
async def test_load_reports_outage_instead_of_empty_base(store_without_db):
    """None, а не []: пустой список означал бы «база есть и она пуста»,
    и бот начал бы заново создавать строки поверх существующих."""
    assert await store_without_db._load() is None


@pytest.mark.asyncio
async def test_write_returns_false_so_the_batch_comes_back(store_without_db):
    assert await store_without_db._write([], []) is False


@pytest.mark.asyncio
async def test_payment_write_reports_failure(store_without_db):
    state = UserState(chat_id="1", bucket="A", is_premium=True)
    assert await store_without_db._write_user(state) is False


@pytest.mark.asyncio
async def test_close_without_pool_is_harmless(store_without_db):
    await store_without_db._close()


# --- метка времени события -------------------------------------------------


def test_event_ts_returns_datetime_not_text():
    """Тип параметра asyncpg берёт из колонки timestamptz: строку он отвергнет,
    и выгрузка падала бы на каждой пачке."""
    from datetime import datetime, timezone

    from utils.pg_store import event_ts

    parsed = event_ts("2026-08-21T10:00:00+00:00")
    assert isinstance(parsed, datetime)
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)


def test_naive_event_ts_is_read_as_utc():
    from datetime import timedelta

    from utils.pg_store import event_ts

    assert event_ts("2026-08-21T10:00:00").utcoffset() == timedelta(0)


def test_broken_event_ts_falls_back_to_now():
    """Событие с битой меткой не должно ронять всю пачку."""
    from datetime import datetime

    from utils.pg_store import event_ts

    assert isinstance(event_ts("не дата"), datetime)
    assert isinstance(event_ts(None), datetime)
