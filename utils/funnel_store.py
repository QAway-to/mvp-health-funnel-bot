"""Persistent funnel state for the Telegram bot.

Google Sheets is the source of truth; the in-memory cache serves every read so
the chat loop never waits on an HTTP round-trip. Writes are coalesced and
flushed in the background — except payments, which go out immediately.

The cache is authoritative for the lifetime of the process: if Sheets is
unreachable the bot keeps working and the dirty set is retried on the next
flush. Restarting with Sheets down loses nothing that was already written.
"""

import asyncio
import hashlib
import json
import os
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from utils import sheets_api
from utils.logger import log_agent_action

_FLUSH_INTERVAL = 10.0      # seconds between background flushes
_EVENT_BUFFER_MAX = 500     # drop oldest events rather than grow unbounded

# Local append-only journal of premium grants. Sheets is the source of truth,
# but a container that dies before the write lands would otherwise strand a
# paying customer — the journal is replayed on every start.
_JOURNAL_PATH = Path(
    os.getenv("PREMIUM_JOURNAL_PATH", str(Path(__file__).resolve().parents[1] / "logs" / "premium.jsonl"))
)

BUCKET_A = "A"
BUCKET_B = "B"


def assign_bucket(chat_id: str) -> str:
    """Deterministic 50/50 split — stable across restarts and re-imports."""
    digest = hashlib.sha256(chat_id.encode("utf-8")).digest()
    return BUCKET_A if digest[0] % 2 == 0 else BUCKET_B


@dataclass(frozen=True)
class UserState:
    chat_id: str
    bucket: str
    is_premium: bool = False
    messages: int = 0
    cta_shown: int = 0
    source: str = ""
    seen_content: tuple[int, ...] = ()
    created_at: str = ""
    # Последняя активность человека и сколько догоняющих сообщений ему уже
    # ушло. Вместе они и составляют всю память цепочки: тишину считаем от
    # last_seen_at, очередь шагов — от followups_sent.
    last_seen_at: str = ""
    followups_sent: int = 0
    # Где человек в пошаговом курсе: слаг направления и номер последнего
    # выданного шага. Пусто — курс не начат. Держим прямо здесь, а не в
    # отдельной таблице: одна запись на человека, и читается она в том же
    # запросе, что и всё остальное.
    course: str = ""
    step: int = 0

    def to_row(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "bucket": self.bucket,
            "is_premium": "1" if self.is_premium else "",
            "messages": self.messages,
            "cta_shown": self.cta_shown,
            "source": self.source,
            "seen_content": ",".join(str(i) for i in self.seen_content),
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "followups_sent": self.followups_sent,
            "course": self.course,
            "step": self.step,
        }

    @staticmethod
    def from_row(row: dict[str, Any]) -> "UserState | None":
        chat_id = str(row.get("chat_id") or "").strip()
        if not chat_id:
            return None
        seen_raw = str(row.get("seen_content") or "")
        seen = tuple(
            int(part) for part in seen_raw.split(",") if part.strip().lstrip("-").isdigit()
        )
        return UserState(
            chat_id=chat_id,
            bucket=str(row.get("bucket") or "").strip() or assign_bucket(chat_id),
            is_premium=str(row.get("is_premium") or "").strip() not in ("", "0", "false", "FALSE"),
            messages=_as_int(row.get("messages")),
            cta_shown=_as_int(row.get("cta_shown")),
            source=str(row.get("source") or ""),
            seen_content=seen,
            created_at=str(row.get("created_at") or ""),
            last_seen_at=str(row.get("last_seen_at") or ""),
            followups_sent=_as_int(row.get("followups_sent")),
            course=str(row.get("course") or ""),
            step=_as_int(row.get("step")),
        )


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value).strip() or 0))
    except (TypeError, ValueError):
        return 0


def journal_premium(chat_id: str, reason: str, details: dict[str, Any] | None = None) -> None:
    """Record a premium grant on local disk before anything else can fail.

    Synchronous on purpose: a few hundred bytes, and the whole point is that it
    has already happened by the time the caller continues.
    """
    try:
        _JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": _now(),
            "chat_id": chat_id,
            "reason": reason,
            "details": details or {},
        }
        with _JOURNAL_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log_agent_action("Funnel", f"Could not journal premium for {chat_id}: {e}", level="ERROR")


