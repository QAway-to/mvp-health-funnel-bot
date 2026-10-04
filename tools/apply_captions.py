"""Проставить роликам канала подписи из черновика — правкой, не перезаливкой.

ПОЧЕМУ ПРАВКОЙ. Индекс бота собирается из подписей, а не из файлов: историю
канала Bot API не отдаёт, поэтому `reindex_range` пересылает каждый пост в
служебный чат, читает подпись и удаляет пересылку. Значит достаточно поправить
подпись и прогнать `/reindex` — файл остаётся на месте, `file_id` прежний,
`copy_message` работает как работал.

Перезаливка же дала бы новые номера постам, а старые остались бы в канале: те
самые байт-в-байт дубли, которых 28.09 вычистили шестьдесят штук. И вычистить
новые получилось бы не все — посты, которые бот не отправлял, он и удалить не
может. Перезаливка воспроизводит ровно ту проблему, ради которой всё затевалось.

ПО УМОЛЧАНИЮ НЕ ДЕЛАЕТСЯ НИЧЕГО. Канал живой и один; `--apply` пишется руками,
и до него инструмент только показывает, что собирается сделать. `--only`
ограничивает проход одним постом — с этого и стоит начинать, потому что право
бота править чужие посты проверяется не документацией, а попыткой: удалять
форварднутые человеком посты он, например, не может, хотя право на удаление
у него есть.

ПОДПИСЬ ПРОВЕРЯЕТСЯ ТЕМ ЖЕ КОДОМ, КОТОРЫМ ЕЁ ПОТОМ ЧИТАЕТ БОТ. Собранный текст
прогоняется через `parse_caption` перед отправкой, и если из него не вышло ни
одного тега — пост пропускается. Подпись без тегов не ошибка формата, она
хуже: ролик с ней лежит в библиотеке и не подбирается никогда.

ПРЕЖНЯЯ ПОДПИСЬ СНИМАЕТСЯ ДО ПРАВКИ И ПИШЕТСЯ РЯДОМ С ЧЕРНОВИКОМ
(`<черновик>.before_apply.tsv`). Правка необратима в буквальном смысле: старого
текста не хранит ни Telegram, ни мы, и «вернуть как было» после неё нечем.
Снимается тем же приёмом, которым живёт `/reindex` — пересылкой в служебный чат
(`ADMIN_CHAT_ID`) и удалением пересылки. Не вышло снять — пост не правится
вовсе: правка без снимка стоит дороже, чем неразмеченный ролик.

    python tools/apply_captions.py <выгрузка>/captions_draft.txt --only 442
    python tools/apply_captions.py <выгрузка>/captions_draft.txt --only 442 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import config  # noqa: E402
from utils.content_library import parse_caption  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover — импорт только для подсказки типа
    from telegram import Bot

#: Telegram режет подпись на 1024 символах. Резать её самим нельзя: обрезанный
#: хвост — это потерянный заголовок, а то и половина тегов.
CAPTION_LIMIT = 1024

#: Пауза между правками. Канал один, спешить некуда, а flood limit стоит
#: дороже: он обрывает проход на середине и оставляет библиотеку разнородной.
PAUSE = 0.5

#: Куда пишется прежняя подпись перед правкой — рядом с черновиком.
JOURNAL_SUFFIX = ".before_apply.tsv"

#: Сколько добавить к сроку, который назвал Telegram в ответе на flood limit.
#: Проснуться ровно в названную секунду значит попасть в тот же отказ снова.
RETRY_MARGIN = 1.0

#: Сколько раз пережидать flood limit на одном посте. Предел нужен: без него
#: проход встаёт на одном посте навсегда и держит всю очередь, а отличить
#: «подожди ещё» от «так будет всегда» изнутри нельзя. Исчерпали — пост уходит
#: в отказы, и его добирают дозапуском, когда лимит отпустит.
RETRY_LIMIT = 5


def journal_path(draft: Path) -> Path:
    return draft.with_name(draft.name + JOURNAL_SUFFIX)


def remember(journal: Path, message_id: int, caption: str | None) -> None:
    """Записать прежнюю подпись до того, как она перестанет существовать.

    Правка подписи необратима: Bot API не отдаёт историю канала, прежний текст
    нигде не хранится, и «откатить» его нечем — он просто исчезает. Поэтому
    журнал дозаписывается ПЕРЕД каждой правкой, а не после прохода: падение на
    середине не должно стоить тех строк, которые уже перезаписаны.

    Пустая подпись пишется явным словом, а не пустой строкой: отличить «подписи
    не было» от «журнал недописан» потом будет нечем.
    """
    text = "БЕЗ ПОДПИСИ" if caption is None else caption.replace("\t", " ").replace("\n", "\\n")
    with journal.open("a", encoding="utf-8") as file:
        file.write(f"{message_id}\t{text}\n")


@dataclass(frozen=True)
class Caption:
    """Готовая подпись для одного поста."""

    message_id: int
    file: str
    text: str


def is_comment(line: str) -> bool:
    """Комментарий, а не строка тегов.

    Различать приходится потому, что теги тоже начинаются с решётки:
    `#! шапка` и `# пост 442 — …` — комментарии, `#закаливание` — данные.
    Решётка с пробелом или восклицательным знаком после неё тегом быть не
    может, а без них — не может быть комментарием.
    """
    return line.startswith("#!") or line.startswith("# ")


@dataclass(frozen=True)
class Draft:
    """Разобранный черновик целиком.

    `broken` — заголовки, в которых не вышло прочитать номер поста. Отдельным
    списком, а не выброшенным молча: файл правит человек, опечатка в номере
    (`# пост 44a`) съела бы весь блок до следующего заголовка, и в отчёте
    «готово 50, пропущено 11» этого поста не было бы ни там, ни там.
    """

    ready: list[Caption]
    skipped: list[int]
    broken: list[str]


def read_draft(path: Path) -> Draft:
    """Разобрать черновик.

    Пропускается всё, из чего бот не вычитает ни одного тега, — в черновике
    такие блоки помечены «РАЗМЕТИТЬ РУКАМИ» и состоят из одного комментария,
    но проверяется не пометка, а результат разбора: человек правит этот файл
    руками, и доверять надо тому, что получилось, а не тому, что обещано.
    """
    if not path.is_file():
        sys.exit(f"Нет файла {path}")

    ready: list[Caption] = []
    skipped: list[int] = []
    broken: list[str] = []
    message_id: int | None = None
    file = ""
    body: list[str] = []

    def flush() -> None:
        nonlocal message_id, file, body
        if message_id is None:
            return
        text = "\n".join(body).strip()
        if text and parse_caption(text, message_id).tags:
            ready.append(Caption(message_id=message_id, file=file, text=text))
        else:
            skipped.append(message_id)
        message_id, file, body = None, "", []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        # Редактор мог сохранить черновик в cp1251 — это объяснимая ошибка
        # человека, и отвечать на неё надо словами, а не трассировкой.
        sys.exit(f"{path} читается не как UTF-8 — сохраните файл в UTF-8")

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# пост "):
            flush()
            head = line.removeprefix("# пост ").split("—")
            number = head[0].strip().split(":")[0].strip()
            if not number.isdigit():
                broken.append(line)
                continue
            message_id = int(number)
            file = head[1].strip().split("(")[0].strip() if len(head) > 1 else ""
            continue
        if is_comment(line) or not line:
            continue
        if message_id is not None:
            body.append(line)
    flush()

    return Draft(ready=ready, skipped=skipped, broken=broken)


def telegram_length(text: str) -> int:
    """Длина подписи так, как её считает Telegram — в кодовых единицах UTF-16.

    Эмодзи вне basic plane (🏃, 🔥) занимают там две единицы, а в `len()` одну.
    Подпись у предела с несколькими такими знаками прошла бы нашу проверку и
    упёрлась в отказ уже на живом канале — то есть проверка сделала бы ровно
    обратное тому, зачем она есть.
    """
    return len(text.encode("utf-16-le")) // 2


def check(draft: Draft) -> list[str]:
    """Что не так с черновиком до того, как его увидит Telegram."""
    problems: list[str] = []
    seen: set[int] = set()
    for line in draft.broken:
        problems.append(f"не читается номер поста в строке «{line}» — блок потерян целиком")
    for caption in draft.ready:
        if caption.message_id in seen:
            problems.append(f"пост {caption.message_id} встречается дважды")
        seen.add(caption.message_id)
        length = telegram_length(caption.text)
        if length > CAPTION_LIMIT:
            problems.append(
                f"пост {caption.message_id}: подпись {length} символов "
                f"при пределе {CAPTION_LIMIT} — сократите заголовок"
            )
    return problems


async def despite_flood(call, label: str):
    """Выполнить вызов, пережидая flood limit — но не бесконечно.

    Пережидать нужно у КАЖДОГО вызова, а не только у правки: на пост их теперь
    три (пересылка, удаление пересылки, правка), и flood limit на первом из них
    так же не отказ, как на последнем. Ловить его в одном месте значило бы
    записать «прежнюю подпись не снять» там, где её прекрасно снимут через
    минуту.

    Исчерпав попытки, отдаём последний отказ наружу — пусть его обработают как
    обычный, с именем поста и строкой в отчёте.
    """
    from telegram.error import RetryAfter

    for remaining in range(RETRY_LIMIT, -1, -1):
        try:
            return await call()
        except RetryAfter as error:
            if remaining == 0:
                raise
            wait = float(error.retry_after) + RETRY_MARGIN
            print(f"{label}: flood limit, ждём {wait:.0f} с (осталось попыток {remaining})",
                  flush=True)
            await asyncio.sleep(wait)


async def previous_caption(
    bot: "Bot", channel: str, via_chat: str, message_id: int, label: str = ""
) -> str | None:
    """Прежняя подпись поста. Пересылкой — другого способа Bot API не даёт.

    Пост пересылается в служебный чат, из ответа берётся подпись, пересылка
    удаляется. Тем же приёмом живёт `/reindex` в боте, и ради одного и того же:
    историю канала Bot API не отдаёт, а `forwardMessage` возвращает полный
    `Message`.
    """
    from telegram.error import TelegramError

    forwarded = await despite_flood(
        lambda: bot.forward_message(
            chat_id=via_chat, from_chat_id=channel, message_id=message_id
        ),
        label or f"пост {message_id}",
    )
    try:
        await bot.delete_message(chat_id=via_chat, message_id=forwarded.message_id)
    except TelegramError:
        # Пересылку не убрали — это мусор в служебном чате, а не причина
        # отказываться от снимка, который уже в руках. Пережидать flood limit
        # тут незачем по той же причине: ждать минуту ради уборки дороже самой
        # уборки, а снимок от этого не портится.
        pass
    return forwarded.caption


async def apply(
    bot: "Bot",
    channel: str,
    captions: list[Caption],
    journal: Path,
    via_chat: str,
    pause: float = PAUSE,
) -> list[str]:
    """Отправить подписи. Возвращает список отказов, по строке на пост.

    Перед каждой правкой прежняя подпись снимается и пишется в журнал. Не
    вышло снять — пост пропускается: правка без снимка необратима, а «почти
    получилось» здесь означает безвозвратно потерянный текст.
    """
    from telegram.error import TelegramError

    failures: list[str] = []
    for index, caption in enumerate(captions, 1):
        head = f"[{index}/{len(captions)}] пост {caption.message_id}"
        try:
            before = await previous_caption(bot, channel, via_chat, caption.message_id, head)
        except TelegramError as error:
            failures.append(
                f"пост {caption.message_id} ({caption.file}): прежнюю подпись не снять "
                f"({error}) — не правил"
            )
            print(f"{head}: ПРОПУЩЕН, прежнюю подпись не снять ({error})", flush=True)
            await asyncio.sleep(pause)
            continue
        remember(journal, caption.message_id, before)

        try:
            await despite_flood(
                lambda: bot.edit_message_caption(
                    chat_id=channel, message_id=caption.message_id, caption=caption.text
                ),
                head,
            )
            print(f"{head}: подписан", flush=True)
        except TelegramError as error:
            # Самый ожидаемый отказ здесь — пост, который бот не отправлял.
            # Право `can_edit_messages` этого не всегда перекрывает, ровно как
            # право на удаление не перекрыло форварднутые человеком посты.
            failures.append(f"пост {caption.message_id} ({caption.file}): {error}")
            print(f"{head}: ОТКАЗ {error}", flush=True)
        await asyncio.sleep(pause)
    return failures


def preview(captions: list[Caption], skipped: list[int], channel: str) -> None:
    print(f"Канал {channel}; подписей готово {len(captions)}, пропущено {len(skipped)}\n")
    for caption in captions:
        head = caption.text.splitlines()[0]
        print(f"  пост {caption.message_id} ({caption.file}): {head}")


def select(captions: list[Caption], only: int | None) -> list[Caption]:
    """Сузить проход до одного поста.

    Отсутствие поста — отказ, а не пустой проход: `--only 422` вместо `442`
    иначе отработал бы молча и успешно, ничего не сделав, и опечатку приняли
    бы за «правка не проходит».
    """
    if only is None:
        return captions
    chosen = [c for c in captions if c.message_id == only]
    if not chosen:
        sys.exit(f"В черновике нет готовой подписи для поста {only}")
    return chosen


async def run(path: Path, only: int | None, do_apply: bool) -> int:
    draft = read_draft(path)

    # Черновик проверяется целиком, а не только выбранный пост: ошибка в чужом
    # блоке означает, что файл правили невнимательно, и чинить его надо весь.
    problems = check(draft)
    if problems:
        # Не «пропустим плохие, сделаем остальные»: подпись длиннее предела
        # или задвоенный пост — это ошибка в файле, который правил человек,
        # и чинить её должен он, а не мы догадками.
        print("Черновик не годится:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    captions = select(draft.ready, only)
    skipped = draft.skipped

    channel = config.CONTENT_CHANNEL_ID or ""
    if not channel:
        sys.exit("CONTENT_CHANNEL_ID не задан — некуда писать")

    preview(captions, skipped, channel)
    if not do_apply:
        print("\nВхолостую. Чтобы правда проставить — повторите с --apply")
        return 0

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN не задан")

    via_chat = config.ADMIN_CHAT_ID or ""
    if not via_chat:
        # Без служебного чата прежнюю подпись не снять, а правка без снимка
        # необратима. Поэтому это отказ, а не предупреждение.
        sys.exit("ADMIN_CHAT_ID не задан — некуда снимать прежние подписи, правка необратима")

    from telegram import Bot

    journal = journal_path(path)
    print(f"Прежние подписи пишутся в {journal.name}\n")
    bot = Bot(token)
    async with bot:
        failures = await apply(bot, channel, captions, journal, via_chat)

    if failures:
        print(f"\nНе проставлено {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
    done = len(captions) - len(failures)
    if done:
        ids = [c.message_id for c in captions]
        print(f"\nПроставлено {done}. Индекс об этом ещё не знает — в боте:")
        print(f"    /reindex {min(ids)} {max(ids)}")
    return 1 if failures else 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Проставить подписи постам канала из черновика")
    parser.add_argument("draft", type=Path, help="файл captions_draft.txt")
    parser.add_argument("--only", type=int, help="только этот пост — с него и начинайте")
    parser.add_argument(
        "--apply", action="store_true", help="правда править канал (без флага — вхолостую)"
    )
    args = parser.parse_args()

    raise SystemExit(asyncio.run(run(args.draft.expanduser(), args.only, args.apply)))


if __name__ == "__main__":
    main()
