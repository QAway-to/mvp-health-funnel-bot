"""Правка подписей живого канала не имеет права делать лишнего.

Канал один, он боевой, и прежней подписи не хранит ни Telegram, ни мы. Отсюда
всё, что проверяется здесь.

Без `--apply` не отправляется ничего. Флаг пишется руками, и это единственное,
что отделяет просмотр от правки.

Прежняя подпись снимается ДО правки и пишется в журнал. Не вышло снять — пост
не правится вовсе: необратимая правка без снимка хуже неразмеченного ролика,
потому что ролик размечают потом, а текст не восстанавливают никогда.

Подпись без тегов не отправляется никогда. Она не ломает формат — она хуже:
ролик с ней лежит в библиотеке и не подбирается никогда, потому что бот
подбирает по пересечению тегов поста с тегами вопроса. Проверяется результат
разбора тем же `parse_caption`, которым подпись потом читает бот, а не пометка
в черновике: файл правит человек, и верить надо тому, что получилось.

Испорченный черновик останавливает весь проход, а не фильтруется. Задвоенный
пост, подпись длиннее предела Telegram или нечитаемый номер в заголовке — это
ошибка человека в его файле; догадываться за него нельзя, а молча проглотить
блок нельзя тем более.

Flood limit — не отказ. Это «подожди столько», и записать его отказом значит
оставить библиотеку разнородной там, где пост правится прекрасно. Пережидается
он у каждого вызова, потому что их на пост три. Но не бесконечно: без предела
проход встаёт на одном посте и держит всю очередь.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, RetryAfter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import apply_captions  # noqa: E402

READY = """#! шапка черновика
#! вторая строка шапки

# пост 442 — IMG_1.MOV (01:19)
#закаливание #снег
tier: premium
Как заходить в холод

# пост 443 — IMG_2.MOV (00:44): тишина, РАЗМЕТИТЬ РУКАМИ