def _read_journal() -> set[str]:
    if not _JOURNAL_PATH.exists():
        return set()
    granted: set[str] = set()
    try:
        with _JOURNAL_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    chat_id = str(json.loads(line).get("chat_id") or "").strip()
                except json.JSONDecodeError:
                    continue
                if chat_id:
                    granted.add(chat_id)
    except OSError as e:
        log_agent_action("Funnel", f"Could not read premium journal: {e}", level="ERROR")
    return granted


class Store(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def user(self, chat_id: str, *, source: str = "") -> UserState: ...
    def all_users(self) -> list[UserState]: ...
    async def save(self, state: UserState, *, immediate: bool = False) -> bool: ...
    async def event(self, chat_id: str, name: str, **payload: Any) -> None: ...


class CachedStore:
    """Кеш в памяти плюс фоновая выгрузка — общая механика всех хранилищ.

    Читает всегда кеш: разговор в чате не должен ждать сетевого round-trip.
    Записи копятся и уезжают пачкой раз в `_FLUSH_INTERVAL` — кроме оплат, они
    пишутся немедленно и умеют сообщить о неудаче.

    Бэкенд подключается четырьмя методами внизу класса. Всё, что выше, для
    Google Sheets и Postgres одинаково, и дублировать это в двух местах —
    верный способ починить гонку только в одном из них.
    """

    backend_name = "store"

    def __init__(self) -> None:
        self._users: dict[str, UserState] = {}
        self._dirty: set[str] = set()
        self._events: deque[dict[str, Any]] = deque(maxlen=_EVENT_BUFFER_MAX)
        self._flusher: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._loaded = False

    async def start(self) -> None:
        """Warm the cache from the backend, then run the background flusher."""
        rows = await self._load()
        if rows is None:
            log_agent_action(
                "Funnel",
                f"Could not load users from {self.backend_name} — starting cold, "
                "existing rows stay untouched",
                level="WARNING",
            )
        else:
            for state in rows:
                # Загрузка идёт фоном, пока бот уже отвечает: то, что успели
                # накопить в памяти, свежее прочитанного из хранилища.
                if state.chat_id not in self._users:
                    self._users[state.chat_id] = state
            self._loaded = True
            log_agent_action(
                "Funnel", f"Loaded {len(self._users)} users from {self.backend_name}"
            )

        self._replay_journal()
        self._flusher = asyncio.create_task(self._flush_loop())

    def _replay_journal(self) -> None:
        """Re-apply premium grants that may never have reached the backend."""
        recovered = 0
        for chat_id in _read_journal():
            state = self._users.get(chat_id) or UserState(
                chat_id=chat_id, bucket=assign_bucket(chat_id), created_at=_now()
            )
            if not state.is_premium:
                self._users[chat_id] = replace(state, is_premium=True)
                self._dirty.add(chat_id)
                recovered += 1
            else:
                self._users[chat_id] = state
        if recovered:
            log_agent_action(
                "Funnel", f"Recovered {recovered} premium grants from local journal"
            )

    async def stop(self) -> None:
        if self._flusher:
            self._flusher.cancel()
            try:
                await self._flusher
            except asyncio.CancelledError:
                pass
            self._flusher = None
        await self._flush_once()
        await self._close()

    def user(self, chat_id: str, *, source: str = "") -> UserState:
        """Return cached state, creating (and queueing) a new row on first sight."""
        state = self._users.get(chat_id)
        if state is None:
            state = UserState(
                chat_id=chat_id,
                bucket=assign_bucket(chat_id),
                source=source,
                created_at=_now(),
            )
            self._users[chat_id] = state
            self._dirty.add(chat_id)
        return state

    def all_users(self) -> list[UserState]:
        """Snapshot of every known user.

        A copy on purpose: callers iterate with awaits inside, and the cache is
        mutated by the chat loop meanwhile — iterating the live dict would
        raise mid-broadcast.
        """
        return list(self._users.values())

    async def save(self, state: UserState, *, immediate: bool = False) -> bool:
        """Persist state. Returns False when an immediate write did NOT land,
        so callers holding money-critical data can escalate."""
        self._users[state.chat_id] = state
        if immediate:
            if await self._write_user(state):
                return True
            self._dirty.add(state.chat_id)  # retry in the background
            return False
        self._dirty.add(state.chat_id)
        return True

    async def event(self, chat_id: str, name: str, **payload: Any) -> None:
        self._events.append(
            {"ts": _now(), "chat_id": chat_id, "event": name, "payload": payload}
        )

    async def _flush_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_FLUSH_INTERVAL)
                await self._flush_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # a flush must never kill the loop
                log_agent_action("Funnel", f"Flush loop error: {e}", level="ERROR")

    async def _flush_once(self) -> None:
        # _dirty/_users are also mutated by user()/save() without the lock; that
        # is safe only because those paths never await between read and write.
        # Anything added here that yields must take the lock.
        async with self._lock:
            users = [self._users[cid] for cid in self._dirty if cid in self._users]
            pending_ids = set(self._dirty)
            events = list(self._events)

            if not users and not events:
                return

            self._dirty.clear()
            self._events.clear()

        delivered = False
        try:
            delivered = await self._write(users, events)
        finally:
            # Cancellation (shutdown mid-flush) must not swallow the batch:
            # without this the cleared state would simply be gone.
            if not delivered:
                self._restore(pending_ids, events)

    def _restore(self, pending_ids: set[str], events: list[dict[str, Any]]) -> None:
        """Put an undelivered batch back. Synchronous so it still runs to
        completion when the flush was interrupted by shutdown."""
        self._dirty |= pending_ids
        headroom = _EVENT_BUFFER_MAX - len(self._events)
        if headroom < len(events):
            dropped = len(events) - max(headroom, 0)
            log_agent_action(
                "Funnel", f"Event buffer full — dropping {dropped} oldest events", level="WARNING"
            )
            events = events[-headroom:] if headroom > 0 else []
        self._events.extendleft(reversed(events))

    # --- то, что зависит от бэкенда -----------------------------------------

    async def _load(self) -> list[UserState] | None:
        """Все известные пользователи. None — хранилище недоступно."""
        raise NotImplementedError

    async def _write(self, users: list[UserState], events: list[dict[str, Any]]) -> bool:
        """Записать пачку. False — не доставлено, батч вернётся в очередь."""
        raise NotImplementedError

    async def _write_user(self, state: UserState) -> bool:
        """Записать одного пользователя немедленно — это путь оплат."""
        raise NotImplementedError

    async def _close(self) -> None:
        """Закрыть соединения."""


