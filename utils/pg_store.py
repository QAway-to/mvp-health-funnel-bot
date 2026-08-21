"""Хранилище воронки в PostgreSQL.

Подключается вместо Google Sheets, когда задан `DATABASE_URL`. Вся механика
кеша и фоновой выгрузки — в `CachedStore`; здесь только четыре метода доступа
к базе и схема.

Зачем база вместо таблицы: события перестают жить в буфере на 500 записей и
начинают накапливаться целиком, состояние переживает недоступность Google, а
на воронку можно смотреть запросом, а не глазами.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utils.funnel_store import CachedStore, UserState
from utils.logger import log_agent_action

# Соединений держим немного: на free-плане и у базы, и у контейнера лимиты
# невелики, а нагрузка здесь — десятки запросов в минуту, не тысячи.
_POOL_MIN = 1
_POOL_MAX = 4
_CONNECT_TIMEOUT = 10.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS funnel_users (
    chat_id        TEXT PRIMARY KEY,
    bucket         TEXT    NOT NULL DEFAULT '',
    is_premium     BOOLEAN NOT NULL DEFAULT FALSE,
    messages       INTEGER NOT NULL DEFAULT 0,
    cta_shown      INTEGER NOT NULL DEFAULT 0,
    source         TEXT    NOT NULL DEFAULT '',
    seen_content   TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL DEFAULT '',
    last_seen_at   TEXT    NOT NULL DEFAULT '',
    followups_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS funnel_events (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    chat_id TEXT NOT NULL,
    event   TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS funnel_events_chat_idx ON funnel_events (chat_id);
CREATE INDEX IF NOT EXISTS funnel_events_event_ts_idx ON funnel_events (event, ts);
"""

_UPSERT = """
INSERT INTO funnel_users (
    chat_id, bucket, is_premium, messages, cta_shown,
    source, seen_content, created_at, last_seen_at, followups_sent
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (chat_id) DO UPDATE SET
    bucket         = EXCLUDED.bucket,
    is_premium     = EXCLUDED.is_premium,
    messages       = EXCLUDED.messages,
    cta_shown      = EXCLUDED.cta_shown,
    source         = EXCLUDED.source,
    seen_content   = EXCLUDED.seen_content,
    created_at     = EXCLUDED.created_at,
    last_seen_at   = EXCLUDED.last_seen_at,
    followups_sent = EXCLUDED.followups_sent
"""

_INSERT_EVENT = """
INSERT INTO funnel_events (ts, chat_id, event, payload)
VALUES ($1, $2, $3, $4::jsonb)
"""


def event_ts(value: Any) -> datetime:
    """Метка события — в datetime, а не в строку.

    Тип параметра asyncpg берёт из колонки: для `timestamptz` он ждёт объект
    datetime и отвергает строку. Строка прошла бы тесты на разбор и молча
    роняла бы каждую выгрузку в проде.
    """
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_dsn(raw: str) -> tuple[str, bool]:
    """Привести адрес к тому, что понимает asyncpg.

    Возвращает (адрес, нужен_ли_TLS). Render отдаёт внутренний адрес без
    параметров, а внешний — с `?sslmode=require`; asyncpg этот параметр в
    строке не принимает и падает на подключении, поэтому вынимаем его сюда.
    """
    parts = urlsplit(raw.strip())
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "sslmode"]
    sslmode = dict(parse_qsl(parts.query)).get("sslmode", "")
    # Внутренний адрес Render (`...-internal`, без домена) идёт по приватной
    # сети — TLS там не нужен и часто попросту не настроен.
    needs_tls = sslmode not in ("", "disable", "allow")
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return cleaned, needs_tls


