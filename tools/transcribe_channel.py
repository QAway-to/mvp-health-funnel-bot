"""Расшифровать ролики из выгрузки канала-библиотеки (Telegram Desktop).

ЗАЧЕМ ОТДЕЛЬНЫЙ ПУТЬ, А НЕ БОТ. Бот берёт файлы канала через `getFile`, а тот
молча обрывается на 20 МБ. Курсовые ролики весят 28–128 МБ, то есть через Bot
API недоступны вообще — сколько ключей ни меняй. «Экспорт истории чата» из
Telegram Desktop снимает это целиком: файлы уже лежат на диске, и Telegram из
цепочки выпадает. Скачивать здесь нечего, поэтому и сети тут нет.

ЧТО НА ВЫХОДЕ. По файлу на ролик: `<выгрузка>/transcripts/<имя ролика>.txt`.

Пустой файл — это тишина, а не поломка. А вот ролик, на котором расшифровка
упала, файла не получает намеренно — следующий запуск возьмётся за него снова.
Разница между «посчитали, там тишина» и «не посчитали» и есть всё, на чём
держится дозапуск, поэтому пустой файл имеет право появиться только там, где
тишина доказана, — см. `audio_state`.

ДУБЛИ СЧИТАЮТСЯ ОДИН РАЗ. В канале лежат остатки сорванных заливок: один и тот
же файл байт в байт в разных постах (`IMG_2796.MOV` попал туда трижды). Гонять
модель по ним повторно незачем — ролики сверяются по хешу, текст считается для
одного и раскладывается по всем именам группы. Хеш считается только для тех,
что ещё не расшифрованы: читать ради этого все 2.5 ГБ на каждом запуске глупо.

ПОЧЕМУ ЛУЧ ШИРЕ, ЧЕМ В `tiktok_ingest`. Там стоит `beam_size=1`, и это верно
для тиктоков: речи в них нет, ширина луча ничего не спасёт, а время съест.
Здесь наоборот — это шаги курса, их текст пойдёт в базу знаний, и цена ошибки
в слове выше цены лишних минут счёта.

    python tools/transcribe_channel.py "C:/Users/.../ChatExport_2026-09-28"
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

#: Подпапка выгрузки, куда Telegram Desktop кладёт видео. Рядом с роликами там
#: лежат превью `<имя>.MOV_thumb.jpg` — по расширению они и отсеиваются.
VIDEO_DIR = "video_files"
TRANSCRIPTS = "transcripts"
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")

#: `small` лежит в локальном кеше и на русском держится заметно лучше `base`:
#: та не столько путает буквы, сколько подставляет вместо неуслышанного слова
#: похожее по звучанию, и текст выходит связным на вид и неверным по сути.
WHISPER_MODEL = "small"
BEAM_SIZE = 5

#: Три состояния звуковой дорожки. Строки, а не enum: они же идут в лог.
AUDIO_PRESENT = "есть"
AUDIO_NONE = "нет"
AUDIO_BROKEN = "битый"


def need(module: str, package: str) -> None:
    try:
        __import__(module)
    except ImportError:
        sys.exit(f"Нет модуля {module}. Установите:\n    pip install {package}")


def find_videos(export: Path) -> list[Path]:
    """Ролики выгрузки, по возрастанию размера."""
    folder = export / VIDEO_DIR
    if not folder.is_dir():
        sys.exit(f"В {export} нет папки {VIDEO_DIR} — это не выгрузка Telegram Desktop")
    videos = [p for p in folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES and p.is_file()]
    if not videos:
        sys.exit(f"В {folder} нет видео")
    # Мелкие вперёд: если запуск прервут, успеет посчитаться больше роликов.
    return sorted(videos, key=lambda p: (p.stat().st_size, p.name))


def digest(path: Path) -> str:
    """Хеш файла. Читается кусками — ролики бывают по сто с лишним мегабайт."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def group_duplicates(videos: list[Path]) -> list[list[Path]]:
    """Сгруппировать одинаковые ролики. Размер отсеивает почти всё до чтения."""
    by_size: dict[int, list[Path]] = {}
    for video in videos:
        by_size.setdefault(video.stat().st_size, []).append(video)

    groups: list[list[Path]] = []
    for same_size in by_size.values():
        # Уникальный размер — читать файл незачем, совпасть не с чем.
        if len(same_size) == 1:
            groups.append(same_size)
            continue
        by_hash: dict[str, list[Path]] = {}
        for video in same_size:
            by_hash.setdefault(digest(video), []).append(video)
        groups.extend(by_hash.values())
    return groups


def audio_state(path: Path) -> str:
    """Есть ли у ролика звуковая дорожка — и цел ли вообще контейнер.

    Спрашивать это до модели, а не разбирать её исключение, приходится потому,
    что на файле без дорожки faster-whisper падает с `tuple index out of
    range` — сообщением, по которому причину не опознать никогда. А причина
    смирная и заранее известная: тиктоки заливались в канал через
    `upload_clips.py --mute-all`, дорожки у них вырезаны.

    Разница важна не для красоты лога. Ролик без дорожки — это доказанная
    тишина, и пустой файл ему положен: пересчитывать его нечем и незачем.
    Битый контейнер — наоборот, ничего не доказывает и файла не получает.
    """
    import av

    try:
        with av.open(str(path)) as container:
            return AUDIO_PRESENT if container.streams.audio else AUDIO_NONE
    except Exception:  # noqa: BLE001 — любой отказ разбора здесь значит одно
        return AUDIO_BROKEN


