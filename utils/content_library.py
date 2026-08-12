"""Video library backed by a private Telegram channel.

Posting a video to the content channel is the only way to add material — the
bot indexes the post (`channel_post` update) and later serves it with
`copy_message`, so nothing has to be re-uploaded and no `file_id` lives in the
source tree.

Caption format (first line = tags, everything else optional):

    #закаливание #терморегуляция
    tier: free
    Как заходить в холод без стресса

Bot API cannot read channel history, so the index is mirrored to Sheets and
reloaded on startup; `/reindex` rebuilds it for posts published while the
service was asleep.
"""

import re
from dataclasses import dataclass
from typing import Any, Iterable

from utils import sheets_api
from utils.logger import log_agent_action

TIER_FREE = "free"
TIER_PREMIUM = "premium"

_TAG_RE = re.compile(r"#([^\s#]+)")
_TIER_RE = re.compile(r"^\s*tier\s*:\s*(\w+)\s*$", re.IGNORECASE)

# Words a user might type -> canonical tag. Keeps captions short while still
# matching how people actually ask.
_TAG_SYNONYMS: dict[str, tuple[str, ...]] = {
    "закаливание": (
        "закал", "холод", "лёд", "лед", "мороз", "терморегул", "обливан",
        "прохладн", "зим", "замерз", "мёрзн", "мерзн",
    ),
    "снег": ("снег", "сугроб", "зим", "метел"),
    "бокс": ("бокс", "единоборств", "удар", "спарринг", "груш", "тренировк"),
    "пляж": ("пляж", "песок", "песку", "берег", "ракушк", "море", "морю", "моря"),
    "вода": ("вода", "воде", "воду", "море", "морю", "моря", "речк", "озер", "плаван", "дожд", "лужа"),
    "роса": ("роса", "росе", "росу", "трав", "утром", "рассвет"),
    "дыхание": ("дыхан", "дышать", "дыши", "вдох", "выдох", "одышк", "бок колет", "нос"),
    "обувь": ("кроссовк", "обув", "босиком", "босых", "подошв", "стоп", "ступн"),
    # Темы без роликов пока: подберутся, как только такие ролики появятся.
    "техника": ("техник", "перекат", "подушк", "стопу ставить", "как правильно бежать"),
    "начало": ("с чего начать", "начать бегать", "с нуля", "новичок", "первый раз"),
    "долголетие": ("долголет", "возраст", "старост", "молодост", "здоровь"),
    "травмы": ("травм", "болит", "колен", "сустав", "повредил", "боль"),
    "камешки": ("камешк", "камн", "галь", "массаж стоп"),
}


@dataclass(frozen=True)
class ContentItem:
    message_id: int
    tags: tuple[str, ...]
    tier: str = TIER_FREE
    title: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "tags": ",".join(self.tags),
            "tier": self.tier,
            "title": self.title,
        }

    @staticmethod
    def from_row(row: dict[str, Any]) -> "ContentItem | None":
        raw_id = str(row.get("message_id") or "").strip()
        if not raw_id.isdigit():
            return None
        tags = tuple(t.strip().lower() for t in str(row.get("tags") or "").split(",") if t.strip())
        tier = str(row.get("tier") or TIER_FREE).strip().lower()
        return ContentItem(
            message_id=int(raw_id),
            tags=tags,
            tier=TIER_PREMIUM if tier == TIER_PREMIUM else TIER_FREE,
            title=str(row.get("title") or ""),
        )


def parse_caption(caption: str | None, message_id: int) -> ContentItem:
    """Turn a channel post caption into an indexable item.

    A post without tags is still indexed (so it can be found by title later),
    it just never matches a topic.
    """
    text = caption or ""
    tags = tuple(dict.fromkeys(tag.lower() for tag in _TAG_RE.findall(text)))

    tier = TIER_FREE
    title_lines: list[str] = []
    for line in text.splitlines():
        tier_match = _TIER_RE.match(line)
        if tier_match:
            if tier_match.group(1).lower() == TIER_PREMIUM:
                tier = TIER_PREMIUM
            continue
        stripped = _TAG_RE.sub("", line).strip()
        if stripped:
            title_lines.append(stripped)

    return ContentItem(
        message_id=message_id,
        tags=tags,
        tier=tier,
        title=title_lines[0][:120] if title_lines else "",
    )


# Слова ищем с начала слова, а не подстрокой: «море» сидит внутри
# «терМОРЕгуляции», и без границы любое упоминание терморегуляции тянуло ролик
# про пляж.
_TAG_MATCHERS: dict[str, re.Pattern[str]] = {
    tag: re.compile(
        r"\b(?:" + "|".join(re.escape(n) for n in (tag, *needles)) + r")",
        re.IGNORECASE | re.UNICODE,
    )
    for tag, needles in _TAG_SYNONYMS.items()
}


def tags_for_text(text: str) -> tuple[str, ...]:
    """Which canonical tags a user message is asking about."""
    return tuple(tag for tag, matcher in _TAG_MATCHERS.items() if matcher.search(text))


class ContentLibrary:
    def __init__(self) -> None:
        self._items: dict[int, ContentItem] = {}

    def __len__(self) -> int:
        return len(self._items)

    def premium_count(self) -> int:
        return sum(1 for item in self._items.values() if item.tier == TIER_PREMIUM)

    async def load(self) -> None:
        rows = await sheets_api.call("content_all")
        if not isinstance(rows, list):
            log_agent_action(
                "Content", "Could not load video index — run /reindex once online", level="WARNING"
            )
            return
        for row in rows:
            if isinstance(row, dict):
                item = ContentItem.from_row(row)
                if item:
                    self._items[item.message_id] = item
        log_agent_action("Content", f"Indexed {len(self._items)} videos from Sheets")

    async def upsert(self, item: ContentItem, *, persist: bool = True) -> None:
        self._items[item.message_id] = item
        if persist:
            await sheets_api.call("content_upsert", {"item": item.to_row()})

    async def upsert_many(self, items: Iterable[ContentItem]) -> int:
        batch = list(items)
        for item in batch:
            self._items[item.message_id] = item
        if batch:
            await sheets_api.call("content_bulk", {"items": [i.to_row() for i in batch]})
        return len(batch)

    async def remove(self, message_id: int) -> None:
        self._items.pop(message_id, None)
        await sheets_api.call("content_delete", {"message_id": message_id})

    def match(
        self, text: str, *, is_premium: bool, exclude: Iterable[int] = ()
    ) -> ContentItem | None:
        """Best on-topic video the user has not seen yet, or None.

        Deliberately returns None instead of a random pick: an irrelevant video
        devalues every other one.
        """
        wanted = set(tags_for_text(text))
        if not wanted:
            return None

        skip = set(exclude)
        best: ContentItem | None = None
        best_score = 0
        for item in self._items.values():
            if item.message_id in skip:
                continue
            if item.tier == TIER_PREMIUM and not is_premium:
                continue
            score = len(wanted.intersection(self.topics_of(item)))
            if score > best_score:
                best, best_score = item, score
        return best

    @staticmethod
    def topics_of(item: ContentItem) -> set[str]:
        """Темы ролика: явные теги плюс то, что читается из названия.

        Посты в канал часто кладут без #тегов, и без этого такой ролик не
        подобрался бы никогда.
        """
        return set(item.tags) | set(tags_for_text(item.title))

    def untagged(self) -> list[ContentItem]:
        """Ролики, которые не подберутся ни по одному запросу."""
        return [item for item in self._items.values() if not self.topics_of(item)]


library = ContentLibrary()
