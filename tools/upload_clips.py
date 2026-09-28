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

СТУПЕНЬ ПОШТУЧНО. Там же, через запятую, можно указать `free` или `premium` —
это перебьёт общий `--tier` для одной строки:

    IMG_2783.MOV | #зарядка | Вступление          | free
    IMG_2785.MOV | #зарядка | Подъём и воздух     | premium
    IMG_2786.MOV | #зарядка | Разминка и растяжка | mute, premium

Нужно это ровно там, где курс заливается одной пачкой: вступление свободное,
шаги платные. Без пометки пачку пришлось бы делить на две папки руками — а
делят их руками, и ровно там платный ролик уезжает в свободные.

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
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.video_meta import ffmpeg_exe, probe  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CAPTIONS_FILE = "captions.txt"
SENT_FILE = ".uploaded.json"
TIERS = ("free", "premium")
#: Пометки, допустимые четвёртой частью строки captions.txt. Собирается из
#: TIERS, чтобы третья ступень, если она появится, не потребовала правки в
#: двух местах — разойдутся они молча.
KNOWN_FLAGS = {"mute", *TIERS}
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
    #: Ступень этого ролика. Пусто — берётся общая, из --tier.
    #:
    #: Появилось, когда понадобилось залить курс и тиктоки одной пачкой:
    #: вступления свободные, шаги платные. Без этого пачку приходится делить
    #: на две папки и гонять скрипт дважды — а делят её руками, и ровно там
    #: платный ролик уезжает в свободные.
    tier: str = ""

    def caption(self, default_tier: str) -> str:
        return f"{self.tags}\ntier: {self.tier or default_tier}\n{self.title}"


@contextmanager
def without_sound(path: Path):
    """Копия ролика без звуковой дорожки. Удаляется сразу после отправки.

    `-c:v copy` — картинка переписывается байт в байт, без перекодирования:
    ролик не теряет качества и не ждёт минуту на кодеке.

    `+faststart` обязателен. По умолчанию ffmpeg дописывает служебный блок
    `moov` в конец файла, и до самого конца скачивания никто не знает ни
    размеров кадра, ни длительности. Telegram столько не читает — и кладёт
    ролик в канал как `320x320` без превью.
    """
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / f"{path.stem}-mute.mp4"
        result = subprocess.run(
            [ffmpeg_exe(), "-y", "-i", str(path),
             "-c:v", "copy", "-an", "-movflags", "+faststart", str(target)],
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
            problems.append(f"строка {number}: нужно три части через | (или четыре с пометками)")
            continue
        name, tags, title = parts[:3]
        # Пометки четвёртой частью, через запятую: mute, free, premium.
        # Порядок не важен, регистр тоже.
        flags = {f.strip().lower() for f in parts[3].split(",")} if len(parts) == 4 else set()
        flags.discard("")
        unknown = flags - KNOWN_FLAGS
        if unknown:
            problems.append(
                f"строка {number}: непонятные пометки {sorted(unknown)} — бывают mute, {', '.join(TIERS)}"
            )
            continue
        tiers = flags & set(TIERS)
        if len(tiers) > 1:
            problems.append(f"строка {number}: две ступени сразу — {sorted(tiers)}")
            continue
        if not tags.startswith("#"):
            problems.append(f"строка {number}: теги должны начинаться с #")
            continue
        path = folder / name
        if not path.is_file():
            problems.append(f"строка {number}: нет файла {name}")
            continue
        clips.append(Clip(
            path=path, tags=tags, title=title,
            mute="mute" in flags, tier=next(iter(tiers), ""),
        ))

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
    # encoding обязателен. Пишется файл в utf-8, а read_text без аргумента
    # берёт кодировку системы — на Windows это не utf-8, и книжка с именем
    # вроде «закалка.mp4» не читается обратно. Ломалось это ровно там, где
    # книжка и нужна: на повторном запуске после обрыва, посреди залитой
    # наполовину пачки.
    sent: dict[str, int] = (
        json.loads(sent_log.read_text(encoding="utf-8")) if sent_log.is_file() else {}
    )

    if args.dry_run:
        for clip in clips:
            mark = "уже залит" if clip.path.name in sent else f"{clip.path.stat().st_size / 2**20:.1f} МБ"
            # Ступень печатаем всегда: пробный прогон затем и нужен, чтобы
            # увидеть платное платным до того, как оно уедет свободным.
            marks = f"{mark}, {clip.tier or args.tier}" + (", без звука" if clip.mute else "")
            print(f"{clip.path.name}  [{marks}]")
            print("  " + clip.caption(args.tier).replace("\n", "\n  "))
        # Раньше здесь печаталась одна общая ступень. С поштучными пометками
        # она стала враньём: под единственным платным роликом стояло
        # «tier: free». Считаем по тому, что реально уедет в подписи.
        counts = Counter(clip.tier or args.tier for clip in clips)
        breakdown = ", ".join(f"{tier} {counts[tier]}" for tier in TIERS if counts[tier])
        print(f"\nвсего: {len(clips)} — {breakdown}")
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
            # Размеры и длительность передаём сами. Оставить это Telegram
            # нельзя: файлы больше примерно 10 МБ он не разбирает и записывает
            # ролик как 320x320 — вертикальное видео после этого показывается
            # растянутым, и у готового поста это уже не исправить ничем, кроме
            # перезаливки.
            meta = probe(source, ffmpeg_exe())
            fields: dict[str, object] = {
                "chat_id": channel,
                "caption": clip.caption(args.tier),
                "supports_streaming": True,
            }
            if meta.is_usable:
                fields |= {
                    "width": meta.width,
                    "height": meta.height,
                    "duration": meta.duration,
                }
            else:
                print(f"[{index}/{len(clips)}] {name} — размеры не прочитались, "
                      "заливаю без них", flush=True)
            with source.open("rb") as handle:
                files: dict[str, tuple] = {"video": (name, handle, "video/mp4")}
                if meta.thumbnail:
                    files["thumbnail"] = ("thumb.jpg", meta.thumbnail, "image/jpeg")
                response = requests.post(url, data=fields, files=files, timeout=600)
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
