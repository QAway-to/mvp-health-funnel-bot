"""Язык озвучки определяется один раз, и неудача не считается ответом.

Проход длинный: модель слушает по четыре куска дорожки у каждого ролика, и
предыдущие заходы на этой выгрузке обрывали не на ошибке, а на молчаливом
счёте. Отсюда два требования, которые здесь и проверяются.

Определённое не пересчитывается, и записывается оно после каждого ролика —
иначе обрыв стоит всего прохода.

А вот ролик, на котором инструмент споткнулся, в файл не попадает вовсе. Это
обратное решение по сравнению с расшифровкой, где доказанная тишина пишется
пустым файлом и закрывает ролик навсегда: там нечего распознавать, а здесь
ответа просто нет. Запиши его хоть чем-нибудь — и дозапуск уже не вернётся, а
язык ролика так и останется неизвестным под видом известного.

Тишина не слушается по той же причине: у тишины нет языка, и модель вернёт на
неё случайную догадку с высокой уверенностью, которая потом будет выглядеть
как факт.
"""

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import detect_speech_language as detector  # noqa: E402


@pytest.fixture
def export(tmp_path: Path) -> Path:
    """Выгрузка в том виде, в каком её оставляет расшифровка."""
    (tmp_path / detector.VIDEO_DIR).mkdir()
    (tmp_path / detector.TRANSCRIPTS).mkdir()
    return tmp_path


def clip(export: Path, name: str, transcript: str) -> Path:
    """Ролик с расшифровкой. Пустая расшифровка — доказанная тишина."""
    video = export / detector.VIDEO_DIR / name
    video.write_bytes(b"not really a video")
    (export / detector.TRANSCRIPTS / f"{name}.txt").write_text(transcript, encoding="utf-8")
    return video


@dataclass
class Whisper:
    """Что подмена запомнила: загрузки модели и прослушанные ролики.

    Загрузки считаются отдельно от прослушиваний, потому что это разные
    инварианты: «не слушать уже определённое» и «не грузить модель, когда
    слушать нечего». Одного списка на оба хватило бы ровно до того дня, когда
    загрузку перенесут выше проверки, — и тест бы этого не заметил.
    """

    loaded: list[str]
    listened: list[str]


def fake_whisper(monkeypatch: pytest.MonkeyPatch, answers: dict[str, object]) -> Whisper:
    """Подменить faster-whisper. Значение-исключение означает сбой на ролике.

    Модель настоящая слушает дорожку минутами, и ни один инвариант здесь от
    качества распознавания не зависит — зависит от того, что инструмент делает
    с ответом.
    """
    seen = Whisper(loaded=[], listened=[])
    listened = seen.listened

    class Model:
        def __init__(self, name: str, device: str = "", compute_type: str = "") -> None:
            self.name = name
            seen.loaded.append(name)

        def detect_language(self, audio=None, vad_filter=None, language_detection_segments=None):
            name = Path(audio).name
            listened.append(name)
            answer = answers[name]
            # BaseException, а не Exception: Ctrl+C инструмент гасить не должен,
            # и подмена обязана уметь изобразить именно его.
            if isinstance(answer, BaseException):
                raise answer
            language, probability = answer
            return language, probability, None

    package = types.ModuleType("faster_whisper")
    package.WhisperModel = Model
    audio = types.ModuleType("faster_whisper.audio")
    audio.decode_audio = lambda path, sampling_rate=16000: path
    package.audio = audio

    monkeypatch.setitem(sys.modules, "faster_whisper", package)
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", audio)
    return seen


def test_silence_is_not_listened_to(export: Path) -> None:
    clip(export, "speech.MOV", "а теперь по снегу")
    clip(export, "silence.MOV", "")
    clip(export, "spaces.MOV", "   \n  ")

    assert [video.name for video in detector.spoken_clips(export)] == ["speech.MOV"]


def test_transcript_without_its_clip_is_skipped(export: Path) -> None:
    """Расшифровка живёт дольше файла: выгрузку могли пересобрать заново."""
    (export / detector.TRANSCRIPTS / "gone.MOV.txt").write_text("текст", encoding="utf-8")

    assert detector.spoken_clips(export) == []


