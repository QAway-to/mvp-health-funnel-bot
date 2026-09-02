"""Тексты просьбы об отзыве и допродажи.

Отдельный файл, потому что это тексты, а не логика: их правит тот, кто пишет
тексты, и правит чаще, чем код вокруг.

Формат тот же, что у карточек ступеней и этапов воронки: `== <ключ>`, дальше
текст до следующего ключа.
"""

from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
TEXTS_FILE = "review_request.txt"


def load_texts(path: Path | None = None) -> dict[str, str]:
    """Тексты по ключам. Файла нет — пустой словарь, бот молчит вместо падения."""
    source = path or (PROMPTS / TEXTS_FILE)
    if not source.is_file():
        return {}

    texts: dict[str, str] = {}
    current = ""
    lines: list[str] = []

    def flush() -> None:
        if current:
            body = "\n".join(lines).strip()
            if body:
                texts[current] = body

    for raw in source.read_text(encoding="utf-8").splitlines():
        if raw.startswith("#"):
            continue
        if raw.startswith("== "):
            flush()
            current = raw[3:].strip()
            lines = []
            continue
        lines.append(raw)
    flush()
    return texts
