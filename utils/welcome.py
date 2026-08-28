"""Приветствие бота — своё на каждое направление.

Раньше текст приветствия лежал прямо в bot.py и рассказывал про бег босиком.
Пока направление было одно, это работало. Теперь их семь, и человек, пришедший
со страницы про сон, первым сообщением получал речь о стопе и коленях — то
есть ровно то, за чем не приходил.

Метка направления и так приезжает в deep link (`t.me/<bot>?start=son`) и
хранится в состоянии пользователя. Здесь она наконец выбирает текст.

Тексты живут в `prompts/welcome.txt` и правятся без изменения кода: раздел
`== <слаг>` на направление плюс обязательный `== default` для тех, кто пришёл
по прямой ссылке.
"""

from dataclasses import dataclass
from pathlib import Path

from utils.logger import log_agent_action

_PROMPTS_PATH = Path(__file__).resolve().parents[1] / "prompts" / "welcome.txt"

DEFAULT_KEY = "default"

_SECTION_PREFIX = "=="
_PHOTO_PREFIX = "photo:"
_TOPIC_PREFIX = "@topic "

#: Подпись кнопки Telegram обрезает многоточием примерно на этой длине.
TOPIC_LABEL_LIMIT = 40


@dataclass(frozen=True)
class Welcome:
    """Что показать человеку первым сообщением."""

    key: str
    text: str
    #: file_id картинки в Telegram. Пусто — покажем картинку из `default`.
    photo: str = ""
    #: Темы направления кнопками. Клик = тот же вопрос, только не напечатанный.
    topics: tuple[str, ...] = ()


def _parse(raw: str) -> dict[str, Welcome]:
    sections: dict[str, tuple[list[str], str, list[str]]] = {}
    #: Прежний слаг -> действующий раздел. Ссылки со старой меткой не пропадают.
    aliases: dict[str, str] = {}
    key: str | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(_SECTION_PREFIX):
            # Заголовок может перечислить несколько слагов через запятую:
            # «== massazh, samomassazh». Так живут метки направлений, которые
            # слили в одно: ссылки со старой уже разошлись, и уводить их в
            # общее приветствие было бы потерей.
            names = [n.strip().lower() for n in stripped[len(_SECTION_PREFIX) :].split(",")]
            names = [n for n in names if n]
            key = names[0] if names else None
            if key:
                sections.setdefault(key, ([], "", []))
                for alias in names[1:]:
                    aliases[alias] = key
            continue
        if key is None:
            continue
        lines, photo, topics = sections[key]
        if stripped.lower().startswith(_PHOTO_PREFIX):
            sections[key] = (lines, stripped[len(_PHOTO_PREFIX) :].strip(), topics)
            continue
        if stripped.startswith(_TOPIC_PREFIX):
            label = stripped[len(_TOPIC_PREFIX) :].strip()
            if label:
                topics.append(label)
            continue
        lines.append(line.rstrip())

    result: dict[str, Welcome] = {}
    for key, (lines, photo, topics) in sections.items():
        text = "\n".join(lines).strip()
        if text:
            result[key] = Welcome(
                key=key, text=text, photo=photo, topics=tuple(topics)
            )

    # Псевдоним ведёт на тот же объект, а не на копию: `key` внутри остаётся
    # действующим, поэтому и callback_data кнопок будет с действующим слагом.
    for alias, target in aliases.items():
        if target in result:
            result[alias] = result[target]
    return result


def load_welcome() -> dict[str, Welcome]:
    """Прочитать приветствия. Пустой словарь — не авария, а повод для лога."""
    try:
        raw = _PROMPTS_PATH.read_text(encoding="utf-8")
    except OSError as e:
        log_agent_action("Welcome", f"Не прочитан welcome.txt: {e}", level="ERROR")
        return {}

    sections = _parse(raw)
    if DEFAULT_KEY not in sections:
        log_agent_action(
            "Welcome",
            "в welcome.txt нет раздела '== default' — пришедшим по прямой ссылке "
            "показать будет нечего",
            level="ERROR",
        )
    if sections:
        log_agent_action("Welcome", f"Приветствий загружено: {len(sections)}")
    else:
        log_agent_action("Welcome", "welcome.txt пуст", level="ERROR")
    return sections


def welcome_for(sections: dict[str, Welcome], source: str) -> Welcome | None:
    """Приветствие для метки направления, иначе общее.

    Картинка наследуется от `default`: снимать своё фото под каждое
    направление никто не обязан, а приветствие без картинки выглядит беднее,
    чем было раньше.
    """
    if not sections:
        return None

    fallback = sections.get(DEFAULT_KEY)
    chosen = sections.get(source.strip().lower()) if source else None
    if chosen is None:
        return fallback
    if chosen.photo or fallback is None:
        return chosen
    return Welcome(
        key=chosen.key, text=chosen.text, photo=fallback.photo, topics=chosen.topics
    )
