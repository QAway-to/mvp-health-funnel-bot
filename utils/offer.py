"""Оффер: карточка продукта, продающий блок промпта и текст CTA.

Всё живёт в prompts/*.txt — правится без изменения кода, но требует
передеплоя: файлы читаются один раз при импорте.

Пока в файлах остаются метки вида <<...>>, оффер считается ненастроенным: бот
не показывает кнопку покупки и не обсуждает условия — иначе ИИ начнёт называть
выдуманные цены живым людям.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from utils.logger import log_agent_action

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

PLACEHOLDER_OPEN = "<<"

_NOT_CONFIGURED_RULE = (
    "\n\nПРОДАЖА СЕЙЧАС ОТКЛЮЧЕНА: программа не настроена. "
    "Не называй цен, состава и условий, не предлагай купить. "
    "Если спросят о платных занятиях — скажи, что подробности скоро, "
    "и продолжи содержательный разговор."
)


# Денежные упоминания в ответе модели. Инструкция в промпте — не гарантия:
# модель можно раскрутить на разговор о цене, и тогда она назовёт выдуманную.
# База знаний про бег денег не касается, поэтому ложных срабатываний почти нет.
_PRICE_RE = re.compile(
    r"(\d[\d\s.,]*\s*(руб|₽|рубл|тыс|долл|\$|€|евро))|((цена|стоит|стоимость)\s*[:—-]?\s*\d)",
    re.IGNORECASE,
)

_PRICE_FALLBACK = (
    "Про условия и стоимость я тебе точно не скажу — уточню и вернусь. "
    "Давай пока про саму практику: что у тебя сейчас не получается?"
)


def looks_like_price_talk(text: str) -> bool:
    return bool(_PRICE_RE.search(text))


DEMO_MARKER = "# DEMO"
_INVOICE_TITLE_MAX = 32  # лимит Telegram на заголовок счёта


def _read_raw(name: str) -> str:
    try:
        return (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    except OSError as e:
        log_agent_action("Offer", f"Не прочитан {name}: {e}", level="WARNING")
        return ""


def _strip_comments(raw: str) -> str:
    lines = [line for line in raw.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines).strip()


def _read(name: str) -> str:
    """Прочитать файл промпта, выбросив строки-комментарии."""
    return _strip_comments(_read_raw(name))


@dataclass(frozen=True)
class Offer:
    product_card: str
    sales_block: str
    cta_text: str
    purchase_url: str
    blockers: tuple[str, ...]
    is_demo: bool = False

    @property
    def is_ready(self) -> bool:
        return not self.blockers

    @property
    def product_name(self) -> str:
        """Название из карточки — заголовок счёта в Telegram."""
        for line in self.product_card.splitlines():
            if line.upper().startswith("НАЗВАНИЕ:"):
                name = line.split(":", 1)[1].strip()
                if not name:
                    break
                if len(name) <= _INVOICE_TITLE_MAX:
                    return name
                # Лимит Telegram — 32 символа; режем по слову, а не посередине
                cut = name[:_INVOICE_TITLE_MAX].rsplit(" ", 1)[0].rstrip(" —-,")
                return cut or name[:_INVOICE_TITLE_MAX]
        return "Доступ к материалам"

    def sanitize_reply(self, reply: str) -> tuple[str, bool]:
        """Не дать ненастроенному боту назвать цену.

        Возвращает (текст, была_ли_подмена). Когда оффер настроен, цены брать
        неоткуда кроме карточки продукта — там они верные, и мы не вмешиваемся.
        """
        if self.is_ready or not looks_like_price_talk(reply):
            return reply, False
        return _PRICE_FALLBACK, True

    def system_suffix(self) -> str:
        """Что дописать к системному промпту чата."""
        if not self.is_ready:
            return _NOT_CONFIGURED_RULE
        return f"\n\nКАРТОЧКА ПРОДУКТА:\n{self.product_card}\n\n{self.sales_block}"


def load_offer(purchase_url: str | None) -> Offer:
    product_raw = _read_raw("product.txt")
    product = _strip_comments(product_raw)
    sales = _read("sales_block.txt")
    cta = _read("offer_cta.txt")
    is_demo = DEMO_MARKER in product_raw

    blockers: list[str] = []
    if not product:
        blockers.append("prompts/product.txt пуст")
    elif PLACEHOLDER_OPEN in product:
        blockers.append("в prompts/product.txt остались метки <<...>>")
    if not sales:
        blockers.append("prompts/sales_block.txt пуст")
    if not cta or PLACEHOLDER_OPEN in cta:
        blockers.append("в prompts/offer_cta.txt нет текста или остались метки")
    # PURCHASE_URL намеренно НЕ блокирует оффер: без него воронка всё равно
    # доводит до кнопки, а на клике честно сообщает, что оплата не подключена.
    # Блокируют только выдуманные факты о продукте — они опаснее.
    if not purchase_url:
        log_agent_action(
            "Offer", "PURCHASE_URL не задан — кнопка покупки без ссылки", level="WARNING"
        )

    offer = Offer(
        product_card=product,
        sales_block=sales,
        cta_text=cta or "Хочешь разобрать это системно?",
        purchase_url=purchase_url or "",
        blockers=tuple(blockers),
        is_demo=is_demo,
    )

    if offer.is_ready and offer.is_demo:
        log_agent_action(
            "Offer",
            "⚠️ В prompts/product.txt ДЕМО-данные: бот называет вымышленные цену и "
            "состав. Заменить до живого трафика (убрать строку '# DEMO').",
            level="WARNING",
        )
    elif offer.is_ready:
        log_agent_action("Offer", "Оффер настроен — продающий блок включён")
    else:
        log_agent_action(
            "Offer",
            "Оффер выключен: " + "; ".join(offer.blockers),
            level="WARNING",
        )
    return offer
