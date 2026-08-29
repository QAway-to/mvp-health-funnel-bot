"""Залить ролики в канал-библиотеку бота.

ДВА ВИДА РОЛИКОВ, И ЭТО ГЛАВНОЕ РАЗЛИЧИЕ ВО ВСЕЙ БИБЛИОТЕКЕ.

*free* — публичные ролики из TikTok. Они уже лежат в открытом доступе, на них
водяной знак TikTok, и прятать их за подписку бессмысленно: спрятать нельзя
то, что уже показано. Их работа другая — бот прикрепляет такой ролик к своему
ответу, когда тег совпал с тем, о чём идёт разговор. Это доказательство на
этапе продажи: человек читает текст и тут же видит, что за ним стоит живой
автор, а не пересказ статей.

*premium* — шаги курса. Их нигде больше нет, и это то, за что платят. Такой
ролик уходит только подписчику; остальным тот же шаг приходит текстом.

Перепутать их дорого в обе стороны. Пометить курс как free — раздать товар.
Пометить тиктоки как premium — лишить бота единственного, чем он может
подкрепить свои слова до оплаты.

ЗВУК. Ролики из TikTok обычно идут с музыкой, и в чате она не помогает: смысл
в них показан, а не рассказан. Весь набор — без звука:

    python tools/upload_clips.py папка --mute-all

Поштучно — четвёртой частью строки `mute`:

    IMG_1234.mp4 | #закаливание | Обливание на снегу | mute

Ролик уйдёт без звука. Дорожка вырезается копированием картинки, без
перекодирования: качество не меняется, занимает секунду.

ПОДПИСЬ РЕШАЕТ ВСЁ. Бот подбирает ролик только по ней:

    #тег #ещёодин
    tier: free
    Заголовок ролика

Пост без тегов попадёт в библиотеку и не подберётся никогда.

КАК ПОЛЬЗОВАТЬСЯ

Рядом с роликами кладётся `captions.txt`, по строке на файл:

    IMG_1234.mp4 | #закаливание #снег | Обливание на снегу
    IMG_1235.mp4 | #дыхание | Дыхание на морозе
    IMG_1236.mp4 | #бокс | Работа по мешку | mute

Дальше:

    python tools/upload_clips.py путь/к/папке --dry-run   посмотреть, что уйдёт
    python tools/upload_clips.py путь/к/папке             залить
    python tools/upload_clips.py путь/к/папке --tier premium

Повторный запуск безопасен: уже залитое (по `.uploaded.json` в той же папке)
пропускается.

ПОСЛЕ ЗАЛИВКИ ОБЯЗАТЕЛЬНА ПЕРЕИНДЕКСАЦИЯ. Своих постов бот в `channel_post`
не получает вовсе — ролики, залитые его же токеном, сами в библиотеку не
попадут никогда:

    GET /tasks/reindex?key=<TASKS_SECRET>&from=<первый>&to=<последний>
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
CAPTIONS_FILE = "captions.txt"
SENT_FILE = ".uploaded.json"
TIERS = ("free", "premium")
#: Пауза между отправками: на двух десятках файлов подряд Telegram отвечает
#: flood limit, и половина заливки молча теряется.
PAUSE_SECONDS = 2


@dataclass(frozen=True)
class Clip:
    path: Path
    tags: str
    title: str
    #: Заливать без звука. Не редкость: на части роликов музыка из TikTok или
    #: посторонний шум, и в чате он мешает, а не помогает.
    mute: bool = False

    def caption(self, tier: str) -> str:
        return f"{self.tags}\ntier: {tier}\n{self.title}"


@contextmanager
def without_sound(path: Path):
    """Копия ролика без звуковой дорожки. Удаляется сразу после отправки.

    `-c:v copy` — картинка переписывается байт в байт, без перекодирования:
    ролик не теряет качества и не ждёт минуту на кодеке.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        sys.exit("Для вырезания звука нужен ffmpeg:\n    pip install imageio-ffmpeg")

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / f"{path.stem}-mute.mp4"
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(path),
             "-c:v", "copy", "-an", str(target)],
            capture_output=True,
        )
        if result.returncode != 0 or not target.is_file():
            sys.exit(
                f"Не вышло вырезать звук из {path.name}:\n"
                + result.stderr.decode(errors="replace")[-400:]
            )
        yield target


