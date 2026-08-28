"""База знаний: по файлу на направление, все они доезжают до модели.

Раньше знания лежали одним файлом вместе с правилами, и проверять было нечего:
файл либо прочитался, либо нет. Теперь файлов восемь, склеивает их код, и
сломаться может тихо — направление просто перестанет отвечать, а ошибки не
будет ни одной. Отсюда эти проверки.

Отдельно проверяется то, чего в базе быть НЕ должно. Голодание и курение
заказчик не подтвердил: по голоданию в его материалах нет ни одного
противопоказания, по курению нет текста вообще. Если такой раздел однажды
появится сам собой, узнать об этом лучше здесь, чем от человека, который
послушал бота.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as bot_module  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "prompts" / "kb"

# Направления, открытые на сайте. Список намеренно продублирован здесь, а не
# импортирован: тест должен падать, когда файл направления пропал, а не молча
# соглашаться с тем, что осталось.
DIRECTIONS = {
    "01-beg.txt": "БЕГ",
    "02-son.txt": "СОН",
    "03-zakalivanie.txt": "ЗАКАЛИВАНИЕ",
    "04-vrednye-privychki.txt": "ВРЕДНЫЕ ПРИВЫЧКИ",
    "05-zaryadka.txt": "ЗАРЯДКА",
    # Массаж и самомассаж слиты 28.08.2026: приёмы там одни и те же.
    "06-massazh.txt": "МАССАЖ И САМОМАССАЖ",
}


def test_every_direction_has_a_file():
    present = {path.name for path in KB_DIR.glob("*.txt")}
    assert present == set(DIRECTIONS), "состав направлений в prompts/kb разошёлся с сайтом"


def test_every_file_declares_its_direction():
    """Первая строка — заголовок направления: по нему модель и ориентируется."""
    for name, title in DIRECTIONS.items():
        text = (KB_DIR / name).read_text(encoding="utf-8").strip()
        assert text, f"{name} пуст"
        assert text.startswith(f"НАПРАВЛЕНИЕ: {title}"), f"{name} не объявляет направление"


def test_knowledge_reaches_the_model():
    """Файл на диске бесполезен, если не попал в системный промпт."""
    prompt = bot_module._CHAT_SYSTEM_PROMPT
    for title in DIRECTIONS.values():
        assert f"НАПРАВЛЕНИЕ: {title}" in prompt, f"направление {title} не доехало до модели"


def test_no_placeholders_left():
    for path in KB_DIR.glob("*.txt"):
        text = path.read_text(encoding="utf-8")
        assert "<<" not in text, f"в {path.name} остались метки <<...>>"


def test_unconfirmed_topics_stay_out():
    """Голодание и курение не подтверждены — инструкций по ним быть не должно."""
    prompt = bot_module._CHAT_SYSTEM_PROMPT

    assert "ЧЕГО НЕТ В БАЗЕ ЗНАНИЙ:" in prompt
    absent = prompt.split("ЧЕГО НЕТ В БАЗЕ ЗНАНИЙ:", 1)[1]
    for topic in ("Голодание", "курение"):
        assert topic in absent, f"«{topic}» пропало из списка того, чего у нас нет"

    habits = (KB_DIR / "04-vrednye-privychki.txt").read_text(encoding="utf-8")
    assert "КУРЕНИЯ В БАЗЕ НЕТ" in habits, "предупреждение про курение пропало"


def test_directions_in_preparation_are_marked():
    """Зарядка и массаж открыты как материалы — модель должна это знать."""
    for name in ("05-zaryadka.txt", "06-massazh.txt"):
        text = (KB_DIR / name).read_text(encoding="utf-8")
        assert "дописыва" in text, f"{name} не помечен как готовящийся"
        assert "ГОВОРИТЬ ЧЕСТНО" in text, f"в {name} нет списка того, чего в нём нет"


def test_contraindications_are_present_where_they_matter():
    """Холод и массаж — единственные темы, где молчание стоит здоровья."""
    for name in ("03-zakalivanie.txt", "06-massazh.txt"):
        text = (KB_DIR / name).read_text(encoding="utf-8")
        assert "ПРОТИВОПОКАЗАНИ" in text.upper(), f"в {name} нет противопоказаний"


def test_loader_survives_a_missing_directory(tmp_path, monkeypatch):
    """Пустой каталог — не авария: бот отвечает правилами, а не падает."""
    monkeypatch.setattr(bot_module, "_KB_DIR", tmp_path / "nope")
    assert bot_module._load_knowledge_base() == ""


def test_entry_hint_names_the_landing_direction():
    """Метка из deep link должна доезжать до модели словами, а не слагом."""
    hint = bot_module.entry_hint("zakalivanie")
    assert "Закаливание" in hint
    assert "не по бегу" in hint


def test_entry_hint_is_empty_without_a_known_source():
    for source in ("", "home", "demo", "site", "мусор"):
        assert bot_module.entry_hint(source) == "", f"неожиданная подсказка для {source!r}"


def test_every_lead_segment_of_the_site_is_understood():
    """Слаги задаёт сайт (src/lib/leadLink.ts). Разъедутся — метка потеряется."""
    from_site = {
        "komfort", "sila", "beg", "son", "zaryadka", "samomassazh",
        "massazh", "zakalivanie", "vrednye-privychki",
    }
    assert from_site <= set(bot_module._SOURCE_DIRECTIONS), "сайт шлёт метку, которой бот не знает"


def test_no_stray_foreign_characters():
    """Иероглиф или латиница посреди русской фразы — след опечатки при правке.

    Ловится только глазами и только случайно: модель такой текст проглотит и
    перескажет человеку как есть. Проверяем весь каталог промптов, а не одну
    базу знаний.
    """
    suspicious = []
    for path in sorted((KB_DIR.parent).rglob("*.txt")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for char in line:
                # CJK, хирагана, катакана, хангыль — ничего этого в русском
                # тексте Федерации быть не может
                if "぀" <= char <= "鿿" or "가" <= char <= "힯":
                    suspicious.append(f"{path.name}:{number}: {char!r} в «{line.strip()[:50]}»")
                    break
    assert not suspicious, "посторонние символы в промптах:\n" + "\n".join(suspicious)