def test_missing_transcripts_folder_stops_the_run(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stop:
        detector.spoken_clips(tmp_path)

    assert "transcribe_channel" in str(stop.value)


def test_known_survives_a_round_trip(tmp_path: Path) -> None:
    target = tmp_path / detector.LANGUAGES
    detector.write_known(target, {"b.MOV": ("uk", 0.9415), "a.MOV": ("ru", 0.5)})

    assert detector.read_known(target) == {"a.MOV": ("ru", 0.5), "b.MOV": ("uk", 0.942)}
    # Порядок строк не зависит от порядка определения: файл дозаписывается
    # много раз, и переставленные строки превратили бы его правку в кашу.
    assert target.read_text(encoding="utf-8").splitlines()[1].startswith("a.MOV")


def test_absent_file_is_not_an_error(tmp_path: Path) -> None:
    assert detector.read_known(tmp_path / detector.LANGUAGES) == {}


def test_a_broken_line_does_not_cost_the_rest(tmp_path: Path) -> None:
    """Обрыв посреди записи оставляет огрызок строки — это не повод всё терять."""
    target = tmp_path / detector.LANGUAGES
    target.write_text(
        "file\tlanguage\tprobability\n"
        "good.MOV\tru\t0.900\n"
        "half-written.MOV\tuk\n"
        "nonsense.MOV\tru\tочень уверенно\n"
        "after.MOV\ten\t0.400\n",
        encoding="utf-8",
    )

    assert detector.read_known(target) == {"good.MOV": ("ru", 0.9), "after.MOV": ("en", 0.4)}


def test_determined_clips_are_not_listened_to_again(
    export: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip(export, "old.MOV", "уже определён")
    clip(export, "new.MOV", "ещё нет")
    detector.write_known(export / detector.LANGUAGES, {"old.MOV": ("uk", 0.88)})
    seen = fake_whisper(monkeypatch, {"new.MOV": ("ru", 0.91)})

    known = detector.detect(export, "small")

    assert seen.listened == ["new.MOV"]
    assert known == {"old.MOV": ("uk", 0.88), "new.MOV": ("ru", 0.91)}


def test_nothing_pending_means_no_model_at_all(
    export: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Загрузка модели — минуты и гигабайт; впустую её грузить незачем.

    Проверяется именно загрузка, а не прослушивание: модель, построенная до
    проверки «а есть ли что слушать», обошлась бы человеку в те же минуты и
    гигабайт, ничего при этом не прослушав.
    """
    clip(export, "old.MOV", "уже определён")
    detector.write_known(export / detector.LANGUAGES, {"old.MOV": ("ru", 0.95)})
    seen = fake_whisper(monkeypatch, {})

    assert detector.detect(export, "small") == {"old.MOV": ("ru", 0.95)}
    assert seen.loaded == []
    assert seen.listened == []


def test_each_clip_is_written_before_the_next_one(
    export: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обрыв на втором ролике не имеет права стоить первого."""
    clip(export, "first.MOV", "речь")
    clip(export, "second.MOV", "речь")
    fake_whisper(
        monkeypatch,
        {"first.MOV": ("ru", 0.93), "second.MOV": KeyboardInterrupt("оборвали")},
    )

    with pytest.raises(KeyboardInterrupt):
        detector.detect(export, "small")

    assert detector.read_known(export / detector.LANGUAGES) == {"first.MOV": ("ru", 0.93)}


def test_a_failed_clip_is_left_for_the_next_run(
    export: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой — не ответ: ролик не записан, значит дозапуск его переберёт."""
    clip(export, "broken.MOV", "речь")
    clip(export, "fine.MOV", "речь")
    fake_whisper(
        monkeypatch,
        {"broken.MOV": RuntimeError("moov atom not found"), "fine.MOV": ("uk", 0.84)},
    )

    known = detector.detect(export, "small")

    assert known == {"fine.MOV": ("uk", 0.84)}
    assert "broken.MOV" not in detector.read_known(export / detector.LANGUAGES)


def test_doubtful_russian_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    """Неуверенный русский — обычно смешанная речь, и её слушает человек."""
    detector.report(
        {
            "sure.MOV": ("ru", 0.97),
            "mixed.MOV": ("ru", 0.61),
            "ukrainian.MOV": ("uk", 0.52),
        }
    )

    printed = capsys.readouterr().out
    assert "mixed.MOV" in printed
    assert "sure.MOV" not in printed.split("неуверенно")[-1]
    # Невысокая уверенность на украинском в этот список не попадает: ролик
    # отсеивается по языку, а не по тому, насколько уверенно он украинский.
    assert "ukrainian.MOV" not in printed.split("неуверенно")[-1]


def test_the_file_is_replaced_whole_and_leaves_nothing_behind(tmp_path: Path) -> None:
    """Запись идёт через соседний файл, и этот сосед не должен оставаться.

    Файл перезаписывается после каждого ролика, и прямая запись оставляла бы
    его обрезанным, если процесс убить посреди неё: обрыв стоил бы не одного
    ролика, а всего прохода. Переставленное имя эту дыру закрывает — но
    забытый `.tmp` рядом с результатом выглядит как недосчитанный проход.
    """
    target = tmp_path / detector.LANGUAGES
    detector.write_known(target, {"a.MOV": ("ru", 0.9)})
    detector.write_known(target, {"a.MOV": ("ru", 0.9), "b.MOV": ("uk", 0.8)})

    assert [path.name for path in sorted(tmp_path.iterdir())] == [detector.LANGUAGES]
    assert len(detector.read_known(target)) == 2


def test_the_model_is_loaded_once_for_the_whole_run(
    export: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Модель грузится одна на проход, а не по одной на ролик."""
    clip(export, "one.MOV", "речь")
    clip(export, "two.MOV", "речь")
    seen = fake_whisper(monkeypatch, {"one.MOV": ("ru", 0.9), "two.MOV": ("uk", 0.8)})

    detector.detect(export, "small")

    assert seen.loaded == ["small"]
    assert seen.listened == ["one.MOV", "two.MOV"]
