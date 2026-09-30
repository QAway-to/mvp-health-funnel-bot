"""Свести выгрузку канала в манифест и черновую разметку по расшифровкам.

ЧТО ЭТО ЗА ЗАДАЧА. В канале-библиотеке лежат ролики без подписи: они не
находятся никогда, потому что бот подбирает ролик по пересечению тегов поста с
тегами вопроса, а тегов у них нет. Имя файла (`IMG_2802.MOV`) о содержании не
говорит ничего, и до расшифровок разметить их было нечем. Теперь есть чем.

ОТКУДА МЕТАДАННЫЕ. Из `messages.html` выгрузки Telegram Desktop. Bot API истории
канала не отдаёт, и раньше номер поста с размерами ролика добывали форвардом
поста в тот же канал с немедленным удалением. Выгрузка отдаёт то же самое
даром, и заодно то, чего форвард не давал: кто именно запостил.

ТЕГИ СЧИТАЕТ САМ БОТ. `tags_for_text` — та же функция, которой бот разбирает
вопрос покупателя. Совпадение здесь не вежливость к чужому коду, а условие
работы: размечать библиотеку одним словарём, а искать по ней другим — значит
класть в неё то, что не найдётся.

СТУПЕНЬ — ДОГАДКА, И ЕЁ НАДО ПРОВЕРЯТЬ. Перепутать `free` и `premium` дорого в
обе стороны: пометить курс свободным — раздать товар, пометить тиктоки платными
— лишить бота единственного, чем он подкрепляет слова до оплаты. Машине про это
известен ровно один надёжный признак: у тиктоков вырезана звуковая дорожка
(их заливали с `--mute-all`), и роликов без расшифрованной речи курс не
содержит. Поэтому «без речи» предлагается как `free`, всё остальное — как
`premium`, и обе пометки идут в черновик как вопрос, а не как решение.

НИЧЕГО НИКУДА НЕ ОТПРАВЛЯЕТСЯ. На выходе два файла рядом с выгрузкой; что с
ними делать — править подписи существующих постов или перезаливать — решает
человек. Сети в этом инструменте нет.

    python tools/channel_manifest.py "C:/Users/.../ChatExport_2026-09-28"
"""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.content_library import TIER_PREMIUM, parse_caption, tags_for_text

if TYPE_CHECKING:  # bs4 грузится лениво, ради дружелюбного «pip install»
    from bs4.element import Tag

VIDEO_DIR = "video_files"
TRANSCRIPTS = "transcripts"
MANIFEST = "manifest.tsv"
DRAFT = "captions_draft.txt"

#: Заголовок черновика режется: подпись поста — это строка, а не абзац.
TITLE_LIMIT = 70


@dataclass(frozen=True)
class Post:
    """Один пост канала с видео — ровно то, что о нём знает выгрузка."""

    message_id: int
    date: str
    file: str
    duration: str
    caption: str
    forwarded_from: str


def need(module: str, package: str) -> None:
    try:
        __import__(module)
    except ImportError:
        sys.exit(f"Нет модуля {module}. Установите:\n    pip install {package}")


