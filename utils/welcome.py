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


@dataclass(frozen=True)
class Welcome:
    """Что показать человеку первым сообщением."""

    key: str
    text: str
    #: file_id картинки в Telegram. Пусто — покажем картинку из `default`.
    photo: str = ""


def _parse(raw: str) -> dict[str, Welcome]:
    sections: dict[str, tuple[list[str], str]] = {}
    key: str | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(_SECTION_PREFIX):
            key = stripped[len(_SECTION_PREFIX) :].strip().lower()
            if key:
                sections.setdefault(key, ([], ""))
            continue
        if key is None:
            continue
        lines, photo = sections[key]
        if stripped.lower().startswith(_PHOTO_PREFIX):
            sections[key] = (lines, stripped[len(_PHOTO_PREFIX) :].strip())
            continue
        lines.append(line.rstrip())

    result: dict[str, Welcome] = {}
    for key, (lines, photo) in sections.items():
        text = "\n".join(lines).strip()
        if text:
            result[key] = Welcome(key=key, text=text, photo=photo)
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
    return Welcome(key=chosen.key, text=chosen.text, photo=fallback.photo)
