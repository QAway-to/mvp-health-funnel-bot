"""Ролики из TikTok: скачать, расшифровать, разметить, подготовить к заливке.

Это про СВОИ ролики — те, что автор сам выложил в TikTok. Они уже публичные,
на них его водяной знак, и в боте они работают бесплатной частью: бот
прикрепляет такой ролик к своему ответу, когда тег совпал с тем, о чём идёт
разговор. Человек читает текст и тут же видит, что за ним живой автор.

ЧТО ДЕЛАЕТ

    ссылки.txt → mp4 → расшифровка → теги → captions.txt → черновик базы знаний

Дальше заливка отдельным шагом — `tools/upload_clips.py`, у него free по
умолчанию. Разделено намеренно: скачать и расшифровать можно когда угодно,
а заливка пишет в канал, и запускать её случайно не нужно.

ЧЕГО НЕ ДЕЛАЕТ

Не кладёт расшифровку в базу знаний сама. Whisper ошибается в терминах, а
здесь речь про здоровье: неверно расслышанное противопоказание бот повторит
уверенным голосом. Поэтому пишется черновик `kb-draft.md`, и перенос в
`prompts/kb/` — ручной, глазами.

ЗАПУСК

    pip install yt-dlp faster-whisper

    # в файле — по одной ссылке TikTok на строку
    python tools/tiktok_ingest.py ссылки.txt --out clips/

    # только расшифровать уже скачанное
    python tools/tiktok_ingest.py --out clips/ --skip-download

Повторный запуск ничего не переделывает: скачанное и расшифрованное
пропускается.

ПОТОМ

    python tools/upload_clips.py clips/ --dry-run
    python tools/upload_clips.py clips/
    # и переиндексация по номерам постов, которые он напечатает
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utils.content_library import tags_for_text  # noqa: E402

VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
TRANSCRIPTS = "transcripts"
CAPTIONS = "captions.txt"
KB_DRAFT = "kb-draft.md"
#: На CPU это единственный разумный размер: medium считает часами, а для
#: тегов и черновика точности small хватает.
WHISPER_MODEL = "small"


def need(module: str, package: str):
    try:
        return __import__(module)
    except ImportError:
        sys.exit(f"Нет модуля {module}. Установите:\n    pip install {package}")


def download(links_file: Path, out: Path) -> None:
    """Скачать ролики по ссылкам. Уже скачанные yt-dlp пропускает сам."""
    need("yt_dlp", "yt-dlp")
    from yt_dlp import YoutubeDL

    links = [
        line.strip()
        for line in links_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not links:
        sys.exit(f"В {links_file} нет ссылок")

    print(f"Скачиваю {len(links)} роликов в {out}", flush=True)
    options = {
        "outtmpl": str(out / "%(id)s.%(ext)s"),
        "format": "mp4/best",
        "quiet": True,
        "no_warnings": True,
        # Уже скачанное не перекачиваем: список ссылок обычно дописывают,
        # а не пересобирают с нуля.
        "download_archive": str(out / ".downloaded"),
    }
    with YoutubeDL(options) as ydl:
        ydl.download(links)


def transcribe(out: Path) -> dict[str, str]:
    """Расшифровать всё, что ещё не расшифровано. Возвращает текст по файлам."""
    need("faster_whisper", "faster-whisper")
    from faster_whisper import WhisperModel

    folder = out / TRANSCRIPTS
    folder.mkdir(parents=True, exist_ok=True)
    videos = sorted(p for p in out.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    if not videos:
        sys.exit(f"В {out} нет видео")

    texts: dict[str, str] = {}
    pending = [v for v in videos if not (folder / f"{v.stem}.txt").is_file()]
    model = None
    if pending:
        print(f"Расшифровываю {len(pending)} из {len(videos)} (модель {WHISPER_MODEL})", flush=True)
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    for index, video in enumerate(videos, 1):
        target = folder / f"{video.stem}.txt"
        if target.is_file():
            texts[video.name] = target.read_text(encoding="utf-8")
            continue
        segments, _ = model.transcribe(
            str(video), language="ru", vad_filter=True, beam_size=1,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        target.write_text(text, encoding="utf-8")
        texts[video.name] = text
        print(f"[{index}/{len(videos)}] {video.name}: {len(text)} знаков", flush=True)

    return texts


def title_from(text: str) -> str:
    """Первое предложение как заголовок — его всё равно править руками."""
    sentence = text.strip().split(".")[0].strip()
    return (sentence[:70].rstrip() + "…") if len(sentence) > 70 else (sentence or "Без названия")


def write_captions(out: Path, texts: dict[str, str]) -> int:
    """Разметка для заливки. Теги — тем же кодом, которым бот потом ищет.

    Совпадение здесь не случайность, а условие работы: ролик подбирается по
    пересечению тегов поста с тегами вопроса. Размечать другим словарём —
    значит класть в библиотеку то, что не найдётся.
    """
    target = out / CAPTIONS
    if target.is_file():
        print(f"{target} уже есть — не трогаю", flush=True)
        return 0

    lines, untagged = [], []
    for name in sorted(texts):
        tags = tags_for_text(texts[name])
        if not tags:
            untagged.append(name)
        marks = " ".join(f"#{t}" for t in tags) or "#БЕЗ_ТЕГОВ_ПОСТАВЬТЕ_РУКАМИ"
        lines.append(f"{name} | {marks} | {title_from(texts[name])}")

    target.write_text(
        "#! Проверьте теги и заголовки — они собраны машиной по расшифровке.\n"
        "#! Ролик без тегов попадёт в библиотеку и не подберётся никогда.\n"
        + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(f"\n{target}: строк {len(lines)}", flush=True)
    if untagged:
        print(f"БЕЗ ТЕГОВ ({len(untagged)}) — проставьте руками: {', '.join(untagged)}", flush=True)
    return len(lines)


def write_kb_draft(out: Path, texts: dict[str, str]) -> None:
    """Черновик для базы знаний — на глаза, а не в прод.

    Прямой путь «расшифровка → prompts/kb/» выглядит соблазнительно и здесь
    недопустим: тема — здоровье, а Whisper путает термины и дозировки. Один
    неверно расслышанный запрет бот повторит уверенным голосом, и это ровно
    тот случай, где выдуманный совет стоит здоровья.
    """
    target = out / KB_DRAFT
    body = [
        "# Черновик для базы знаний",
        "",
        "Собран машиной из расшифровок. **В `prompts/kb/` переносить руками.**",
        "",
        "Whisper ошибается в терминах, названиях и числах. В текстах про здоровье",
        "это не мелочь: неверная дозировка или потерянное «не» меняют смысл на",
        "противоположный, а бот повторит это уверенным голосом.",
        "",
        "Что проверять: числа, названия, противопоказания, отрицания.",
        "",
    ]
    for name in sorted(texts):
        tags = tags_for_text(texts[name])
        body += [
            f"## {name}",
            "",
            f"Теги: {', '.join(tags) or '—'}",
            "",
            texts[name] or "_расшифровка пустая — вероятно, ролик без речи_",
            "",
        ]
    target.write_text("\n".join(body), encoding="utf-8")
    print(f"{target}: черновик базы знаний", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Скачать ролики TikTok и подготовить к заливке")
    parser.add_argument("links", type=Path, nargs="?", help="файл со ссылками, по одной на строку")
    parser.add_argument("--out", type=Path, required=True, help="папка для роликов и разметки")
    parser.add_argument("--skip-download", action="store_true", help="только расшифровка уже скачанного")
    args = parser.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        if not args.links or not args.links.is_file():
            sys.exit("Нужен файл со ссылками, либо --skip-download")
        download(args.links, out)

    texts = transcribe(out)
    write_captions(out, texts)
    write_kb_draft(out, texts)

    print(
        "\nДальше:\n"
        f"  1. Проверьте {out / CAPTIONS} — теги и заголовки собраны машиной.\n"
        f"  2. python tools/upload_clips.py {out} --dry-run\n"
        f"  3. python tools/upload_clips.py {out}\n"
        "  4. Переиндексация по номерам постов, которые он напечатает.\n"
        f"  5. {out / KB_DRAFT} — перенесите в prompts/kb/ то, что проверили глазами.",
        flush=True,
    )


if __name__ == "__main__":
    main()