def read_env() -> tuple[str, str]:
    """Токен и канал из .env репозитория. В аргументы командной строки они не
    попадают: список процессов виден всей машине."""
    env = REPO / ".env"
    if not env.is_file():
        sys.exit(
            f"Нет {env}\nВпишите в него две строки (значения — из панели Render):\n"
            "  TELEGRAM_BOT_TOKEN=...\n  CONTENT_CHANNEL_ID=..."
        )
    values: dict[str, str] = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    token = values.get("TELEGRAM_BOT_TOKEN", "")
    channel = values.get("CONTENT_CHANNEL_ID", "")
    if not token or not channel:
        sys.exit("В .env нет TELEGRAM_BOT_TOKEN или CONTENT_CHANNEL_ID")
    return token, channel


def read_clips(folder: Path) -> list[Clip]:
    """Разобрать captions.txt. Строка без тегов — это ошибка, а не мелочь."""
    listing = folder / CAPTIONS_FILE
    if not listing.is_file():
        sys.exit(f"Нет {listing}. Формат строки:\n  файл.mp4 | #тег #тег | Заголовок")

    clips: list[Clip] = []
    problems: list[str] = []
    for number, line in enumerate(listing.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#!"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) not in (3, 4):
            problems.append(f"строка {number}: нужно три части через | (или четыре с mute)")
            continue
        name, tags, title = parts[:3]
        flag = parts[3].lower() if len(parts) == 4 else ""
        if flag not in ("", "mute"):
            problems.append(f"строка {number}: четвёртой частью бывает только mute, а не {flag!r}")
            continue
        if not tags.startswith("#"):
            problems.append(f"строка {number}: теги должны начинаться с #")
            continue
        path = folder / name
        if not path.is_file():
            problems.append(f"строка {number}: нет файла {name}")
            continue
        clips.append(Clip(path=path, tags=tags, title=title, mute=flag == "mute"))

    if problems:
        sys.exit("\n".join(["Ролики не залиты — сначала поправьте:", *problems]))
    return clips


@contextmanager
def _as_is(path: Path):
    """Ролик как есть — чтобы обе ветки отправки выглядели одинаково."""
    yield path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="папка с роликами и captions.txt")
    parser.add_argument(
        "--tier",
        choices=TIERS,
        default="free",
        help="free — публичные ролики из TikTok (по умолчанию); premium — шаги курса",
    )
    parser.add_argument(
        "--mute-all",
        action="store_true",
        help="залить все ролики без звука (перебивает отметки mute в captions.txt)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    folder: Path = args.folder
    if not folder.is_dir():
        sys.exit(f"Нет папки {folder}")

    clips = read_clips(folder)
    if args.mute_all:
        clips = [replace(clip, mute=True) for clip in clips]
    sent_log = folder / SENT_FILE
    sent: dict[str, int] = json.loads(sent_log.read_text()) if sent_log.is_file() else {}

    if args.dry_run:
        for clip in clips:
            mark = "уже залит" if clip.path.name in sent else f"{clip.path.stat().st_size / 2**20:.1f} МБ"
            print(f"{clip.path.name}  [{mark}{', без звука' if clip.mute else ''}]")
            print("  " + clip.caption(args.tier).replace("\n", "\n  "))
        print(f"\nвсего: {len(clips)}, tier: {args.tier}")
        return

    token, channel = read_env()
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    posted: list[int] = []

    for index, clip in enumerate(clips, 1):
        name = clip.path.name
        if name in sent:
            print(f"[{index}/{len(clips)}] {name} — уже залит", flush=True)
            posted.append(sent[name])
            continue

        with without_sound(clip.path) if clip.mute else _as_is(clip.path) as source:
            with source.open("rb") as handle:
                response = requests.post(
                    url,
                    data={
                        "chat_id": channel,
                        "caption": clip.caption(args.tier),
                        "supports_streaming": True,
                    },
                    files={"video": (name, handle, "video/mp4")},
                    timeout=600,
                )
        payload = response.json()
        if not payload.get("ok"):
            print(f"[{index}/{len(clips)}] {name} — ОШИБКА: {payload}", flush=True)
            continue

        message_id = payload["result"]["message_id"]
        sent[name] = message_id
        posted.append(message_id)
        sent_log.write_text(json.dumps(sent, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{index}/{len(clips)}] {name} → пост #{message_id}", flush=True)
        time.sleep(PAUSE_SECONDS)

    if posted:
        print(
            "\nГотово. Теперь переиндексация — без неё роликов для бота не существует:\n"
            f"  /tasks/reindex?key=<TASKS_SECRET>&from={min(posted)}&to={max(posted)}"
        )


if __name__ == "__main__":
    main()
