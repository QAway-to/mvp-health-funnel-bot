"""Картинка приветствия: файл в репозитории вместо file_id.

Почему не file_id, как было раньше. Telegram выдаёт file_id не на файл, а на
пару «файл + бот»: чужой идентификатор для другого бота не существует. При
переезде на @FederationHealthBot картинка приветствия умерла молча — в логе
«Wrong file identifier», у человека просто нет картинки, — и заметить это
можно было только по логу.

Поэтому в `prompts/welcome.txt` теперь имя файла из `site/public/img/`.
Первая отправка загружает его в Telegram, полученный file_id остаётся в
памяти процесса, и дальше уходит он же. Так и переезд между ботами ничего не
ломает, и на каждое приветствие мы не заливаем картинку заново.

Кэш живёт до перезапуска намеренно: он ускоряет, но ни от чего не защищает,
а хранить его на диске значило бы тащить в базу значение, действительное
только для текущего бота, — то есть ровно ту ошибку, из-за которой всё это.
"""

from pathlib import Path

#: Картинки лежат вместе с картинками сайта: одна и та же фотография на
#: странице направления и в приветствии — это узнавание, а не экономия.
PHOTO_DIR = Path(__file__).resolve().parents[1] / "site" / "public" / "img"


def photo_path(value: str) -> Path | None:
    """Путь к картинке, если `value` называет файл из `PHOTO_DIR`.

    Имя берётся без каталогов: значение приходит из текстового файла, и
    подниматься из него по `../` наружу незачем.
    """
    name = (value or "").strip()
    if not name or "/" in name or "\\" in name:
        return None
    path = PHOTO_DIR / name
    return path if path.is_file() else None


class PhotoCache:
    """file_id по имени файла — на время жизни процесса."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._ids.get(name)

    def remember(self, name: str, file_id: str) -> None:
        if name and file_id:
            self._ids[name] = file_id

    def __len__(self) -> int:
        return len(self._ids)
