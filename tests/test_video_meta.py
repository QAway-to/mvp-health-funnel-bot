"""Метаданные ролика перед заливкой.

Ради чего всё: без явных `width`/`height`/`duration` Telegram записывает
крупный файл как `320x320` без длительности, и вертикальное видео у зрителя
растягивается. Исправить готовый пост нельзя — только перезалить, поэтому
проверяем здесь, а не в канале.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.video_meta import THUMB_SIDE, VideoMeta, _jpeg_size, probe  # noqa: E402


def _ffmpeg() -> str:
    imageio_ffmpeg = pytest.importorskip(
        "imageio_ffmpeg", reason="ffmpeg ставится только для заливки роликов"
    )
    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture(scope="module")
def portrait_clip(tmp_path_factory) -> Path:
    """Трёхсекундный вертикальный ролик 360x640 — форма, в которой снимают все."""
    target = tmp_path_factory.mktemp("clips") / "portrait.mp4"
    subprocess.run(
        [_ffmpeg(), "-y", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25:duration=3",
         "-pix_fmt", "yuv420p", str(target)],
        capture_output=True, check=True,
    )
    return target


# --- разбор заголовка JPEG ------------------------------------------------

def test_jpeg_size_reads_sof_header():
    # SOI, затем SOF0 длиной 17: точность, высота 640, ширина 360.
    data = b"\xff\xd8" + b"\xff\xc0\x00\x11\x08" + (640).to_bytes(2, "big") + (360).to_bytes(2, "big")
    assert _jpeg_size(data) == (360, 640)


def test_jpeg_size_skips_segments_before_sof():
    # APP0 длиной 16 идёт первым — его нужно перешагнуть, а не принять за размер.
    app0 = b"\xff\xe0\x00\x10" + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0\x00\x11\x08" + (100).to_bytes(2, "big") + (200).to_bytes(2, "big")
    assert _jpeg_size(b"\xff\xd8" + app0 + sof) == (200, 100)


def test_jpeg_size_survives_garbage():
    """Мусор не должен ронять заливку — вызывающий просто пойдёт без размеров."""
    assert _jpeg_size(b"\xff\xd8not a jpeg at all") == (0, 0)


def test_jpeg_size_steps_over_markers_without_length():
    """RST и TEM длины не несут. Приняв их за сегмент, разбор читал бы как
    длину чужие байты и улетал мимо настоящего SOF."""
    sof = b"\xff\xc0\x00\x11\x08" + (48).to_bytes(2, "big") + (64).to_bytes(2, "big")
    for standalone in (b"\xff\x01", b"\xff\xd0", b"\xff\xd7"):
        assert _jpeg_size(b"\xff\xd8" + standalone + sof) == (64, 48)


def test_jpeg_size_ignores_fill_bytes_before_a_marker():
    """0xFF перед маркером — разрешённая набивка, а не начало сегмента."""
    sof = b"\xff\xc0\x00\x11\x08" + (48).to_bytes(2, "big") + (64).to_bytes(2, "big")
    assert _jpeg_size(b"\xff\xd8" + b"\xff\xff\xff" + sof) == (64, 48)


# --- сам замер ------------------------------------------------------------

def test_probe_reports_real_portrait_shape(portrait_clip):
    meta = probe(portrait_clip, _ffmpeg())
    assert (meta.width, meta.height) == (360, 640)
    assert meta.is_usable


def test_probe_reads_duration(portrait_clip):
    assert probe(portrait_clip, _ffmpeg()).duration == 3


def test_probe_returns_thumbnail_within_telegram_limits(portrait_clip):
    meta = probe(portrait_clip, _ffmpeg())
    assert meta.thumbnail[:2] == b"\xff\xd8"      # это JPEG
    assert len(meta.thumbnail) < 200 * 1024        # предел Telegram
    assert max(_jpeg_size(meta.thumbnail)) == THUMB_SIDE


def test_probe_on_a_non_video_is_not_fatal(tmp_path):
    """Битый файл не должен ронять скрипт: ролик уйдёт без подсказок."""
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    meta = probe(broken, _ffmpeg())
    assert not meta.is_usable


def test_probe_survives_an_unlaunchable_ffmpeg(tmp_path):
    """Бинарник может не запуститься посреди пачки: путь протух, нет прав.

    Исключение отсюда обрывало бы заливку на середине и теряло прогресс по
    всем оставшимся роликам — а обещание модуля ровно обратное.
    """
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"whatever")
    meta = probe(clip, str(tmp_path / "нет-такого-ffmpeg.exe"))
    assert meta == VideoMeta(0, 0, 0, b"")


def test_unusable_meta_is_falsy_on_zero_sides():
    assert not VideoMeta(0, 0, 10, b"").is_usable
    assert not VideoMeta(360, 0, 10, b"").is_usable
    assert VideoMeta(360, 640, 10, b"").is_usable