def transcribe(export: Path, model_name: str, beam: int) -> None:
    need("faster_whisper", "faster-whisper")
    # PyAV приезжает вместе с faster-whisper и потому почти всегда на месте.
    # Спрашивается он здесь, а не в `audio_state`, ради единственного: там его
    # отсутствие попало бы в `except` и каждый ролик объявило бы битым.
    need("av", "av")
    from faster_whisper import WhisperModel

    folder = export / TRANSCRIPTS
    folder.mkdir(parents=True, exist_ok=True)

    videos = find_videos(export)
    target_of = {video: folder / f"{video.name}.txt" for video in videos}
    pending = [video for video in videos if not target_of[video].is_file()]
    if not pending:
        print(f"Все {len(videos)} роликов уже расшифрованы — в {folder}")
        return

    groups = group_duplicates(pending)
    doubles = sum(len(group) - 1 for group in groups)
    print(
        f"Расшифровываю {len(groups)} из {len(videos)} "
        f"(уже готово {len(videos) - len(pending)}, дублей {doubles}); "
        f"модель {model_name}, луч {beam}",
        flush=True,
    )

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    started = time.monotonic()
    failed: list[tuple[Path, str]] = []
    broken: list[Path] = []
    silent = 0

    for index, group in enumerate(groups, 1):
        source = group[0]
        also = f" (+{len(group) - 1} дубл.)" if len(group) > 1 else ""
        state = audio_state(source)

        if state == AUDIO_BROKEN:
            broken.append(source)
            print(f"[{index}/{len(groups)}] {source.name}: битый файл в выгрузке{also}", flush=True)
            continue

        if state == AUDIO_NONE:
            # Дорожки нет вовсе — тишина доказана самим контейнером, модель
            # тут не нужна и всё равно упала бы.
            text, mark = "", "без дорожки"
        else:
            try:
                segments, info = model.transcribe(
                    str(source),
                    language="ru",
                    vad_filter=True,
                    beam_size=beam,
                    # Whisper склонен продолжать собственный предыдущий вывод,
                    # и на коротком ролике это превращается в повтор фразы.
                    condition_on_previous_text=False,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
            except Exception as error:  # noqa: BLE001 — один плохой ролик не отменяет остальные
                failed.append((source, str(error)))
                print(f"[{index}/{len(groups)}] {source.name}: ОШИБКА {error}", flush=True)
                continue

            # Дорожка есть, а декодер не дал ни секунды — это отказ, и выдать
            # его за тишину нельзя: пустой файл закрыл бы ролик навсегда.
            if not text and not info.duration:
                failed.append((source, "дорожка есть, но декодер не дал ни секунды"))
                print(f"[{index}/{len(groups)}] {source.name}: ОШИБКА пустой разбор", flush=True)
                continue

            mark = "тишина" if not text else f"{len(text)} знаков"

        try:
            # Файл пишется всем именам группы: дальше по цепочке про дубли
            # знать не нужно, каждый пост находит текст по имени своего файла.
            for video in group:
                target_of[video].write_text(text, encoding="utf-8")
        except OSError as error:
            # Считали, но не сохранили. Группа могла записаться наполовину —
            # уцелевшие имена просто не попадут в следующий запуск, а
            # оставшиеся попадут, так что потеряно только время.
            failed.append((source, f"не записалось: {error}"))
            print(f"[{index}/{len(groups)}] {source.name}: ОШИБКА записи {error}", flush=True)
            continue

        if not text:
            silent += 1
        print(f"[{index}/{len(groups)}] {source.name}: {mark}{also}", flush=True)

    minutes = (time.monotonic() - started) / 60
    print(f"\nГотово за {minutes:.0f} мин, тексты в {folder}")
    print(f"Из них без речи: {silent}")
    if broken:
        print(f"Битых файлов в самой выгрузке {len(broken)} — их не спасти, нужна новая выгрузка:")
        for source in broken:
            print(f"  {source.name}")
    if failed:
        print(f"Не сосчитано {len(failed)} — следующий запуск возьмётся за них снова:")
        for source, reason in failed:
            print(f"  {source.name}: {reason}")


def main() -> None:
    # Русский вывод на Windows встречается с консолью в cp1252 и роняет запуск
    # на первой же строке. Считать часами, чтобы упасть на печати, глупо.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Расшифровать ролики из выгрузки канала Telegram Desktop"
    )
    parser.add_argument("export", type=Path, help="папка выгрузки (та, где messages.html)")
    parser.add_argument(
        "--model", default=WHISPER_MODEL, help=f"модель Whisper (по умолчанию {WHISPER_MODEL})"
    )
    parser.add_argument(
        "--beam", type=int, default=BEAM_SIZE, help=f"ширина луча (по умолчанию {BEAM_SIZE})"
    )
    args = parser.parse_args()

    export = args.export.expanduser()
    if not export.is_dir():
        sys.exit(f"Нет папки {export}")
    transcribe(export, args.model, args.beam)


if __name__ == "__main__":
    main()