class SheetsStore(CachedStore):
    """Google Sheets через Apps Script.

    Заказчику показать проще всего, но таблица — не база: ни запросов, ни
    индексов, ни истории событий дальше буфера в памяти.
    """

    backend_name = "Sheets"

    async def _load(self) -> list[UserState] | None:
        if not sheets_api.is_configured():
            log_agent_action(
                "Funnel", "SHEETS_SCRIPT_URL not set — state is in-memory only", level="WARNING"
            )
            return []

        rows = await sheets_api.call("users_all")
        if not isinstance(rows, list):
            return None

        loaded = (UserState.from_row(row) for row in rows if isinstance(row, dict))
        return [state for state in loaded if state]

    async def _write(self, users: list[UserState], events: list[dict[str, Any]]) -> bool:
        payload = {"users": [state.to_row() for state in users], "events": events}
        return await sheets_api.call("flush", payload) is not None

    async def _write_user(self, state: UserState) -> bool:
        return await sheets_api.call("user_upsert", {"user": state.to_row()}) is not None

    async def _close(self) -> None:
        await sheets_api.close()


def now_iso() -> str:
    """Метка времени в том виде, в каком её понимают таблица и `parse_ts`."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_now = now_iso


def _build_store() -> Store:
    """Postgres, если задан DATABASE_URL, иначе таблица.

    Выбор по наличию адреса, а не по отдельному флагу: два переключателя рано
    или поздно разъедутся, и бот начнёт писать не туда, куда смотрят.
    """
    if os.getenv("DATABASE_URL"):
        from utils.pg_store import PostgresStore

        return PostgresStore()
    return SheetsStore()


store: Store = _build_store()
