"""Определить язык озвучки роликов. Библиотека — только русскоязычная.

ЗАЧЕМ. Аудитория продукта русскоязычная, и ролик с украинской озвучкой в
платной библиотеке — не находка, а проблема: его отдадут человеку, который его
не поймёт. Поэтому язык у ролика надо знать до того, как он попадёт в разметку.

ПОЧЕМУ ПО ЗВУКУ, А НЕ ПО РАСШИФРОВКЕ. Расшифровки сделаны с `language="ru"`, и
в этом режиме Whisper не отказывается от украинской речи — он подгоняет её под
русский на слух: «швидкість» становится «швидкость», «ціль» — «циньи». Текст
получается русскими буквами при любом исходном языке, и определять по нему
язык значит гарантированно отвечать «русский». Единственный честный источник
здесь — сама дорожка.

ЧТО НА ВЫХОДЕ. `<выгрузка>/languages.tsv`: файл, язык, уверенность. Файл
дозаписывается, уже определённое не пересчитывается.

РОЛИКИ БЕЗ РЕЧИ НЕ ТРОГАЮТСЯ. Их в библиотеке не будет по отдельному решению,
а определять язык тишины бессмысленно — модель вернёт случайную догадку с
высокой уверенностью, и эта догадка потом будет выглядеть как факт.

    python tools/detect_speech_language.py "C:/Users/.../ChatExport_2026-09-28"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

VIDEO_DIR = "video_files"
TRANSCRIPTS = "transcripts"
LANGUAGES = "languages.tsv"

WHISPER_MODEL = "small"

#: Сколько кусков дорожки слушать. Один — это первые секунды, а ролик часто
#: начинается с приветствия на одном языке и продолжается на другом; по одному
#: куску такой ролик уедет не в ту сторону целиком.
DETECTION_SEGMENTS = 4


def need(module: str, package: str) -> None:
    """Проверить, что модуль есть, и сказать словами, если нет.

    Проверяется именно тот путь импорта, который понадобится дальше: бывают
    сборки, где пакет стоит, а `faster_whisper.audio` в нём нет, — и тогда
    человек увидел бы трассировку вместо строчки «установите вот это».
    """
    try:
        __import__(module)
    except ImportError:
        sys.exit(f"Нет модуля {module}. Установите:\n    pip install {package}")


def spoken_clips(export: Path) -> list[Path]:
    """Ролики, в которых есть распознанная речь.

    Пустая расшифровка означает тишину — такой ролик пропускается: язык у
    тишины не определяется, а выдуманный ответ хуже отсутствующего.
    """
    folder = export / TRANSCRIPTS
    if not folder.is_dir():
        sys.exit(f"Нет {folder} — сначала расшифровка (tools/transcribe_channel.py)")

    clips: list[Path] = []
    for transcript in sorted(folder.glob("*.txt")):
        if not transcript.read_text(encoding="utf-8").strip():
            continue
        video = export / VIDEO_DIR / transcript.stem
        if video.is_file():
            clips.append(video)
    return clips


def read_known(target: Path) -> dict[str, tuple[str, float]]:
    """Уже определённое. Заголовок пропускается, битые строки — тоже."""
    if not target.is_file():
        return {}
    known: dict[str, tuple[str, float]] = {}
    for line in target.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            known[parts[0]] = (parts[1], float(parts[2]))
        except ValueError:
            continue
    return known


def write_known(target: Path, known: dict[str, tuple[str, float]]) -> None:
    """Переписать файл целиком — но так, чтобы обрыв не застал его полупустым.

    Файл перезаписывается после КАЖДОГО ролика и содержит все предыдущие, а не
    только новый. Прямая запись тут опаснее, чем выглядит: убитый посреди неё
    процесс оставляет файл обрезанным, и обрыв стоит не одного ролика, а всех
    часов прохода — ровно того, от чего запись на каждом шаге и защищает.

    Поэтому пишем рядом и переставляем имя: `os.replace` в пределах одной папки
    атомарен, и файл под нужным именем либо старый целиком, либо новый целиком.
    """
    rows = ["\t".join(("file", "language", "probability"))]
    rows.extend(
        f"{name}\t{language}\t{probability:.3f}"
        for name, (language, probability) in sorted(known.items())
    )
    draft = target.with_name(target.name + ".tmp")
    draft.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.replace(draft, target)


def detect(export: Path, model_name: str) -> dict[str, tuple[str, float]]:
    need("faster_whisper", "faster-whisper")
    need("faster_whisper.audio", "faster-whisper")
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    target = export / LANGUAGES
    known = read_known(target)
    clips = spoken_clips(export)
    pending = [clip for clip in clips if clip.name not in known]
    if not pending:
        print(f"Все {len(clips)} роликов с речью уже определены — в {target}")
        return known

    print(f"Определяю язык у {len(pending)} из {len(clips)}; модель {model_name}", flush=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    for index, clip in enumerate(pending, 1):
        try:
            audio = decode_audio(str(clip), sampling_rate=16000)
            language, probability, _ = model.detect_language(
                audio=audio,
                vad_filter=True,
                language_detection_segments=DETECTION_SEGMENTS,
            )
        except Exception as error:  # noqa: BLE001 — один ролик не отменяет проход
            print(f"[{index}/{len(pending)}] {clip.name}: ОШИБКА {error}", flush=True)
            continue
        known[clip.name] = (language, probability)
        # Пишем на каждом шаге: проход длинный, и обрыв не должен стоить всего.
        write_known(target, known)
        print(f"[{index}/{len(pending)}] {clip.name}: {language} ({probability:.0%})", flush=True)

    return known


def report(known: dict[str, tuple[str, float]]) -> None:
    counts: dict[str, int] = {}
    for language, _ in known.values():
        counts[language] = counts.get(language, 0) + 1
    print("\nЯзыки:")
    for language, count in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"  {language}: {count}")

    # Невысокая уверенность на русском обычно означает смешанную речь, а не
    # ошибку: такой ролик стоит послушать, прежде чем отдавать подписчику.
    doubtful = sorted(
        (name for name, (language, p) in known.items() if language == "ru" and p < 0.8)
    )
    if doubtful:
        print(f"\nРусские, но неуверенно ({len(doubtful)}) — послушайте перед заливкой:")
        for name in doubtful:
            print(f"  {name} ({known[name][1]:.0%})")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Определить язык озвучки роликов выгрузки")
    parser.add_argument("export", type=Path, help="папка выгрузки (та, где messages.html)")
    parser.add_argument("--model", default=WHISPER_MODEL, help=f"модель (по умолчанию {WHISPER_MODEL})")
    args = parser.parse_args()

    export = args.export.expanduser()
    if not export.is_dir():
        sys.exit(f"Нет папки {export}")
    report(detect(export, args.model))


if __name__ == "__main__":
    main()