class PostgresStore(CachedStore):
    """То же поведение, что у SheetsStore, но поверх настоящей базы."""

    backend_name = "Postgres"

    def __init__(self, dsn: str | None = None) -> None:
        super().__init__()
        self._raw_dsn = dsn if dsn is not None else os.getenv("DATABASE_URL", "")
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        """Пул создаётся лениво: сеть не должна висеть на пути импорта."""
        if self._pool is not None:
            return self._pool
        if not self._raw_dsn:
            return None

        try:
            import asyncpg
        except ImportError:
            log_agent_action(
                "Funnel",
                "DATABASE_URL задан, но asyncpg не установлен — добавьте его в requirements.txt",
                level="ERROR",
            )
            return None

        dsn, needs_tls = normalize_dsn(self._raw_dsn)
        try:
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=_POOL_MIN,
                max_size=_POOL_MAX,
                timeout=_CONNECT_TIMEOUT,
                command_timeout=_CONNECT_TIMEOUT,
                ssl="require" if needs_tls else None,
            )
        except Exception as e:
            # Адрес, логин и пароль лежат в одной строке — в лог она не идёт.
            log_agent_action("Funnel", f"Не подключиться к Postgres: {type(e).__name__}", level="ERROR")
            return None

        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)
        return self._pool

    async def _load(self) -> list[UserState] | None:
        pool = await self._ensure_pool()
        if pool is None:
            return None

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM funnel_users")
        except Exception as e:
            log_agent_action("Funnel", f"Не прочитать пользователей: {type(e).__name__}", level="ERROR")
            return None

        loaded = (UserState.from_row(dict(row)) for row in rows)
        users = [state for state in loaded if state]
        if users:
            return users

        # База пустая — возможно, это первый запуск после переезда с таблицы.
        # Без переноса бот забыл бы всех, включая оплативших: доступ выдаётся
        # по полю is_premium, и в чистой базе его нет ни у кого.
        return await self._import_from_sheets()

    async def _import_from_sheets(self) -> list[UserState]:
        """Разовый перенос строк из Google Sheets в пустую базу.

        Срабатывает только когда в базе ноль строк, поэтому повторный запуск
        ничего не затрёт: со второго старта строки уже свои.
        """
        from utils import sheets_api

        if not sheets_api.is_configured():
            return []

        rows = await sheets_api.call("users_all")
        if not isinstance(rows, list) or not rows:
            return []

        loaded = (UserState.from_row(row) for row in rows if isinstance(row, dict))
        users = [state for state in loaded if state]
        if not users:
            return []

        if not await self._write(users, []):
            log_agent_action(
                "Funnel",
                "Перенос из таблицы не записался — работаем из памяти, повторим при следующем старте",
                level="ERROR",
            )
            return users

        premium = sum(1 for state in users if state.is_premium)
        log_agent_action(
            "Funnel",
            f"Перенесено из таблицы в Postgres: {len(users)} пользователей, из них с доступом {premium}",
        )
        return users

    @staticmethod
    def _user_params(state: UserState) -> tuple[Any, ...]:
        return (
            state.chat_id,
            state.bucket,
            state.is_premium,
            state.messages,
            state.cta_shown,
            state.source,
            ",".join(str(i) for i in state.seen_content),
            state.created_at,
            state.last_seen_at,
            state.followups_sent,
        )

    async def _write(self, users: list[UserState], events: list[dict[str, Any]]) -> bool:
        pool = await self._ensure_pool()
        if pool is None:
            return False

        try:
            async with pool.acquire() as conn:
                # Одна транзакция на пачку: половина выгруженного батча хуже,
                # чем не выгруженный вовсе — он вернётся в очередь целиком.
                async with conn.transaction():
                    if users:
                        await conn.executemany(_UPSERT, [self._user_params(u) for u in users])
                    if events:
                        await conn.executemany(
                            _INSERT_EVENT,
                            [
                                (
                                    event_ts(event.get("ts", "")),
                                    str(event.get("chat_id", "")),
                                    str(event.get("event", "")),
                                    json.dumps(event.get("payload") or {}, ensure_ascii=False),
                                )
                                for event in events
                            ],
                        )
        except Exception as e:
            log_agent_action("Funnel", f"Не записать пачку в Postgres: {type(e).__name__}", level="ERROR")
            return False
        return True

    async def _write_user(self, state: UserState) -> bool:
        pool = await self._ensure_pool()
        if pool is None:
            return False
        try:
            async with pool.acquire() as conn:
                await conn.execute(_UPSERT, *self._user_params(state))
        except Exception as e:
            log_agent_action("Funnel", f"Не записать оплату в Postgres: {type(e).__name__}", level="ERROR")
            return False
        return True

    async def _close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
