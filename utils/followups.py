"""Догоняющие сообщения: что бот пишет сам, когда разговор оборвался.

Без этого воронка живёт ровно одну сессию: человек ушёл думать — и больше о
нём никто не вспомнит. Тексты и кнопки лежат в `prompts/followups.txt`, здесь
только расписание и правило «кому сейчас положено».

Решение о том, кого догонять, вынесено в чистую функцию `next_step`: она не
ходит в сеть и не трогает Telegram, поэтому проверяется тестами целиком.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils.logger import log_agent_action
from utils.offer import CtaButton, split_buttons

_PROMPTS_PATH = Path(__file__).resolve().parents[1] / "prompts" / "followups.txt"

# «== 1» открывает шаг, который отправляется после часа тишины.
_STEP_RE = re.compile(r"^==\s*(\d+(?:[.,]\d+)?)\s*$")

# Дольше этого срока человека не трогаем: тот, кто молчит месяц, ушёл, и письмо
# «вдогонку» через полгода выглядит не заботой, а спамом из мёртвой базы.
MAX_SILENCE_HOURS = 24 * 30

# Часовой пояс аудитории и окно, в которое допустима рассылка. Пишем только
# днём: сообщение в четыре утра стоит отписки, а не прочтения.
_AUDIENCE_TZ = timezone(timedelta(hours=3))
QUIET_FROM_HOUR = 21
QUIET_UNTIL_HOUR = 9


@dataclass(frozen=True)
class FollowUp:
    """Один шаг цепочки."""

    index: int              # 1-based, для событий и логов
    after_hours: float      # сколько тишины должно пройти
    text: str
    buttons: tuple[CtaButton, ...]

    @property
    def is_sales(self) -> bool:
        """Шаг зовёт покупать — значит, требует настроенного оффера."""
        return any(button.action == "offer" for button in self.buttons)


def _parse(raw: str) -> tuple[FollowUp, ...]:
    steps: list[FollowUp] = []
    current_hours: float | None = None
    chunk: list[str] = []

    def flush() -> None:
        if current_hours is None:
            return
        text, buttons = split_buttons("\n".join(chunk))
        if not text:
            log_agent_action(
                "Followups", f"Шаг на {current_hours}ч без текста — пропущен", level="WARNING"
            )
            return
        steps.append(
            FollowUp(
                index=len(steps) + 1,
                after_hours=current_hours,
                text=text,
                buttons=buttons,
            )
        )

    for line in raw.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _STEP_RE.match(line.strip())
        if match:
            flush()
            current_hours = float(match.group(1).replace(",", "."))
            chunk = []
            continue
        chunk.append(line)
    flush()

    ordered = tuple(sorted(steps, key=lambda step: step.after_hours))
    # Порядок в файле мог оказаться другим — перенумеровываем после сортировки,
    # иначе индекс в аналитике перестанет совпадать с очередью отправки.
    return tuple(
        FollowUp(index=i + 1, after_hours=s.after_hours, text=s.text, buttons=s.buttons)
        for i, s in enumerate(ordered)
    )


def load_followups() -> tuple[FollowUp, ...]:
    try:
        raw = _PROMPTS_PATH.read_text(encoding="utf-8")
    except OSError as e:
        log_agent_action("Followups", f"Не прочитан followups.txt: {e}", level="WARNING")
        return ()
    steps = _parse(raw)
    if steps:
        schedule = ", ".join(f"{s.after_hours:g}ч" for s in steps)
        log_agent_action("Followups", f"Загружено шагов: {len(steps)} ({schedule})")
    else:
        log_agent_action("Followups", "followups.txt пуст — догоняющих сообщений не будет")
    return steps


def parse_ts(value: str) -> datetime | None:
    """Разобрать метку времени из состояния. Пустая или битая — это не авария."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Ранние строки писались без зоны; считаем их UTC, а не локальным временем
    # сервера — иначе расписание поедет вместе с часовым поясом хостинга.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_quiet_hour(now: datetime) -> bool:
    """Ночь по времени аудитории — рассылку придержать до утра."""
    hour = now.astimezone(_AUDIENCE_TZ).hour
    return hour >= QUIET_FROM_HOUR or hour < QUIET_UNTIL_HOUR


def next_step(
    *,
    steps: tuple[FollowUp, ...],
    last_seen_at: str,
    followups_sent: int,
    is_premium: bool,
    now: datetime,
    offer_ready: bool,
) -> tuple[FollowUp | None, int]:
    """Что сейчас положено отправить этому человеку.

    Возвращает (шаг или None, новое значение followups_sent). Второе число
    меняется и когда отправлять нечего: продающий шаг при выключённом оффере
    пропускается насовсем, иначе очередь встала бы на нём навсегда.
    """
    if is_premium or not steps:
        return None, followups_sent

    last_seen = parse_ts(last_seen_at)
    if last_seen is None:
        # Человек не сказал ни слова и даже не нажал /start — догонять нечего.
        return None, followups_sent

    silence_hours = (now - last_seen).total_seconds() / 3600
    if silence_hours > MAX_SILENCE_HOURS:
        return None, followups_sent

    index = max(followups_sent, 0)
    while index < len(steps):
        step = steps[index]
        if silence_hours < step.after_hours:
            return None, index
        if step.is_sales and not offer_ready:
            log_agent_action(
                "Followups",
                f"Шаг {step.index} продающий, а оффер выключен — пропускаю",
            )
            index += 1
            continue
        return step, index + 1
    return None, index
