"""Расписание догоняющих сообщений.

Цена ошибки здесь — не сломанный экран, а письмо не тому человеку или в три
часа ночи. Поэтому решение «кому сейчас положено» вынесено в чистую функцию,
и проверяется она целиком: пороги тишины, порядок шагов, ночное окно и
пропуск продающего шага при выключённом оффере.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.followups import (  # noqa: E402
    MAX_SILENCE_HOURS,
    FollowUp,
    _parse,
    is_quiet_hour,
    next_step,
    parse_ts,
)
from utils.offer import CtaButton  # noqa: E402

MSK = timezone(timedelta(hours=3))

# Полдень по Москве: заведомо не ночь, чтобы окно тишины не мешало проверять
# сами пороги.
NOON = datetime(2026, 8, 21, 12, 0, tzinfo=MSK)


def ago(hours: float, *, now: datetime = NOON) -> str:
    return (now - timedelta(hours=hours)).isoformat(timespec="seconds")


STEPS = (
    FollowUp(1, 1.0, "через час", (CtaButton("offer", "Условия"),)),
    FollowUp(2, 24.0, "через сутки", (CtaButton("gift", "Чек-лист"),)),
    FollowUp(3, 72.0, "последнее", (CtaButton("offer", "Условия"),)),
)


def call(**overrides):
    kwargs = dict(
        steps=STEPS,
        last_seen_at=ago(2),
        followups_sent=0,
        is_premium=False,
        now=NOON,
        offer_ready=True,
    )
    kwargs.update(overrides)
    return next_step(**kwargs)


# --- пороги тишины ---------------------------------------------------------


def test_silence_below_threshold_sends_nothing():
    step, sent = call(last_seen_at=ago(0.5))
    assert step is None
    assert sent == 0


def test_first_step_fires_after_its_threshold():
    step, sent = call(last_seen_at=ago(1.2))
    assert step is not None and step.index == 1
    assert sent == 1


def test_second_step_waits_for_its_own_silence():
    """Получив первый шаг, человек не получает второй через минуту."""
    step, sent = call(last_seen_at=ago(2), followups_sent=1)
    assert step is None
    assert sent == 1

    step, sent = call(last_seen_at=ago(25), followups_sent=1)
    assert step is not None and step.index == 2


def test_queue_ends_after_last_step():
    step, sent = call(last_seen_at=ago(500), followups_sent=3)
    assert step is None
    assert sent == 3


# --- кого не трогаем -------------------------------------------------------


def test_paying_customer_is_never_chased():
    step, _ = call(last_seen_at=ago(100), is_premium=True)
    assert step is None


def test_user_without_last_seen_is_skipped():
    """Ни слова, ни /start — догонять нечего и не за что."""
    step, _ = call(last_seen_at="")
    assert step is None


def test_long_gone_user_is_left_alone():
    step, _ = call(last_seen_at=ago(MAX_SILENCE_HOURS + 1))
    assert step is None


# --- продающий шаг при выключённом оффере ----------------------------------


def test_sales_step_skipped_when_offer_not_ready():
    """Шаг с кнопкой покупки пропускается насовсем, а не блокирует очередь."""
    step, sent = call(last_seen_at=ago(30), offer_ready=False)
    assert step is not None and step.index == 2      # первый продающий пропущен
    assert sent == 2


def test_queue_does_not_stall_on_sales_step():
    step, sent = call(last_seen_at=ago(2), offer_ready=False)
    assert step is None
    assert sent == 1        # счётчик сдвинулся, очередь не встала


# --- ночное окно -----------------------------------------------------------


@pytest.mark.parametrize("hour,quiet", [(3, True), (8, True), (9, False), (20, False), (21, True), (23, True)])
def test_quiet_hours_follow_audience_timezone(hour, quiet):
    moment = datetime(2026, 8, 21, hour, 30, tzinfo=MSK)
    assert is_quiet_hour(moment) is quiet


# --- разбор файла ----------------------------------------------------------


def test_parse_reads_steps_buttons_and_order():
    raw = """
# комментарий не попадает в текст

== 24
Второй по файлу, первый по времени? нет — сутки.
@gift Чек-лист

== 1
Через час.
@offer Условия
@gift Пока рано
"""
    steps = _parse(raw)

    assert [s.after_hours for s in steps] == [1.0, 24.0]
    assert [s.index for s in steps] == [1, 2]        # перенумерованы после сортировки
    assert steps[0].text == "Через час."
    assert [b.action for b in steps[0].buttons] == ["offer", "gift"]
    assert steps[0].is_sales is True
    assert steps[1].is_sales is False
    assert "комментарий" not in steps[0].text


def test_step_without_text_is_dropped():
    steps = _parse("== 1\n@offer Только кнопка\n")
    assert steps == ()


# --- метки времени ---------------------------------------------------------


def test_naive_timestamp_is_read_as_utc():
    parsed = parse_ts("2026-08-21T10:00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_broken_timestamp_is_not_a_crash():
    assert parse_ts("вчера") is None
    assert parse_ts("") is None
