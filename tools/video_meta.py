"""Размеры, длительность и кадр-превью ролика — то, без чего Telegram портит видео.

ЗАЧЕМ. `sendVideo` разрешает не передавать `width`/`height`/`duration`, и
Telegram пытается прочитать их сам. На файлах примерно до 10 МБ это работает,
на больших — нет: ролик ложится в библиотеку как `320x320`, длительность 0,
без превью. Вертикальное видео 9:16 клиент потом растягивает в квадрат — на
iPhone это видно особенно хорошо. Так в канале оказались 22 ролика из 49,
включая 14 из 15 платных.

ПОЧЕМУ ЧЕРЕЗ КАДР, А НЕ ЧЕРЕЗ РАЗБОР ЛОГА. Размеры можно вытащить из вывода
`ffmpeg -i`, но у снятого на телефон видео в контейнере лежит горизонтальный
кадр плюс матрица поворота, и строка `Stream` показывает именно его. Отдать
такие размеры Telegram — тот же растянутый ролик, только теперь по нашей вине.
Декодер поворот применяет, поэтому снятый кадр всегда в том виде, в каком
ролик реально показывается: его размеры и есть ответ.

Превью берётся тем же кадром: Telegram принимает JPEG до 320 px по стороне и
до 200 КБ.

`ffprobe` здесь не используется намеренно — `imageio-ffmpeg` привозит только
`ffmpeg`, и требовать отдельную установку ради одной цифры не стоит.
"""

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Сторона превью по Telegram. Больше — картинка молча отбрасывается.
THUMB_SIDE = 320

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


@dataclass(frozen=True)
class VideoMeta:
    width: int
    height: int
    duration: int
    thumbnail: bytes

    @property
    def is_usable(self) -> bool:
        """Есть ли что отдавать Telegram. Нули он всё равно проигнорирует."""
        return self.width > 0 and self.height > 0


def _run(ffmpeg: str, args: list[str]) -> "subprocess.CompletedProcess[bytes] | None":
    """Запуск ffmpeg. Не удалось запустить вовсе — None, а не исключение.

    Ненулевой код возврата тут ни при чём, его вызывающие и так проверяют по
    наличию файла. Речь о том, что сам бинарник может не запуститься посреди
    пачки: путь от imageio-ffmpeg протух, нет прав, кончились дескрипторы.
    Исключение отсюда обрывало бы всю заливку на середине — ровно то, чего
    этот модуль обещает не делать.
    """
    try:
        return subprocess.run([ffmpeg, *args], capture_output=True)
    except OSError:
        return None


def _duration_seconds(ffmpeg: str, path: Path) -> int:
    """Длительность из служебного вывода ffmpeg. Не прочиталась — 0."""
    # Без выходного файла ffmpeg завершается ошибкой, напечатав всё, что нужно.
    result = _run(ffmpeg, ["-i", str(path)])
    if result is None:
        return 0
    match = _DURATION_RE.search(result.stderr.decode(errors="replace"))
    if not match:
        return 0
    hours, minutes, seconds = match.groups()
    return int(int(hours) * 3600 + int(minutes) * 60 + float(seconds))


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Размеры JPEG из заголовка SOF. Своим разбором, без Pillow.

    Читать пришлось бы всё равно: ставить Pillow ради двух чисел в скрипте,
    который запускают на чужой машине с папкой роликов, — лишнее условие.
    """
    i = 2  # пропускаем SOI
    # `<=`, а не `<`: в SOF ровно девять байт после маркера, и на файле, где
    # за ним ничего не следует, строгое сравнение пропускало последний — то
    # есть единственный — заголовок.
    while i + 9 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # 0xFF перед маркером — разрешённая набивка, а не начало сегмента.
        if marker == 0xFF:
            i += 1
            continue
        # Маркеры без длины: RST0..RST7, TEM, SOI, EOI. Если принять их за
        # сегмент, следующие два байта прочитаются как длина — и разбор
        # улетит мимо настоящего SOF.
        if marker in (0x01, 0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        # SOF0..SOF15, кроме DHT (C4), JPG (C8) и DAC (CC) — они не про размер.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return width, height
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            break
        i += 2 + length
    return 0, 0


def probe(path: Path, ffmpeg: str) -> VideoMeta:
    """Размеры, длительность и превью. Ничего не вышло — нули и пустой кадр.

    Провал здесь не должен ронять заливку: ролик уйдёт как раньше, просто без
    подсказок Telegram — то есть не хуже, чем было.
    """
    duration = _duration_seconds(ffmpeg, path)
    # Первый кадр у снятого на телефон видео часто чёрный: камера ещё не
    # выставила экспозицию. Секунда внутрь — уже картинка.
    seek = "1" if duration > 2 else "0"

    with tempfile.TemporaryDirectory() as folder:
        full = Path(folder) / "full.jpg"
        thumb = Path(folder) / "thumb.jpg"
        _run(ffmpeg, ["-y", "-ss", seek, "-i", str(path), "-frames:v", "1", "-q:v", "2", str(full)])
        if not full.is_file():
            return VideoMeta(0, 0, duration, b"")

        width, height = _jpeg_size(full.read_bytes())

        # `-2` вместо `-1`: размер стороны обязан быть чётным, иначе кодек
        # отказывается масштабировать.
        scale = f"scale='if(gt(iw,ih),{THUMB_SIDE},-2)':'if(gt(iw,ih),-2,{THUMB_SIDE})'"
        _run(ffmpeg, ["-y", "-i", str(full), "-vf", scale, "-q:v", "5", str(thumb)])
        preview = thumb.read_bytes() if thumb.is_file() else b""

    return VideoMeta(width, height, duration, preview)


def ffmpeg_exe() -> str:
    """Путь к ffmpeg. Нет — понятная остановка вместо трассировки."""
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("Нужен ffmpeg:\n    pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()
