"""Пошаговый курс: шаг = ролик + текст.

Это и есть продукт, а не побочная функция бота. Разговор «спроси — отвечу»
даёт пользу, но не даёт причины вернуться завтра: человек закрывает чат, и
следующий его приход зависит от того, вспомнит ли он сам. Курс, выдаваемый по
шагу, эту причину создаёт.

Форма шага — ролик плюс текст, и именно в таком порядке. Движение показывают
видео, а дозировку, порядок и «чего не делать» показывает текст: одно без
другого неполно. Ролик объясняет за минуту то, на что уходит страница, а текст
остаётся, когда ролик посмотрели и забыли.

Ролик к шагу указывается тегом (`video: #роса`), а не идентификатором
сообщения. Идентификаторы у постов канала меняются при перезаливке, а тег
переживает её — и тот же тег уже используется для подбора роликов в ответах.

Ролика может не быть: часть направлений снята не полностью. Тогда шаг уходит
текстом. Это хуже, но это работает, а ждать съёмок, чтобы отдать написанное,
незачем.
"""

from dataclasses import dataclass
from pathlib import Path

from utils.logger import log_agent_action

_STEPS_DIR = Path(__file__).resolve().parents[1] / "prompts" / "steps"

_SECTION_PREFIX = "=="
_VIDEO_PREFIX = "video:"


@dataclass(frozen=True)
class Step:
    """Один шаг курса."""

    #: Порядковый номер, с единицы.
    number: int
    #: Теги ролика к этому шагу. Пусто — шаг уходит текстом.
    video_tags: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Course:
    """Курс одного направления."""

    #: Слаг направления: тот же, что у приветствий и у метки из ссылки.
    slug: str
    title: str
    steps: tuple[Step, ...]

    def step(self, number: int) -> Step | None:
        """Шаг по номеру, считая с единицы."""
        if 1 <= number <= len(self.steps):
            return self.steps[number - 1]
        return None

    @property
    def length(self) -> int:
        return len(self.steps)


def _parse(raw: str, slug: str) -> Course:
    title = ""
    sections: list[tuple[int, list[str], list[str]]] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.lower().startswith("title:"):
            title = stripped[len("title:") :].strip()
            continue
        if stripped.startswith(_SECTION_PREFIX):
            number = stripped[len(_SECTION_PREFIX) :].strip()
            if number.isdigit():
                sections.append((int(number), [], []))
            continue
        if not sections:
            continue
        _, lines, tags = sections[-1]
        if stripped.lower().startswith(_VIDEO_PREFIX):
            raw_tags = stripped[len(_VIDEO_PREFIX) :].replace("#", " ").split()
            tags.extend(tag.strip().lower() for tag in raw_tags if tag.strip())
            continue
        lines.append(line.rstrip())

    steps = tuple(
        Step(number=number, video_tags=tuple(tags), text="\n".join(lines).strip())
        for number, lines, tags in sorted(sections)
        if "\n".join(lines).strip()
    )
    return Course(slug=slug, title=title or slug, steps=steps)


def load_courses() -> dict[str, Course]:
    """Курсы из prompts/steps/*.txt, по файлу на направление.

    Имя файла — `<номер>-<слаг>.txt`: номер задаёт порядок в списке, слаг
    связывает курс с направлением, приветствием и меткой из ссылки.
    """
    try:
        paths = sorted(_STEPS_DIR.glob("*.txt"))
    except OSError as e:
        log_agent_action("Steps", f"Не прочитан каталог prompts/steps: {e}", level="ERROR")
        return {}

    courses: dict[str, Course] = {}
    for path in paths:
        slug = path.stem.split("-", 1)[-1]
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            log_agent_action("Steps", f"Не прочитан {path.name}: {e}", level="ERROR")
            continue
        course = _parse(raw, slug)
        if course.steps:
            courses[slug] = course

    if courses:
        total = sum(course.length for course in courses.values())
        with_video = sum(
            1 for course in courses.values() for step in course.steps if step.video_tags
        )
        log_agent_action(
            "Steps",
            f"Курсов загружено: {len(courses)}, шагов — {total}, из них с роликом — {with_video}",
        )
    else:
        log_agent_action("Steps", "Пошаговых курсов нет", level="WARNING")
    return courses


def course_for(courses: dict[str, Course], source: str) -> Course | None:
    """Курс по метке направления. Метка слитого направления ведёт на его курс."""
    slug = source.strip().lower()
    if slug in courses:
        return courses[slug]
    # Беговые лендинги ведут два сегмента, курс у них общий.
    if slug in ("komfort", "sila"):
        return courses.get("beg")
    if slug == "samomassazh":
        return courses.get("massazh")
    return None
