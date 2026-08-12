"""Залить папку с роликами в канал-библиотеку, проставив темы.

Ролики берутся откуда угодно (выгрузка TikTok, съёмка, архив) — важно лишь,
чтобы рядом лежал текст: подпись из TikTok, имя файла или файл .txt с тем же
именем. По этому тексту DeepSeek выбирает темы из фиксированного списка, а
скрипт публикует ролик в канал с подписью, которую бот уже умеет читать.

    python tools/import_videos.py ~/tiktok_export --dry-run
    python tools/import_videos.py ~/tiktok_export

Нужны переменные окружения TELEGRAM_BOT_TOKEN, CONTENT_CHANNEL_ID и
DEEPSEEK_API_KEY. Файл больше 50 МБ Telegram от бота не примет — такие
пропускаются с явным сообщением.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram import Bot  # noqa: E402
from telegram.error import TelegramError  # noqa: E402

from config import config  # noqa: E402
from utils.content_library import _TAG_SYNONYMS, TIER_FREE  # noqa: E402
from utils.llm import chat_completion  # noqa: E402

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
TELEGRAM_MAX_BYTES = 50 * 1024 * 1024
UPLOAD_PAUSE = 2.0  # Telegram не любит заливку очередью без пауз

_TAGS = sorted(_TAG_SYNONYMS)

_PROMPT = f"""Ты размечаешь ролики о беге и здоровье для базы знаний.
Выбери подходящие темы ТОЛЬКО из списка: {", ".join(_TAGS)}.

Правила:
— от одной до трёх тем, самые точные
— если ни одна не подходит, верни пустой список
— ничего не выдумывай и не добавляй тем вне списка

Ответ — строго JSON: {{"tags": ["тема"], "title": "короткое название до 60 символов"}}"""


def describe(path: Path) -> str:
    """Текст о ролике: сначала .txt рядом, иначе имя файла."""
    sidecar = path.with_suffix(".txt")
    if sidecar.exists():
        try:
            text = sidecar.read_text(encoding="utf-8").strip()
            if text:
                return text[:1500]
        except OSError:
            pass
    return path.stem.replace("_", " ").replace("-", " ")


async def classify(description: str) -> tuple[list[str], str]:
    raw = await chat_completion([
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": description},
    ])
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
    except (ValueError, json.JSONDecodeError):
        return [], description[:60]

    tags = [t for t in data.get("tags", []) if t in _TAG_SYNONYMS][:3]
    title = str(data.get("title") or description)[:60]
    return tags, title


def build_caption(tags: list[str], title: str) -> str:
    head = " ".join(f"#{t}" for t in tags)
    return f"{head}\ntier: {TIER_FREE}\n{title}".strip()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="папка с видеофайлами")
    parser.add_argument("--dry-run", action="store_true", help="только показать разметку")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Не папка: {args.folder}")
        return 1
    if not config.CONTENT_CHANNEL_ID or not config.TELEGRAM_BOT_TOKEN:
        print("Нужны CONTENT_CHANNEL_ID и TELEGRAM_BOT_TOKEN")
        return 1

    videos = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    if not videos:
        print(f"В {args.folder} нет видеофайлов")
        return 1

    print(f"Найдено роликов: {len(videos)}\n")
    bot = None if args.dry_run else Bot(config.TELEGRAM_BOT_TOKEN)
    uploaded = skipped = 0

    for path in videos:
        size = path.stat().st_size
        tags, title = await classify(describe(path))
        caption = build_caption(tags, title)

        if not tags:
            print(f"⏭  {path.name}: тема не определена, пропускаю")
            skipped += 1
            continue
        if size > TELEGRAM_MAX_BYTES:
            print(f"⏭  {path.name}: {size / 1_048_576:.1f} МБ — больше лимита Telegram в 50 МБ")
            skipped += 1
            continue

        print(f"✓  {path.name} → {' '.join('#' + t for t in tags)} | {title}")
        if args.dry_run:
            continue

        try:
            with path.open("rb") as fh:
                await bot.send_video(
                    chat_id=config.CONTENT_CHANNEL_ID, video=fh, caption=caption
                )
            uploaded += 1
        except TelegramError as e:
            print(f"✗  {path.name}: {e}")
            skipped += 1
        await asyncio.sleep(UPLOAD_PAUSE)

    if args.dry_run:
        print("\nПробный прогон — ничего не залито.")
    else:
        print(f"\nЗалито: {uploaded}, пропущено: {skipped}.")
        print("Бот проиндексирует посты сам, перезапуск не нужен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