def text_of(node: "Tag | None") -> str:
    """Текст узла: без служебной даты и с сохранёнными переносами строк.

    Две вещи, каждая из которых молча портит результат.

    Первая: в шапке пересланного поста имя автора и дата лежат в одном узле, и
    наивный `.text` склеивает их в «Bogdan Borovskiy 12.09.2026 16:47:52».

    Вторая дороже. Переносы строк в подписи — это `<br>`, у которого текста
    нет, поэтому любой `get_text` их теряет, а подпись схлопывается в одну
    строку. Формат подписи построчный: `tier: premium` опознаётся регулярной
    выражением, привязанной к началу и концу строки. Склей строки — и `tier`
    перестаёт быть строкой, ступень читается как `free` по умолчанию, а
    платный ролик оказывается записан как бесплатный. Ошибка при этом не
    видна ничем: подпись выглядит целой, тег на месте.
    """
    if node is None:
        return ""
    clone = copy.copy(node)
    for junk in clone.select("span.date, .details"):
        junk.decompose()
    for line_break in clone.find_all("br"):
        line_break.replace_with("\n")
    lines = (line.strip() for line in clone.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def read_posts(export: Path) -> list[Post]:
    """Разобрать `messages.html`. Посты без видео не возвращаются."""
    need("bs4", "beautifulsoup4")
    from bs4 import BeautifulSoup

    source = export / "messages.html"
    if not source.is_file():
        sys.exit(f"Нет {source} — это не выгрузка Telegram Desktop")

    soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
    posts: list[Post] = []
    for block in soup.select("div.message.default"):
        link = block.select_one("a.video_file_wrap")
        if link is None or not link.get("href"):
            continue

        raw_id = str(block.get("id") or "").removeprefix("message")
        if not raw_id.isdigit():
            continue

        stamp = block.select_one(".pull_right.date.details")
        posts.append(
            Post(
                message_id=int(raw_id),
                date=str(stamp.get("title")) if stamp else "",
                # В href лежит `video_files/IMG_2802.MOV` — нужен хвост.
                file=str(link["href"]).split("/")[-1],
                duration=text_of(block.select_one(".video_duration")),
                caption=text_of(block.select_one("div.text")),
                forwarded_from=text_of(block.select_one(".forwarded.body > .from_name")),
            )
        )
    return posts


def transcript_of(export: Path, post: Post) -> str | None:
    """Расшифровка поста. `None` — её не считали, пустая строка — там тишина."""
    target = export / TRANSCRIPTS / f"{post.file}.txt"
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8").strip()


def title_from(text: str) -> str:
    """Первое предложение как заголовок — его всё равно править руками."""
    sentence = text.strip().split(".")[0].strip()
    if len(sentence) > TITLE_LIMIT:
        return sentence[:TITLE_LIMIT].rstrip() + "…"
    return sentence or "Без названия"


def cell(value: str) -> str:
    """Значение, безопасное для TSV.

    В формате нет ни кавычек, ни экранирования: одна табуляция внутри
    поля сдвигает всю строку, и свод начинает врать про соседние
    колонки, оставаясь на вид разборным.
    """
    return value.replace("\t", " ").replace("\n", " ").strip()


def write_manifest(export: Path, posts: list[Post]) -> Path:
    """Полный свод: пост, файл, что уже размечено, что нашлось в расшифровке."""
    rows = [
        "\t".join(
            (
                "message_id", "date", "file", "duration", "forwarded_from",
                "tier", "tags", "title", "transcript_chars", "suggested_tags",
            )
        )
    ]
    for post in sorted(posts, key=lambda p: p.message_id):
        item = parse_caption(post.caption, post.message_id)
        text = transcript_of(export, post)
        suggested = tags_for_text(text) if text else ()
        rows.append(
            "\t".join(
                (
                    str(post.message_id),
                    cell(post.date),
                    cell(post.file),
                    cell(post.duration),
                    cell(post.forwarded_from),
                    item.tier,
                    ",".join(item.tags),
                    cell(item.title),
                    "—" if text is None else str(len(text)),
                    ",".join(suggested),
                )
            )
        )

    target = export / MANIFEST
    target.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return target


def write_draft(export: Path, posts: list[Post]) -> tuple[Path, int, int]:
    """Черновые подписи для постов без тегов. Возвращает путь, годных, глухих."""
    blocks: list[str] = []
    ready = blind = 0

    for post in sorted(posts, key=lambda p: p.message_id):
        if parse_caption(post.caption, post.message_id).tags:
            continue  # уже размечен — не трогаем

        text = transcript_of(export, post)
        if text is None:
            blocks.append(f"# пост {post.message_id} — {post.file}: НЕ РАСШИФРОВАН\n")
            blind += 1
            continue

        tags = tags_for_text(text)
        if not tags:
            # Речь есть, а словарь её не узнал — или речи нет вовсе. И то и
            # другое значит одно: теги ставить руками, машине сказать нечего.
            blocks.append(
                f"# пост {post.message_id} — {post.file} ({post.duration}): "
                f"{'тишина' if not text else 'теги не подобрались'}, РАЗМЕТИТЬ РУКАМИ\n"
            )
            blind += 1
            continue

        # До сюда доходит только ролик с узнанной речью, а речь у нас говорит
        # ровно об одном: это шаг курса, потому что тиктоки залиты без
        # дорожки. Развилки здесь поэтому нет — и `free` предлагать не из
        # чего. Догадка от этого не перестаёт быть догадкой: проверять руками.
        tier = TIER_PREMIUM
        blocks.append(
            f"# пост {post.message_id} — {post.file} ({post.duration})\n"
            f"{' '.join('#' + tag for tag in tags)}\n"
            f"tier: {tier}\n"
            f"{title_from(text)}\n"
        )
        ready += 1

    target = export / DRAFT
    target.write_text(
        "#! Черновик. Теги собраны машиной по расшифровке, заголовки — первая\n"
        "#! фраза ролика. Ступень free/premium — ДОГАДКА: проверьте каждую.\n"
        "#! Пометить курс как free значит раздать товар.\n\n"
        + "\n".join(blocks),
        encoding="utf-8",
    )
    return target, ready, blind


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Манифест и черновая разметка по выгрузке канала"
    )
    parser.add_argument("export", type=Path, help="папка выгрузки (та, где messages.html)")
    args = parser.parse_args()

    export = args.export.expanduser()
    if not export.is_dir():
        sys.exit(f"Нет папки {export}")

    posts = read_posts(export)
    if not posts:
        sys.exit("В выгрузке не нашлось ни одного поста с видео")

    manifest = write_manifest(export, posts)
    draft, ready, blind = write_draft(export, posts)

    tagged = sum(1 for p in posts if parse_caption(p.caption, p.message_id).tags)
    print(f"Постов с видео: {len(posts)} (уже с тегами {tagged})")
    print(f"{manifest.name}: свод по всем постам")
    print(f"{draft.name}: предложено {ready}, руками разметить {blind}")


if __name__ == "__main__":
    main()