# пост 444 — IMG_3.MOV (02:01)
#бег
tier: free
Разминка
"""

REFUSED = "message can" + chr(39) + "t be edited"


@pytest.fixture
def draft(tmp_path: Path) -> Path:
    target = tmp_path / "captions_draft.txt"
    target.write_text(READY, encoding="utf-8")
    return target


@pytest.fixture
def journal(tmp_path: Path) -> Path:
    return apply_captions.journal_path(tmp_path / "captions_draft.txt")


class FakeBot:
    """Канал, который отдаёт подписи пересылкой и жалуется на чужие посты."""

    def __init__(
        self,
        refuse: set[int] | None = None,
        hidden: set[int] | None = None,
        flood: dict[int, int] | None = None,
        flood_forward: dict[int, int] | None = None,
    ) -> None:
        self.edited: dict[int, str] = {}
        self.forwarded: list[int] = []
        self.deleted: list[int] = []
        #: Что сейчас стоит в канале. 444 без подписи — так тоже бывает.
        self.captions: dict[int, str | None] = {442: "старая подпись 442", 444: None}
        self._refuse = refuse or set()
        self._hidden = hidden or set()
        self._flood = dict(flood or {})
        self._flood_forward = dict(flood_forward or {})

    async def forward_message(self, chat_id: str, from_chat_id: str, message_id: int):
        left = self._flood_forward.get(message_id, 0)
        if left:
            self._flood_forward[message_id] = left - 1
            raise RetryAfter(0)
        if message_id in self._hidden:
            raise BadRequest("message to forward not found")
        self.forwarded.append(message_id)
        return SimpleNamespace(
            message_id=9000 + message_id, caption=self.captions.get(message_id)
        )

    async def delete_message(self, chat_id: str, message_id: int) -> None:
        self.deleted.append(message_id)

    async def edit_message_caption(self, chat_id: str, message_id: int, caption: str) -> None:
        left = self._flood.get(message_id, 0)
        if left:
            self._flood[message_id] = left - 1
            raise RetryAfter(0)
        if message_id in self._refuse:
            raise BadRequest(REFUSED)
        self.edited[message_id] = caption


def run_apply(bot: FakeBot, captions: list, journal: Path) -> list[str]:
    return asyncio.run(
        apply_captions.apply(bot, "@channel", captions, journal, "@admin", pause=0)
    )


def draft_of(*captions: apply_captions.Caption, broken: list[str] | None = None):
    return apply_captions.Draft(ready=list(captions), skipped=[], broken=broken or [])


class TestReadDraft:
    def test_reads_only_blocks_that_parse_into_tags(self, draft: Path) -> None:
        parsed = apply_captions.read_draft(draft)
        assert [c.message_id for c in parsed.ready] == [442, 444]
        assert parsed.skipped == [443]
        assert parsed.broken == []

    def test_keeps_the_caption_line_structure(self, draft: Path) -> None:
        """Формат построчный: склеенный `tier:` перестаёт быть ступенью."""
        parsed = apply_captions.read_draft(draft)
        assert parsed.ready[0].text.splitlines() == [
            "#закаливание #снег",
            "tier: premium",
            "Как заходить в холод",
        ]

    def test_header_comments_never_reach_the_caption(self, draft: Path) -> None:
        parsed = apply_captions.read_draft(draft)
        assert all("шапка" not in c.text for c in parsed.ready)

    def test_hand_written_block_without_tags_is_skipped(self, tmp_path: Path) -> None:
        """Человек стёр теги, оставив заголовок, — отправлять такое нельзя."""
        target = tmp_path / "d.txt"
        target.write_text(
            "# пост 7 — IMG_9.MOV (00:10)\ntier: free\nПросто заголовок\n", encoding="utf-8"
        )
        parsed = apply_captions.read_draft(target)
        assert (parsed.ready, parsed.skipped) == ([], [7])

    def test_unreadable_post_number_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        """Опечатка в номере съедает блок до следующего заголовка — молча нельзя.

        Такой пост не попал бы ни в «готово», ни в «пропущено»: в отчёте его не
        было бы вовсе, и человек решил бы, что разметил его.
        """
        target = tmp_path / "d.txt"
        target.write_text(
            "# пост 44a — a.MOV\n#бег\nПервый\n\n# пост 45 — b.MOV\n#снег\nВторой\n",
            encoding="utf-8",
        )
        parsed = apply_captions.read_draft(target)

        assert [c.message_id for c in parsed.ready] == [45]
        assert len(parsed.broken) == 1 and "44a" in parsed.broken[0]

    def test_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            apply_captions.read_draft(tmp_path / "нет.txt")

    def test_wrong_encoding_is_explained_not_traced(self, tmp_path: Path) -> None:
        """Черновик, сохранённый редактором в cp1251, — ошибка человека."""
        target = tmp_path / "d.txt"
        target.write_bytes("# пост 7 — a.MOV\n#бег\nЗаголовок\n".encode("cp1251"))

        with pytest.raises(SystemExit) as stop:
            apply_captions.read_draft(target)

        assert "UTF-8" in str(stop.value)


class TestCheck:
    def test_duplicate_post_is_a_problem(self) -> None:
        twice = draft_of(
            apply_captions.Caption(442, "a.MOV", "#бег"),
            apply_captions.Caption(442, "b.MOV", "#снег"),
        )
        assert any("дважды" in p for p in apply_captions.check(twice))

    def test_caption_over_the_telegram_limit_is_a_problem(self) -> None:
        long = apply_captions.Caption(442, "a.MOV", "#бег\n" + "я" * apply_captions.CAPTION_LIMIT)
        assert any("символов" in p for p in apply_captions.check(draft_of(long)))

    def test_emoji_count_as_telegram_counts_them(self) -> None:
        """Эмодзи вне basic plane занимают в Telegram две единицы, а в len() одну.

        Подпись у предела прошла бы проверку и упёрлась в отказ уже на живом
        канале — то есть проверка сработала бы наоборот.
        """
        half = apply_captions.CAPTION_LIMIT // 2
        emoji = apply_captions.Caption(442, "a.MOV", "#бег\n" + "🏃" * half)

        assert apply_captions.telegram_length("🏃") == 2
        assert any("символов" in p for p in apply_captions.check(draft_of(emoji)))

    def test_unreadable_header_is_a_problem(self) -> None:
        assert any(
            "не читается" in p
            for p in apply_captions.check(draft_of(broken=["# пост 44a — a.MOV"]))
        )

    def test_clean_draft_has_no_problems(self, draft: Path) -> None:
        assert apply_captions.check(apply_captions.read_draft(draft)) == []


class TestApply:
    def test_sends_every_caption(self, draft: Path, journal: Path) -> None:
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot()

        assert run_apply(bot, parsed.ready, journal) == []
        assert set(bot.edited) == {442, 444}

    def test_the_previous_caption_is_written_before_the_edit(
        self, draft: Path, journal: Path
    ) -> None:
        """Снимок прежней подписи — единственное, чем правку можно откатить."""
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot()

        run_apply(bot, parsed.ready, journal)

        lines = journal.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "442\tстарая подпись 442"
        # Пустая подпись пишется словом: иначе «подписи не было» и «журнал
        # недописан» выглядят в файле одинаково.
        assert lines[1] == "444\tБЕЗ ПОДПИСИ"
        assert bot.forwarded == [442, 444]
        # Пересылка удаляется, иначе служебный чат заполняется мусором.
        assert bot.deleted == [9442, 9444]

    def test_a_post_whose_caption_cannot_be_read_is_not_touched(
        self, draft: Path, journal: Path
    ) -> None:
        """Правка без снимка необратима — значит не правим вовсе."""
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(hidden={442})

        failures = run_apply(bot, parsed.ready, journal)

        assert 442 not in bot.edited
        assert set(bot.edited) == {444}
        assert len(failures) == 1 and "не снять" in failures[0]

    def test_nothing_is_journalled_for_a_post_left_alone(
        self, draft: Path, journal: Path
    ) -> None:
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(hidden={442})

        run_apply(bot, parsed.ready, journal)

        assert "442\t" not in journal.read_text(encoding="utf-8")

    def test_flood_limit_is_waited_out_not_recorded_as_a_refusal(
        self, draft: Path, journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """«Подожди столько» — не отказ: пост правится, просто не сейчас."""
        monkeypatch.setattr(apply_captions, "RETRY_MARGIN", 0)
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(flood={442: 2})

        failures = run_apply(bot, parsed.ready, journal)

        assert failures == []
        assert set(bot.edited) == {442, 444}

    def test_flood_limit_on_the_snapshot_is_waited_out_too(
        self, draft: Path, journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """На пост три вызова, и flood limit на первом из них — тоже не отказ.

        Иначе выходит «прежнюю подпись не снять» там, где её снимут через
        минуту, — и пост остаётся неразмеченным на ровном месте.
        """
        monkeypatch.setattr(apply_captions, "RETRY_MARGIN", 0)
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(flood_forward={442: 2})

        failures = run_apply(bot, parsed.ready, journal)

        assert failures == []
        assert set(bot.edited) == {442, 444}

    def test_endless_flood_gives_up_instead_of_holding_the_queue(
        self, draft: Path, journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Предел попыток обязателен: иначе один пост держит всю очередь.

        Отличить «подожди ещё» от «так будет всегда» изнутри нельзя, поэтому
        пост уходит в отказы — его добирают дозапуском, когда лимит отпустит.
        Остальные посты при этом доходят.
        """
        monkeypatch.setattr(apply_captions, "RETRY_MARGIN", 0)
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(flood={442: apply_captions.RETRY_LIMIT + 1})

        failures = run_apply(bot, parsed.ready, journal)

        assert len(failures) == 1 and "442" in failures[0]
        assert set(bot.edited) == {444}

    def test_endless_flood_on_the_snapshot_also_gives_up(
        self, draft: Path, journal: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(apply_captions, "RETRY_MARGIN", 0)
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(flood_forward={442: apply_captions.RETRY_LIMIT + 1})

        failures = run_apply(bot, parsed.ready, journal)

        assert 442 not in bot.edited
        assert len(failures) == 1 and "не снять" in failures[0]

    def test_refusal_does_not_stop_the_rest(self, draft: Path, journal: Path) -> None:
        """Пост, который бот не отправлял, он править не может — но остальные может."""
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot(refuse={442})

        failures = run_apply(bot, parsed.ready, journal)

        assert len(failures) == 1 and "442" in failures[0]
        assert set(bot.edited) == {444}

    def test_skipped_posts_are_never_sent(self, draft: Path, journal: Path) -> None:
        parsed = apply_captions.read_draft(draft)
        bot = FakeBot()

        run_apply(bot, parsed.ready, journal)

        assert 443 not in bot.edited


class TestSelect:
    def test_narrows_to_one_post(self, draft: Path) -> None:
        ready = apply_captions.read_draft(draft).ready
        assert [c.message_id for c in apply_captions.select(ready, 442)] == [442]

    def test_no_filter_keeps_everything(self, draft: Path) -> None:
        ready = apply_captions.read_draft(draft).ready
        assert apply_captions.select(ready, None) == ready

    def test_unknown_post_is_refused_not_silently_empty(self, draft: Path) -> None:
        """Опечатка в номере иначе выглядит как «правка не проходит»."""
        ready = apply_captions.read_draft(draft).ready
        with pytest.raises(SystemExit):
            apply_captions.select(ready, 999)


class TestRun:
    def test_without_apply_nothing_is_sent(self, draft: Path, monkeypatch) -> None:
        """Единственное, что отделяет просмотр от правки, — флаг руками."""
        monkeypatch.setattr(apply_captions.config, "CONTENT_CHANNEL_ID", "@channel")
        monkeypatch.setattr(
            apply_captions, "apply", lambda *a, **k: pytest.fail("вхолостую ничего не шлём")
        )
        assert asyncio.run(apply_captions.run(draft, only=None, do_apply=False)) == 0

    def test_without_apply_no_journal_appears(self, draft: Path, monkeypatch) -> None:
        monkeypatch.setattr(apply_captions.config, "CONTENT_CHANNEL_ID", "@channel")
        asyncio.run(apply_captions.run(draft, only=None, do_apply=False))
        assert not apply_captions.journal_path(draft).exists()

    def test_broken_draft_stops_everything(self, tmp_path: Path, monkeypatch) -> None:
        target = tmp_path / "d.txt"
        target.write_text(
            "# пост 7 — a.MOV\n#бег\nОдин\n\n# пост 7 — b.MOV\n#снег\nДва\n", encoding="utf-8"
        )
        monkeypatch.setattr(apply_captions.config, "CONTENT_CHANNEL_ID", "@channel")
        monkeypatch.setattr(
            apply_captions,
            "apply",
            lambda *a, **k: pytest.fail("испорченный черновик не применяем"),
        )
        assert asyncio.run(apply_captions.run(target, only=None, do_apply=True)) == 1

    def test_unreadable_header_stops_everything_even_with_only(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Невнимательно правленный файл чинят весь, а не обходят по одному посту."""
        target = tmp_path / "d.txt"
        target.write_text(
            "# пост 44a — a.MOV\n#бег\nОдин\n\n# пост 45 — b.MOV\n#снег\nДва\n", encoding="utf-8"
        )
        monkeypatch.setattr(apply_captions.config, "CONTENT_CHANNEL_ID", "@channel")
        monkeypatch.setattr(
            apply_captions, "apply", lambda *a, **k: pytest.fail("битый черновик не применяем")
        )
        assert asyncio.run(apply_captions.run(target, only=45, do_apply=True)) == 1

    def test_missing_channel_is_refused(self, draft: Path, monkeypatch) -> None:
        monkeypatch.setattr(apply_captions.config, "CONTENT_CHANNEL_ID", "")
        with pytest.raises(SystemExit):
            asyncio.run(apply_captions.run(draft, only=None, do_apply=False))

    def test_missing_service_chat_is_refused(self, draft: Path, monkeypatch) -> None:
        """Без служебного чата прежнюю подпись не снять, а правка необратима."""
        monkeypatch.setattr(apply_captions.config, "CONTENT_CHANNEL_ID", "@channel")
        monkeypatch.setattr(apply_captions.config, "TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setattr(apply_captions.config, "ADMIN_CHAT_ID", "")
        monkeypatch.setattr(
            apply_captions, "apply", lambda *a, **k: pytest.fail("без снимка не правим")
        )

        with pytest.raises(SystemExit) as stop:
            asyncio.run(apply_captions.run(draft, only=None, do_apply=True))

        assert "ADMIN_CHAT_ID" in str(stop.value)
