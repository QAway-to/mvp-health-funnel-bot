"""Разбор captions.txt — единственное место, где решается, что платное.

Ошибка здесь стоит дороже любой другой в этом скрипте: ступень попадает в
подпись поста, подпись читает бот, и платный ролик, уехавший свободным, уже
роздан. Поэтому строку с непонятной пометкой скрипт не пропускает, а
останавливается на всей пачке.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import upload_clips  # noqa: E402
from tools.upload_clips import Clip, read_clips  # noqa: E402
from tools.video_meta import VideoMeta  # noqa: E402


@pytest.fixture
def folder(tmp_path) -> Path:
    for name in ("a.mp4", "b.mp4"):
        (tmp_path / name).write_bytes(b"x")
    return tmp_path


def _write(folder: Path, *lines: str) -> None:
    (folder / "captions.txt").write_text("\n".join(lines), encoding="utf-8")


# --- ступень поштучно -----------------------------------------------------

def test_tier_flag_overrides_the_run_wide_one(folder):
    _write(folder, "a.mp4 | #зарядка | Вступление | free")
    assert read_clips(folder)[0].caption("premium").splitlines()[1] == "tier: free"


def test_without_a_flag_the_run_wide_tier_wins(folder):
    _write(folder, "a.mp4 | #зарядка | Вступление")
    assert read_clips(folder)[0].caption("premium").splitlines()[1] == "tier: premium"


def test_mute_and_tier_travel_together(folder):
    _write(folder, "a.mp4 | #зарядка | Разминка | mute, premium")
    clip = read_clips(folder)[0]
    assert clip.mute
    assert clip.tier == "premium"


def test_flag_order_and_case_do_not_matter(folder):
    _write(folder, "a.mp4 | #зарядка | Разминка | PREMIUM , Mute")
    clip = read_clips(folder)[0]
    assert (clip.mute, clip.tier) == (True, "premium")


def test_mute_alone_still_works(folder):
    """Строки, написанные до появления ступеней, обязаны читаться как раньше."""
    _write(folder, "a.mp4 | #зарядка | Разминка | mute")
    clip = read_clips(folder)[0]
    assert (clip.mute, clip.tier) == (True, "")


# --- на чём скрипт обязан остановиться -------------------------------------

def test_two_tiers_at_once_stop_the_run(folder):
    _write(folder, "a.mp4 | #зарядка | Разминка | free, premium")
    with pytest.raises(SystemExit):
        read_clips(folder)


def test_an_unknown_flag_stops_the_run(folder):
    """Опечатка в пометке не должна тихо превратиться в «ступень по умолчанию»."""
    _write(folder, "a.mp4 | #зарядка | Разминка | premum")
    with pytest.raises(SystemExit):
        read_clips(folder)


def test_a_typo_next_to_a_valid_flag_still_stops_the_run(folder):
    """Ровно та форма, которую принимает настоящая опечатка: одна пометка
    верная, вторая с ошибкой. Пропустить строку значит залить платный ролик
    свободным."""
    _write(folder, "a.mp4 | #зарядка | Разминка | mute, premiun")
    with pytest.raises(SystemExit):
        read_clips(folder)


def test_one_bad_line_stops_the_whole_batch(folder):
    """Залить половину пачки хуже, чем не залить ничего: разбирать, что уехало
    и с какой подписью, придётся вручную."""
    _write(folder, "a.mp4 | #зарядка | Хорошая строка | free", "b.mp4 | без тегов | Плохая")
    with pytest.raises(SystemExit):
        read_clips(folder)


def test_tier_does_not_leak_between_lines(folder):
    _write(folder, "a.mp4 | #зарядка | Первый | premium", "b.mp4 | #зарядка | Второй")
    first, second = read_clips(folder)
    assert (first.tier, second.tier) == ("premium", "")


def test_caption_shape_is_what_the_bot_parses(folder):
    """Подпись читает utils.content_library.parse_caption: теги первой строкой,
    ступень второй, название третьей."""
    _write(folder, "a.mp4 | #зарядка #долголетие | Разминка утром | premium")
    from utils.content_library import TIER_PREMIUM, parse_caption

    item = parse_caption(read_clips(folder)[0].caption("free"), 1)
    assert item.tags == ("зарядка", "долголетие")
    assert item.tier == TIER_PREMIUM
    assert item.title == "Разминка утром"


def test_clip_defaults_stay_backwards_compatible():
    assert Clip(Path("a.mp4"), "#тег", "Название").tier == ""


# --- пробный прогон -------------------------------------------------------
#
# Пробный прогон — единственная страховка между опечаткой и необратимой
# раздачей платного ролика. Пока он держался только на том, что строка печати
# текстуально совпадает с выражением внутри caption(): «упростить» печать до
# args.tier можно было, не уронив ни одного теста.


def _dry_run(folder: Path, monkeypatch, capsys, tier: str = "free") -> str:
    monkeypatch.setattr(
        sys, "argv", ["upload_clips.py", str(folder), "--tier", tier, "--dry-run"]
    )
    upload_clips.main()
    return capsys.readouterr().out


def test_dry_run_prints_the_tier_that_will_actually_be_uploaded(folder, monkeypatch, capsys):
    """--tier free, а у строки premium: если печать и подпись разойдутся,
    человек увидит «free» и одобрит раздачу платного ролика."""
    _write(folder, "a.mp4 | #зарядка | Разминка | premium")
    out = _dry_run(folder, monkeypatch, capsys, tier="free")
    assert "premium" in out.splitlines()[0]     # пометка в квадратных скобках
    assert "tier: premium" in out               # то, что уедет в подпись
    assert "tier: free" not in out


def test_dry_run_shows_the_run_wide_tier_when_the_line_is_silent(folder, monkeypatch, capsys):
    _write(folder, "a.mp4 | #зарядка | Разминка")
    out = _dry_run(folder, monkeypatch, capsys, tier="premium")
    assert "premium" in out.splitlines()[0]
    assert "tier: premium" in out


def test_dry_run_uploads_nothing(folder, monkeypatch, capsys):
    """Ошибка здесь дороже любой другой: пробный прогон, который что-то шлёт,
    хуже отсутствующего."""
    def explode(*args, **kwargs):
        raise AssertionError("пробный прогон обратился к сети")

    monkeypatch.setattr(upload_clips.requests, "post", explode)
    monkeypatch.setattr(upload_clips, "read_env", explode)
    _write(folder, "a.mp4 | #зарядка | Разминка | premium")
    _dry_run(folder, monkeypatch, capsys)


# --- то, что реально уходит в Telegram ------------------------------------


def test_the_resume_log_survives_a_cyrillic_filename(folder, monkeypatch, capsys):
    """Книжка залитого должна читаться обратно, и особенно — с кириллицей.

    Она пишется в utf-8, а `read_text()` без аргумента берёт кодировку
    системы: на Windows это не utf-8, и файл «закалка.mp4» ронял повторный
    запуск. Ломалось ровно там, где книжка и нужна — на продолжении после
    обрыва, посреди залитой наполовину пачки, — поэтому до первого обрыва
    никто этого не видел.
    """
    (folder / "закалка.mp4").write_bytes(b"x")
    sent: list[dict] = []

    class FakeResponse:
        def __init__(self, mid):
            self._mid = mid

        def json(self):
            return {"ok": True, "result": {"message_id": self._mid}}

    def fake_post(url, data=None, files=None, timeout=None):
        sent.append(data)
        return FakeResponse(100 + len(sent))

    monkeypatch.setattr(upload_clips, "read_env", lambda: ("token", "-100500"))
    monkeypatch.setattr(upload_clips.requests, "post", fake_post)
    monkeypatch.setattr(upload_clips, "probe", lambda *a, **k: VideoMeta(720, 1280, 30, b"\xff\xd8"))
    monkeypatch.setattr(upload_clips, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(upload_clips.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["upload_clips.py", str(folder)])
    _write(folder, "закалка.mp4 | #закаливание | Обливание | free")

    upload_clips.main()
    assert len(sent) == 1

    # Второй запуск: ролик уже залит, значит отправки быть не должно —
    # а раньше здесь падало на чтении книжки.
    upload_clips.main()
    assert len(sent) == 1, "ролик отправлен повторно — книжка залитого не прочиталась"


def test_the_uploaded_caption_carries_the_per_file_tier(folder, monkeypatch, capsys):
    """Проверяем поле caption в самом запросе, а не только caption()."""
    sent: list[dict] = []

    class FakeResponse:
        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 1}}

    def fake_post(url, data=None, files=None, timeout=None):
        sent.append(data)
        return FakeResponse()

    monkeypatch.setattr(upload_clips, "read_env", lambda: ("token", "-100500"))
    monkeypatch.setattr(upload_clips.requests, "post", fake_post)
    monkeypatch.setattr(upload_clips, "probe", lambda *a, **k: VideoMeta(720, 1280, 30, b"\xff\xd8"))
    monkeypatch.setattr(upload_clips, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(upload_clips.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["upload_clips.py", str(folder), "--tier", "free"])

    _write(folder, "a.mp4 | #зарядка | Разминка | premium", "b.mp4 | #снег | Снег")
    upload_clips.main()

    assert [d["caption"].splitlines()[1] for d in sent] == ["tier: premium", "tier: free"]
    assert sent[0]["width"] == 720 and sent[0]["height"] == 1280
