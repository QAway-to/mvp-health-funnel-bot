"""Разметка по расшифровке не имеет права угадывать молча.

Инструмент читает выгрузку канала и предлагает подписи для роликов, у которых
их нет. Цена ошибки несимметрична, и отсюда всё остальное.

Пропустить пост, который и так размечен, — потерянное время. Переписать чужую
подпись — потерянная работа человека. Поэтому пост с тегами не трогается вовсе.

Предложить тег, которого бот не знает, — положить в библиотеку то, что не
найдётся никогда: ролик подбирается по пересечению тегов поста с тегами
вопроса. Поэтому теги считает `tags_for_text` — та самая функция, которой бот
разбирает вопрос покупателя, а не своя копия словаря.

И главное: там, где машине сказать нечего — ролик не расшифрован, в нём тишина
или словарь не узнал ни слова, — она обязана сказать «разметьте руками», а не
выдать пустую разметку, которая выглядит как готовая.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import channel_manifest  # noqa: E402
from utils.content_library import TIER_PREMIUM  # noqa: E402

pytest.importorskip("bs4", reason="разбор выгрузки требует beautifulsoup4")


def message(message_id: int, file: str, caption: str = "", forwarded: str = "") -> str:
    """Один пост с видео в том виде, в каком его пишет Telegram Desktop."""
    media = (
        f'<div class="media_wrap clearfix">'
        f'<a class="video_file_wrap clearfix pull_left" href="video_files/{file}">'
        f'<div class="video_duration">01:19</div>'
        f'<img class="video_file" src="video_files/{file}_thumb.jpg"/>'
        f"</a></div>"
    )
    # Переносы строк в подписи Telegram пишет как `<br>` — а от того, уцелеют
    # ли они, зависит, прочитается ли `tier: premium` как отдельная строка.
    text = f'<div class="text">{caption.replace(chr(10), "<br>")}</div>' if caption else ""
    body = media + text
    if forwarded:
        body = (
            f'<div class="forwarded body"><div class="from_name">{forwarded}'
            f'<span class="date details" title="12.09.2026"> 12.09.2026 16:47:52</span>'
            f"</div>{body}</div>"
        )
    return (
        f'<div class="message default clearfix" id="message{message_id}">'
        f'<div class="body">'
        f'<div class="pull_right date details" title="18.09.2026 11:36:36 UTC+04:00">11:36</div>'
        f"{body}</div></div>"
    )


@pytest.fixture
def export(tmp_path: Path) -> Path:
    (tmp_path / "video_files").mkdir()
    (tmp_path / channel_manifest.TRANSCRIPTS).mkdir()
    return tmp_path


def write_export(export: Path, *blocks: str) -> None:
    (export / "messages.html").write_text(
        f'<html><body class="page_body">{"".join(blocks)}</body></html>', encoding="utf-8"
    )


def transcript(export: Path, file: str, text: str) -> None:
    (export / channel_manifest.TRANSCRIPTS / f"{file}.txt").write_text(text, encoding="utf-8")


def draft_of(export: Path) -> str:
    return (export / channel_manifest.DRAFT).read_text(encoding="utf-8")


class TestReadPosts:
    def test_reads_id_file_and_duration(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV"))
        (post,) = channel_manifest.read_posts(export)
        assert (post.message_id, post.file, post.duration) == (42, "IMG_1.MOV", "01:19")

    def test_skips_posts_without_video(self, export: Path) -> None:
        plain = '<div class="message default clearfix" id="message7"><div class="body">привет</div></div>'
        write_export(export, plain, message(8, "IMG_1.MOV"))
        assert [p.message_id for p in channel_manifest.read_posts(export)] == [8]

    def test_forwarded_author_comes_without_the_date(self, export: Path) -> None:
        """Имя и дата лежат в одном узле, и наивный `.text` их склеивает."""
        write_export(export, message(42, "IMG_1.MOV", forwarded="Bogdan Borovskiy"))
        (post,) = channel_manifest.read_posts(export)
        assert post.forwarded_from == "Bogdan Borovskiy"

    def test_own_post_has_no_author(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV"))
        (post,) = channel_manifest.read_posts(export)
        assert post.forwarded_from == ""

    def test_export_without_messages_html_is_refused(self, export: Path) -> None:
        with pytest.raises(SystemExit):
            channel_manifest.read_posts(export)

    def test_caption_keeps_its_line_breaks(self, export: Path) -> None:
        """Telegram пишет переносы как `<br>`, а у `<br>` нет текста.

        Склеенная в одну строку подпись выглядит целой и читается неверно:
        формат построчный, и `tier` вне своей строки не опознаётся.
        """
        write_export(export, message(42, "IMG_1.MOV", caption="#бег\ntier: premium\nРазминка"))
        (post,) = channel_manifest.read_posts(export)
        assert post.caption.splitlines() == ["#бег", "tier: premium", "Разминка"]


class TestDraft:
    def test_tagged_post_is_left_alone(self, export: Path) -> None:
        """Чужая подпись дороже нашей догадки."""
        write_export(export, message(42, "IMG_1.MOV", caption="#закаливание Обливание"))
        transcript(export, "IMG_1.MOV", "Сегодня говорим о беге по снегу")
        _, ready, blind = channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert (ready, blind) == (0, 0)
        assert "42" not in draft_of(export)

    def test_speech_becomes_tags_the_bot_knows(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV"))
        transcript(export, "IMG_1.MOV", "Сегодня говорим о закаливании и обливании холодной водой")
        _, ready, blind = channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert (ready, blind) == (1, 0)
        assert "#закаливание" in draft_of(export)

    def test_speech_means_premium(self, export: Path) -> None:
        """Тиктоки залиты без дорожки, значит речь — это шаг курса."""
        write_export(export, message(42, "IMG_1.MOV"))
        transcript(export, "IMG_1.MOV", "Сегодня говорим о закаливании")
        channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert f"tier: {TIER_PREMIUM}" in draft_of(export)

    def test_silence_is_sent_to_a_human(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV"))
        transcript(export, "IMG_1.MOV", "")
        _, ready, blind = channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert (ready, blind) == (0, 1)
        # Именно «тишина»: причина, а не общий призыв, иначе перепутанные
        # местами сообщения двух разных веток тест бы не заметил.
        assert "тишина, РАЗМЕТИТЬ РУКАМИ" in draft_of(export)

    def test_unknown_words_are_sent_to_a_human(self, export: Path) -> None:
        """Речь есть, а словарь её не узнал — тегов нет, и выдумывать их нельзя."""
        write_export(export, message(42, "IMG_1.MOV"))
        transcript(export, "IMG_1.MOV", "Ну вот примерно так оно и бывает обычно")
        _, ready, blind = channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert (ready, blind) == (0, 1)
        assert "теги не подобрались, РАЗМЕТИТЬ РУКАМИ" in draft_of(export)

    def test_missing_transcript_is_named_as_such(self, export: Path) -> None:
        """«Не считали» и «посчитали, там тишина» — разные вещи."""
        write_export(export, message(42, "IMG_1.MOV"))
        _, ready, blind = channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert (ready, blind) == (0, 1)
        assert "НЕ РАСШИФРОВАН" in draft_of(export)

    def test_draft_warns_that_the_tier_is_a_guess(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV"))
        transcript(export, "IMG_1.MOV", "Сегодня говорим о закаливании")
        channel_manifest.write_draft(export, channel_manifest.read_posts(export))
        assert "ДОГАДКА" in draft_of(export)


class TestManifest:
    def test_row_per_post_plus_header(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV"), message(43, "IMG_2.MOV"))
        transcript(export, "IMG_1.MOV", "Сегодня говорим о закаливании")
        target = channel_manifest.write_manifest(export, channel_manifest.read_posts(export))
        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("message_id\t")

    def test_unread_transcript_is_a_dash_not_a_zero(self, export: Path) -> None:
        """Ноль знаков — это тишина, прочерк — что расшифровки нет вовсе."""
        write_export(export, message(42, "IMG_1.MOV"))
        target = channel_manifest.write_manifest(export, channel_manifest.read_posts(export))
        assert "\t—\t" in target.read_text(encoding="utf-8")

    def test_premium_post_is_not_recorded_as_free(self, export: Path) -> None:
        """Ошибка в эту сторону раздаёт платный товар, и она невидима глазом."""
        write_export(export, message(42, "IMG_1.MOV", caption="#бег\ntier: premium\nРазминка"))
        target = channel_manifest.write_manifest(export, channel_manifest.read_posts(export))
        row = target.read_text(encoding="utf-8").strip().split("\n")[1].split("\t")
        assert row[5] == TIER_PREMIUM
        assert row[7] == "Разминка"

    def test_existing_tags_survive_into_the_manifest(self, export: Path) -> None:
        write_export(export, message(42, "IMG_1.MOV", caption="#закаливание Обливание"))
        target = channel_manifest.write_manifest(export, channel_manifest.read_posts(export))
        assert "закаливание" in target.read_text(encoding="utf-8")


class TestTitle:
    def test_long_sentence_is_cut(self) -> None:
        title = channel_manifest.title_from("а" * 200)
        assert len(title) <= channel_manifest.TITLE_LIMIT + 1 and title.endswith("…")

    def test_empty_text_still_gets_a_name(self) -> None:
        assert channel_manifest.title_from("   ") == "Без названия"
