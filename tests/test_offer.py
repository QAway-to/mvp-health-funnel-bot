"""Оффер не должен включаться, пока в карточке продукта стоят метки.

Бот живой: незаполненная карточка + включённый продающий блок = ИИ называет
реальным людям выдуманные цены. Это тесты именно про этот предохранитель.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import offer as offer_module  # noqa: E402
from utils.offer import load_offer  # noqa: E402


@pytest.fixture
def prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(offer_module, "_PROMPTS_DIR", tmp_path)
    (tmp_path / "sales_block.txt").write_text("Продающий блок.", encoding="utf-8")
    (tmp_path / "offer_cta.txt").write_text("Хочешь системно?", encoding="utf-8")
    return tmp_path


def test_offer_blocked_while_product_has_placeholders(prompts):
    (prompts / "product.txt").write_text("ЦЕНА: <<сумма>>", encoding="utf-8")

    result = load_offer("https://pay.example/x")

    assert result.is_ready is False
    assert any("метки" in b for b in result.blockers)


def test_missing_purchase_url_does_not_block_the_funnel(prompts):
    """Без ссылки воронка всё равно доводит до кнопки — блокируют только
    выдуманные факты о продукте, они опаснее отсутствующей оплаты."""
    (prompts / "product.txt").write_text("ЦЕНА: 4900 руб.", encoding="utf-8")

    result = load_offer(None)

    assert result.is_ready is True
    assert result.purchase_url == ""


def test_offer_ready_when_everything_filled(prompts):
    (prompts / "product.txt").write_text("НАЗВАНИЕ: Курс\nЦЕНА: 4900 руб.", encoding="utf-8")

    result = load_offer("https://pay.example/x")

    assert result.is_ready is True
    assert "4900" in result.system_suffix()
    assert "Продающий блок." in result.system_suffix()


def test_unconfigured_offer_tells_model_not_to_sell(prompts):
    (prompts / "product.txt").write_text("ЦЕНА: <<сумма>>", encoding="utf-8")

    suffix = load_offer(None).system_suffix()

    assert "ПРОДАЖА СЕЙЧАС ОТКЛЮЧЕНА" in suffix
    assert "Не называй цен" in suffix


@pytest.mark.parametrize(
    "reply",
    [
        "Программа стоит 4900 рублей.",
        "Это 4 900 ₽ за месяц.",
        "Цена: 120 долларов.",
        "Стоимость — 15 тыс.",
    ],
)
def test_unconfigured_offer_blocks_invented_prices(prompts, reply):
    """Инструкция в промпте — не гарантия: модель можно раскрутить на цену."""
    (prompts / "product.txt").write_text("ЦЕНА: <<сумма>>", encoding="utf-8")
    unconfigured = load_offer(None)

    safe, blocked = unconfigured.sanitize_reply(reply)

    assert blocked is True
    assert "4900" not in safe and "120" not in safe


@pytest.mark.parametrize(
    "reply",
    [
        "Начни с 500 метров, потом 1 км.",
        "Бегай 10–15 минут два раза в день.",
        "Достаточно 20–30 секунд по росе.",
    ],
)
def test_ordinary_answers_are_not_touched(prompts, reply):
    """База знаний полна чисел — они не должны считаться ценой."""
    (prompts / "product.txt").write_text("ЦЕНА: <<сумма>>", encoding="utf-8")
    unconfigured = load_offer(None)

    safe, blocked = unconfigured.sanitize_reply(reply)

    assert blocked is False and safe == reply


def test_configured_offer_may_talk_about_price(prompts):
    (prompts / "product.txt").write_text("ЦЕНА: 4900 руб.", encoding="utf-8")
    configured = load_offer("https://pay.example/x")

    safe, blocked = configured.sanitize_reply("Программа стоит 4900 рублей.")

    assert blocked is False and "4900" in safe


def test_demo_marker_is_detected_but_does_not_block(prompts):
    """Демо-данные оффер не блокируют — иначе не показать воронку заказчику."""
    (prompts / "product.txt").write_text("# DEMO\nЦЕНА: 4900 руб.", encoding="utf-8")

    result = load_offer("https://pay.example/x")

    assert result.is_demo is True
    assert result.is_ready is True


def test_real_product_card_is_not_marked_demo(prompts):
    (prompts / "product.txt").write_text("ЦЕНА: 4900 руб.", encoding="utf-8")

    assert load_offer("https://pay.example/x").is_demo is False


def test_invoice_title_is_cut_by_word_not_mid_word(prompts):
    (prompts / "product.txt").write_text(
        "НАЗВАНИЕ: Вход в бег босиком — базовый курс Федерации\nЦЕНА: 4900 руб.",
        encoding="utf-8",
    )

    title = load_offer("https://pay.example/x").product_name

    full = "Вход в бег босиком — базовый курс Федерации"
    assert len(title) <= 32
    assert full.startswith(title)          # это начало настоящего названия
    assert full[len(title)] == " "         # и обрыв пришёлся на границу слова


def test_invoice_title_falls_back_without_name(prompts):
    (prompts / "product.txt").write_text("ЦЕНА: 4900 руб.", encoding="utf-8")

    assert load_offer("https://pay.example/x").product_name == "Доступ к материалам"


def test_comment_lines_do_not_leak_into_prompt(prompts):
    (prompts / "product.txt").write_text(
        "# служебный комментарий\nНАЗВАНИЕ: Курс\nЦЕНА: 4900 руб.", encoding="utf-8"
    )

    result = load_offer("https://pay.example/x")

    assert "служебный комментарий" not in result.product_card
    assert "НАЗВАНИЕ: Курс" in result.product_card
