"""Пошаговый курс: шаг = ролик + текст.

Это и есть продукт. Разговор «спроси — отвечу» даёт пользу, но не даёт причины
вернуться завтра: человек закрывает чат, и следующий приход зависит от того,
вспомнит ли он сам. Курс, выдаваемый по шагу, эту причину создаёт.

Ролик и текст — две половины одного шага: видео показывает движение, текст
показывает меру. Поэтому проверяется и то, что текст есть у каждого шага, и
то, что отсутствие ролика шаг не ломает.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402
from utils.content_library import tags_for_text  # noqa: E402
from utils.steps import Course, Step, course_for, load_courses  # noqa: E402

COURSES = load_courses()


def test_courses_exist():
    assert COURSES, "пошаговых курсов нет — бот остаётся справочной"


def test_bot_loaded_them():
    assert bot_module._COURSES


def test_every_step_has_text():
    """Ролик может отсутствовать, текст — никогда: он и есть шаг."""
    for slug, course in COURSES.items():
        for step in course.steps:
            assert step.text.strip(), f"{slug}: шаг {step.number} без текста"


def test_steps_are_numbered_without_gaps():
    for slug, course in COURSES.items():
        numbers = [step.number for step in course.steps]
        assert numbers == list(range(1, len(numbers) + 1)), f"{slug}: дыра в нумерации {numbers}"


#: Направления, по которым автор снял ролики. У них шаг обязан быть парой.
FILMED = ("beg", "son", "zakalivanie")

#: Направления, где роликов нет вовсе. Курс идёт текстом — это осознанно, и
#: файл обязан об этом говорить, иначе через месяц никто не вспомнит почему.
TEXT_ONLY = ("vrednye-privychki", "zaryadka", "massazh")


def test_filmed_courses_pair_every_step_with_a_clip():
    """Там, где ролики сняты, шаг без ролика — недоделка, а не решение."""
    for slug in FILMED:
        course = COURSES[slug]
        without = [step.number for step in course.steps if not step.video_tags]
        assert not without, f"{slug}: шаги без ролика — {without}"


def test_text_only_courses_say_so_out_loud():
    """Курс без роликов — сознательный выбор, и он должен быть записан."""
    for slug in TEXT_ONLY:
        path = next(p for p in (Path(__file__).resolve().parents[1] / "prompts" / "steps").glob(f"*-{slug}.txt"))
        header = path.read_text(encoding="utf-8")[:900].lower()
        assert "ролик" in header, f"{slug}: не сказано, что курс идёт без роликов"


def test_all_open_directions_have_a_course():
    """Шесть направлений открыто — шесть курсов. Без исключений."""
    expected = set(FILMED) | set(TEXT_ONLY)
    assert set(COURSES) == expected, f"нет курса у: {expected - set(COURSES)}"


def test_video_tags_are_ones_the_library_understands():
    """Тег, которого не знает библиотека, не подберёт ничего и никогда."""
    unknown = []
    for slug, course in COURSES.items():
        for step in course.steps:
            for tag in step.video_tags:
                if not tags_for_text(tag):
                    unknown.append(f"{slug}:{step.number} — #{tag}")
    assert not unknown, "теги, которых нет в библиотеке:\n" + "\n".join(unknown)


def test_steps_are_short_enough_to_do():
    """Длинный шаг не делают, его откладывают."""
    for slug, course in COURSES.items():
        for step in course.steps:
            assert len(step.text) <= 900, f"{slug}: шаг {step.number} — {len(step.text)} знаков"


# --- подбор курса под человека ----------------------------------------------


def test_course_follows_the_landing_tag():
    assert course_for(COURSES, "zakalivanie").slug == "zakalivanie"


def test_both_running_landings_share_one_course():
    for tag in ("komfort", "sila", "beg"):
        assert course_for(COURSES, tag).slug == "beg", tag


def test_unknown_tag_returns_nothing():
    """Метка, которой нет ни у одного направления, курс не подбирает."""
    assert course_for(COURSES, "") is None
    assert course_for(COURSES, "home") is None
    assert course_for(COURSES, "мусор") is None


# --- кнопки -----------------------------------------------------------------


def test_greeting_offers_the_course_first():
    """Поставить курс в конец — значит, до него дойдут единицы."""
    from utils.welcome import welcome_for

    greeting = welcome_for(bot_module._WELCOME, "son")
    keyboard = bot_module.TelegramBot._welcome_keyboard(greeting)
    first = keyboard.inline_keyboard[0][0]
    assert first.callback_data == f"{bot_module._STEP_CALLBACK}son:1"


def test_step_and_topic_callbacks_do_not_collide():
    assert not bot_module._STEP_CALLBACK.startswith(bot_module._TOPIC_CALLBACK)
    assert not bot_module._TOPIC_CALLBACK.startswith(bot_module._STEP_CALLBACK)


def test_step_callbacks_fit_telegram_limit():
    for slug, course in COURSES.items():
        data = f"{bot_module._STEP_CALLBACK}{slug}:{course.length}"
        assert len(data.encode("utf-8")) <= 64, data


# --- границы курса ----------------------------------------------------------


def test_asking_past_the_end_gives_nothing():
    course = COURSES["son"]
    assert course.step(course.length + 1) is None
    assert course.step(0) is None


def test_a_course_without_steps_is_not_loaded():
    empty = Course(slug="x", title="x", steps=())
    assert empty.step(1) is None
    assert empty.length == 0


def test_step_carries_its_tags_separately_from_text():
    step = Step(number=1, video_tags=("роса",), text="текст")
    assert step.video_tags == ("роса",)
    assert "video:" not in step.text
