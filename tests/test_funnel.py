"""Unit tests for the funnel primitives — pure logic only, no network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.content_library import (  # noqa: E402
    TIER_FREE,
    TIER_PREMIUM,
    ContentItem,
    ContentLibrary,
    parse_caption,
    tags_for_text,
)
from utils.funnel_store import UserState, assign_bucket  # noqa: E402


# --- bucketing ------------------------------------------------------------

def test_bucket_is_stable_for_same_chat_id():
    assert assign_bucket("123456") == assign_bucket("123456")


def test_bucket_split_is_roughly_even():
    buckets = [assign_bucket(str(i)) for i in range(1000)]
    share_a = buckets.count("A") / len(buckets)
    assert 0.45 < share_a < 0.55


# --- user state round-trip ------------------------------------------------

def test_user_state_survives_row_round_trip():
    state = UserState(
        chat_id="42",
        bucket="B",
        is_premium=True,
        messages=7,
        cta_shown=1,
        source="tiktok",
        seen_content=(11, 12),
        created_at="2026-08-10T00:00:00+00:00",
    )
    assert UserState.from_row(state.to_row()) == state


def test_user_state_from_blank_row_is_none():
    assert UserState.from_row({"chat_id": "  "}) is None


def test_user_state_tolerates_sheets_number_formatting():
    # Apps Script hands numbers back as floats/strings
    state = UserState.from_row({"chat_id": "9", "bucket": "A", "messages": "3.0"})
    assert state is not None and state.messages == 3


# --- caption parsing ------------------------------------------------------

def test_parse_caption_extracts_tags_tier_and_title():
    item = parse_caption("#закаливание #терморегуляция\ntier: premium\nКак заходить в холод", 5)
    assert item.message_id == 5
    assert item.tags == ("закаливание", "терморегуляция")
    assert item.tier == TIER_PREMIUM
    assert item.title == "Как заходить в холод"


def test_parse_caption_defaults_to_free_tier():
    assert parse_caption("#снег\nБег по снегу", 1).tier == TIER_FREE


def test_parse_caption_handles_missing_caption():
    item = parse_caption(None, 3)
    assert item.tags == () and item.title == "" and item.tier == TIER_FREE


def test_parse_caption_does_not_duplicate_tags():
    assert parse_caption("#вода #вода", 1).tags == ("вода",)


# --- topic matching -------------------------------------------------------

def test_tags_for_text_matches_synonyms():
    assert "закаливание" in tags_for_text("а как насчёт холодной воды зимой?")


def test_tags_for_text_empty_for_offtopic():
    assert tags_for_text("сколько стоит доступ?") == ()


@pytest.fixture
def filled_library() -> ContentLibrary:
    lib = ContentLibrary()
    lib._items = {
        1: ContentItem(1, ("снег",), TIER_FREE, "снег"),
        2: ContentItem(2, ("закаливание",), TIER_PREMIUM, "закалка"),
        3: ContentItem(3, ("вода",), TIER_FREE, "вода"),
    }
    return lib


def test_match_returns_none_when_offtopic(filled_library):
    # никакого случайного фолбэка: не в тему — значит без видео
    assert filled_library.match("сколько стоит?", is_premium=False) is None


def test_match_finds_by_tag(filled_library):
    item = filled_library.match("расскажи про бег по снегу", is_premium=False)
    assert item is not None and item.message_id == 1


def test_match_hides_premium_content_from_free_user(filled_library):
    assert filled_library.match("хочу про закаливание", is_premium=False) is None
    assert filled_library.match("хочу про закаливание", is_premium=True) is not None


def test_match_skips_already_seen(filled_library):
    assert filled_library.match("про воду", is_premium=False, exclude=[3]) is None


# --- подбор без тегов -----------------------------------------------------

def test_match_uses_title_when_post_has_no_tags():
    """Посты в канал кладут без #тегов — иначе такой ролик не найдётся никогда."""
    lib = ContentLibrary()
    lib._items = {1: ContentItem(1, (), TIER_FREE, "Бег по снегу босиком")}

    assert lib.match("расскажи про снег", is_premium=False) is not None


def test_untagged_lists_only_unreachable_items():
    lib = ContentLibrary()
    lib._items = {
        1: ContentItem(1, ("снег",), TIER_FREE, ""),
        2: ContentItem(2, (), TIER_FREE, "Бег по снегу"),
        3: ContentItem(3, (), TIER_FREE, ""),
    }

    assert [i.message_id for i in lib.untagged()] == [3]


# --- распознавание тем в живых фразах -------------------------------------

@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("а если холодно на улице?", "закаливание"),
        ("как бегать зимой", "снег"),
        ("можно ли бегать по песку", "пляж"),
        ("бегать у моря", "вода"),
        ("у меня болит колено", "травмы"),
        ("с чего начать бегать", "начало"),
        ("как правильно дышать", "дыхание"),
        ("в каких кроссовках бегать", "обувь"),
    ],
)
def test_everyday_phrases_hit_a_topic(phrase, expected):
    """Словарь должен ловить обычную речь, а не только слово-тег."""
    assert expected in tags_for_text(phrase)


@pytest.mark.parametrize("phrase", ["привет", "сколько это стоит", "спасибо"])
def test_offtopic_phrases_stay_empty(phrase):
    assert tags_for_text(phrase) == ()


def test_topic_words_match_only_at_word_start():
    """«море» сидит внутри «терморегуляции» — подстрочный поиск тянул пляж."""
    assert tags_for_text("Закаливание запускает терморегуляцию") == ("закаливание",)
