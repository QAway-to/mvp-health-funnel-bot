import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, filters
from telegram.error import Forbidden, TelegramError

from config import config
from utils.logger import log_agent_action
from utils.llm import chat_completion
from utils import choices
from utils.content_library import ContentItem, library, parse_caption, tags_for_text
from utils.deeplink import parse_start_payload
from utils.followups import is_quiet_hour, load_followups, next_step
from utils.funnel_stages import load_stages, offer_due, stage_for
from utils.funnel_store import UserState, journal_premium, now_iso, store
from utils.offer import CtaButton, load_offer, read_prompt, split_buttons
from utils.photos import PhotoCache, photo_path
from utils.plan_cards import card_for, load_cards, price_in
from utils.review import load_texts
from utils.purchase import email_in
from utils import lavatop, stars
from utils.telegram_html import has_markdown, plain_text, to_telegram_html
from utils.steps import course_for, load_courses
from utils.testimonials import load_testimonials, pick as pick_testimonial
from utils.welcome import load_welcome, welcome_for

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_KB_DIR = _PROMPTS_DIR / "kb"

_PERSONA_FALLBACK = (
    "Ты — представитель Федерации Здоровья. Отвечай коротко и по делу о беге и здоровье."
)


def _load_knowledge_base() -> str:
    """Знания по направлениям — по файлу на направление в prompts/kb/.

    Раньше всё лежало одним файлом вместе с правилами. Пока направление было
    одно, это работало; на семи такой файл перестаёт читаться человеком, а
    именно человек его и правит. Теперь правила остаются в persona.txt, а
    факты живут по направлениям — ровно как в репозитории сайта, где у
    каждого направления свой файл.

    Порядок склейки — по имени файла, поэтому они пронумерованы: бег идёт
    первым не случайно, это ядро продукта.
    """
    try:
        paths = sorted(_KB_DIR.glob("*.txt"))
    except OSError as e:
        log_agent_action("Bot", f"Не прочитан каталог prompts/kb: {e}", level="ERROR")
        return ""

    parts: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as e:
            log_agent_action("Bot", f"Не прочитан {path.name}: {e}", level="ERROR")
            continue
        if text:
            parts.append(text)

    if not parts:
        log_agent_action(
            "Bot",
            "prompts/kb пуст — бот останется без знаний по направлениям",
            level="ERROR",
        )
        return ""

    log_agent_action("Bot", f"База знаний: направлений — {len(parts)}")
    return "\n\n".join(parts)


def _load_persona() -> str:
    """Характер бота и база знаний: prompts/persona.txt + prompts/kb/*.txt.

    В коде им не место: правка текста не должна выглядеть как правка кода, и
    менять её должен человек, который пишет тексты, а не тот, кто читает Python.
    """
    path = _PROMPTS_DIR / "persona.txt"
    try:
        rules = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        log_agent_action("Bot", f"Не прочитан prompts/persona.txt: {e}", level="ERROR")
        rules = ""

    if not rules:
        log_agent_action(
            "Bot", "prompts/persona.txt пуст — бот будет отвечать без базы знаний", level="ERROR"
        )
        rules = _PERSONA_FALLBACK

    knowledge = _load_knowledge_base()
    return f"{rules}\n\n{knowledge}".strip() if knowledge else rules


_CHAT_SYSTEM_PROMPT = _load_persona()

# Приветствия по направлениям. Запасной текст короткий намеренно: держать
# полную копию приветствия в коде — значит однажды править её в двух местах и
# забыть про одно. Файл лежит в репозитории, и его пропажа — авария, о которой
# сообщит лог, а не то, что нужно молча компенсировать.
_WELCOME = load_welcome()
_WELCOME_FALLBACK = (
    "Приветствую! На связи Богдан, глава Федерации Здоровья.\n\n"
    "Спрашивайте — разберём по существу: бег, сон, закаливание, вредные "
    "привычки, зарядка и массаж."
)


# Направление, с лендинга которого пришёл человек. Метка приезжает в deep link
# (`t.me/bot?start=zakalivanie`) и уже хранится в состоянии пользователя —
# просто до сих пор ей нечего было сказать модели: направление было одно.
# Теперь их семь, и без этой подсказки бот открывал бы бегом разговор с
# человеком, который пришёл со страницы про сон.
#
# Два беговых лендинга ведут разные сегменты, поэтому у них своя расшифровка:
# на «Комфорт» приходят с болью, на «Силу» — из зала.
_SOURCE_DIRECTIONS: dict[str, str] = {
    "beg": "Бег",
    "komfort": "Бег — пришёл с болью в коленях и тяжестью после пробежек",
    "sila": "Бег — пришёл из зала, интересует выносливость",
    "son": "Сон",
    "zakalivanie": "Закаливание",
    "vrednye-privychki": "Вредные привычки",
    "zaryadka": "Зарядка",
    # Массаж и самомассаж слиты в одно направление: приёмы там одни и те же.
    # Старый слаг оставлен — ссылки с ним уже разошлись.
    "massazh": "Массаж и самомассаж",
    "samomassazh": "Массаж и самомассаж",
}


def topic_from_callback(data: str) -> tuple[str, str] | None:
    """Разобрать `t:<раздел>:<номер>` в пару (раздел, тема).

    None — не авария: так выглядит кнопка из приветствия, которое с тех пор
    переписали. Старое сообщение в чате остаётся, и человек может нажать на
    неё через месяц.
    """
    if not data.startswith(_TOPIC_CALLBACK):
        return None
    key, _, index = data[len(_TOPIC_CALLBACK) :].rpartition(":")
    greeting = _WELCOME.get(key)
    if not greeting or not index.isdigit():
        return None
    position = int(index)
    if position >= len(greeting.topics):
        return None
    return key, greeting.topics[position]


def entry_hint(source: str) -> str:
    """Строка о направлении входа — или пусто, если метки нет.

    Пусто — рабочее состояние, а не ошибка: человек мог прийти по прямой
    ссылке или из поиска. Тогда направление выясняется разговором, как и
    раньше.
    """
    direction = _SOURCE_DIRECTIONS.get(source.strip().lower())
    if not direction:
        return ""
    return (
        "\n\nОТКУДА ПРИШЁЛ ЭТОТ ЧЕЛОВЕК: со страницы направления «"
        + direction
        + "». С него и начинай: первый ответ — по этой теме, а не по бегу. "
        "Если человек сам переведёт разговор на другое направление, спокойно "
        "иди за ним."
    )


def _load_gift() -> str:
    """Чек-лист-подарок из prompts/gift_checklist.txt.

    Пустой файл — не авария: подарок просто не предлагается, разговор в боте от
    этого не ломается. Комментарии выброшены так же, как в остальных промптах.
    """
    path = Path(__file__).parent / "prompts" / "gift_checklist.txt"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        log_agent_action("Bot", f"Не прочитан prompts/gift_checklist.txt: {e}", level="WARNING")
        return ""
    lines = [line for line in raw.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines).strip()


_GIFT_TEXT = _load_gift()
# Лимит одного сообщения Telegram — 4096 знаков. Режем на этапе загрузки, а не
# при отправке: иначе подарок молча не уходил бы у части пользователей.
_GIFT_LIMIT = 4096
if len(_GIFT_TEXT) > _GIFT_LIMIT:
    log_agent_action(
        "Bot",
        f"gift_checklist.txt длиннее {_GIFT_LIMIT} знаков — подарок обрезан",
        level="WARNING",
    )
    _GIFT_TEXT = _GIFT_TEXT[:_GIFT_LIMIT]

_GIFT_BUTTON = "🎁 Забрать чек-лист: 30 шагов"
# Префикс callback_data кнопок с темами: «t:<раздел>:<номер>». Внутри —
# номер, а не сама тема: в callback_data Telegram даёт 64 байта, и русская
# подпись в UTF-8 съедает их вдвое быстрее латиницы.
_TOPIC_CALLBACK = "t:"
#: Кнопка-вариант ответа на вопрос бота: `c:<номер>`. В callback_data влезает
#: 64 байта, а формулировки бывают длинными — поэтому номер, а не текст.
_CHOICE_CALLBACK = "c:"
#: Последний вариант в любом списке: выйти из этой ветки разговора.
_CHOICE_OTHER = "c:other"
_CHOICE_OTHER_LABEL = "Интересует другая тема"

#: Способ оплаты: `pay:<ступень>:<способ>`.
_PAY_CALLBACK = "pay:"
_PAY_STARS = "stars"
_PAY_CARD = "card"
#: Отдельный способ, а не разновидность карты: он ведёт на страницу кассы
#: мимо почты в чате, и выбирают его именно поэтому.
_PAY_PAGE = "page"
#: Метка возврата со страницы кассы. Человек уже заплатил, но `chat_id` там
#: взяться неоткуда: на витрине его никто не знает. Единственное, что знают
#: обе стороны, — почта, и просим мы её именно здесь, сразу после оплаты,
#: пока человек ещё в этом контексте.
_PAID_START = "oplacheno"

_PAY_LABELS = {
    _PAY_STARS: "⭐ Звёздами в Telegram",
    _PAY_CARD: "💳 Картой",
    _PAY_PAGE: "Оплатить на странице",
}

# Подпись под каждым сообщением бота. Кнопки удобны, но создают ощущение
# анкеты: человек кликает и не догадывается, что можно просто спросить своими
# словами — а именно свой вопрос и переводит разговор из меню в диалог.
_CHAT_HINT = "\n\n<b>Пиши мне прямо сюда — в чат, этот диалог живой</b>"


def with_hint(text: str) -> str:
    """Дописать подпись, если её там ещё нет.

    Проверка на повтор не лишняя: текст может прийти уже с подписью — из
    промпта, из догоняющего сообщения или из ответа, который её унаследовал.
    Две одинаковые строки подряд читаются как сбой.

    Ищем саму подпись, а не её копию в кавычках. Копия здесь уже была и уже
    разъехалась: формулировку поменяли в одном месте, а проверка осталась
    сторожить прежнюю — и подпись стала дублироваться.
    """
    if not text or plain_text(_CHAT_HINT).strip() in text:
        return text
    return text + _CHAT_HINT

# Сколько кнопок с темами вешать под ответом. Меньше, чем в приветствии: там
# это меню, здесь — подсказка «можно дальше», и длинный список под каждым
# ответом быстро превращается в шум.
_TOPICS_AFTER_ANSWER = 3

# Отзывы участников. Показываются рядом с оффером — там, где человеку нужно
# чужое подтверждение, а не наше обещание.
_TESTIMONIALS = load_testimonials()

# Пошаговые курсы: шаг = ролик + текст. Это продукт, а не функция бота —
# разговор «спроси — отвечу» даёт пользу, но не даёт причины вернуться завтра.
_COURSES = load_courses()
_STEP_CALLBACK = "s:"          # s:<слаг>:<номер шага>
_GIFT_CALLBACK = "gift"
# Deep link t.me/<bot>?start=gift — так подарок выдаётся сразу после перехода
# из рекламы или поста, без лишнего клика.
_GIFT_START_ARGS = ("gift", "checklist")

_MAX_HISTORY = 20
_MAX_CONVERSATIONS = 500   # сколько чатов держим в памяти на 512MB инстансе

# Воронка — платный доступ через Telegram Stars.
# Состояние пользователей живёт в utils/funnel_store (Sheets + кеш в памяти),
# ролики — в приватном канале (utils/content_library).
_FUNNEL_CTA_AT = config.FUNNEL_CTA_AT      # после скольких сообщений показывать оффер
# Сколько раз за разговор вообще показывать оффер и через сколько сообщений
# повторять. Раньше ограничения не было: пройдя порог, человек получал блок с
# ценой под КАЖДЫМ ответом. Продающий блок при этом велит модели «второй раз
# к офферу в этом же диалоге не возвращаться» — код ей противоречил, и громче.
# Дважды — это напоминание, на третий раз это давление.
_CTA_MAX_TIMES = 2
_CTA_GAP = 6
_STARS_PRICE = config.STARS_PRICE          # цена в звёздах, задаётся через env
_REINDEX_MAX_SPAN = 200                    # сколько message_id за один /reindex
_REINDEX_PAUSE = 0.3                       # пауза между пробами, чтобы не словить flood limit
_BOOTSTRAP_SCAN = 60                       # сколько message_id пробуем при авто-старте
_BOOTSTRAP_RETRY = 60                      # пауза между попытками достучаться до канала
_BOOTSTRAP_MAX_WAIT = 1800                 # сколько всего ждём, пока бота добавят

# Догоняющие сообщения из prompts/followups.txt: что бот пишет сам, когда
# человек замолчал. Рассылку запускает внешнее расписание — см. run_followups.
_FOLLOWUPS = load_followups()
_FOLLOWUP_BATCH = 50        # сколько сообщений отправляем за один запуск
_FOLLOWUP_PAUSE = 0.05      # пауза между отправками, чтобы не словить flood limit

# Карточка продукта, продающий блок и CTA — из prompts/*.txt. Пока там метки
# <<...>>, оффер не показывается и ИИ не обсуждает покупку.
_OFFER = load_offer(config.PURCHASE_URL)

# Ступени тарифа. Подписи кнопок — в prompts/offer_plans.txt, цены в звёздах —
# в окружении: текст правит тот, кто пишет тексты, деньги задаёт тот, у кого
# доступ к кассе.
_PLAN_STARS = {
    "buy_base": config.STARS_PRICE_BASE,
    "buy_premium": config.STARS_PRICE_PREMIUM,
    "buy_pro": config.STARS_PRICE_PRO,
}

_PLAN_TITLE_MAX = 32   # лимит Telegram на заголовок счёта


@dataclass(frozen=True)
class Plan:
    """Ступень тарифа: что написано на кнопке и чем за неё платят."""

    action: str
    label: str
    stars: int

    @property
    def title(self) -> str:
        """Заголовок счёта — подпись кнопки без эмодзи и в пределах лимита."""
        clean = self.label.lstrip("💳🔗🎁 ").strip()
        return clean[:_PLAN_TITLE_MAX] or "Доступ к программе"


def _load_plans() -> tuple[str, tuple[Plan, ...]]:
    """Текст и ступени из prompts/offer_plans.txt."""
    text, buttons = split_buttons(read_prompt("offer_plans.txt"))
    plans = tuple(
        Plan(action=button.action, label=button.label, stars=_PLAN_STARS.get(button.action, 0))
        for button in buttons
        if button.action in _PLAN_STARS
    )
    return text or "Что выбираете?", plans


_PLANS_TEXT, _DECLARED_PLANS = _load_plans()

# Сумма счёта и цена на кнопке заданы в разных местах и связи между собой не
# имеют. Однажды они разошлись вдвое — сверяем при старте, чтобы узнать об
# этом из лога, а не от человека, который заплатил больше, чем прочитал.
#
# Проверяем то, что объявлено, а снимаем расхождения ниже: иначе снятая
# ступень выглядела бы как «в звёздах не продаём» и в лог не попала бы.
stars.log_check(_DECLARED_PLANS, config.STARS_PER_DOLLAR)

# Ступень, у которой счёт разошёлся с подписью, за звёзды не продаём — она
# уходит на внешнюю страницу оплаты. Лог заметит не каждый, а деньги списывает
# бот сам: цена в окружении перебивает то, что написано в коде, и один
# STARS_PRICE=2500 при кнопке «$20» стоит дороже, чем несколько дней без
# оплаты звёздами.
_PLANS = stars.without_mismatched(_DECLARED_PLANS, config.STARS_PER_DOLLAR)

#: file_id картинок приветствия, полученные этим ботом. Пустой при запуске:
#: чужие идентификаторы для него не существуют.
_PHOTOS = PhotoCache()

#: Что делать на каждом ходу разговора. Без этого модель задаёт
#: уточняющие вопросы бесконечно: плохого сообщения нет ни одного,
#: плохая только сумма.
_FUNNEL_STAGES = load_stages()

#: На каком ходу показывается оффер — берётся из тех же указаний, а не вторым
#: числом в коде. Указаний нет — падаем на FUNNEL_CTA_AT.
_OFFER_TURN = next(
    (n for n in range(1, 21) if offer_due(_FUNNEL_STAGES, message_number=n)),
    _FUNNEL_CTA_AT,
)


def should_show_cta_now(state: UserState) -> bool:
    """Придёт ли оффер под ответом, который бот пишет прямо сейчас.

    `state.messages` — номер этого ответа, считая с первого.

    Одна функция на два места: сам показ в диалоге и строка в /status. Копией
    условия это уже было — копия жила в тесте и осталась верной, когда
    оригинал сломался, поэтому тесты и молчали.

    Первый показ по порогу, а не по равенству ходу: ход можно проскочить, и на
    равенстве оффер не пришёл бы уже никогда — ветка повтора требует, чтобы
    первый показ состоялся.
    """
    if not _OFFER.is_ready or state.is_premium or state.cta_shown >= _CTA_MAX_TIMES:
        return False
    if not state.cta_shown:
        return state.messages >= _OFFER_TURN
    return state.messages >= _FUNNEL_CTA_AT + state.cta_shown * _CTA_GAP

#: Тексты просьбы об отзыве и допродажи.
_REVIEW_TEXTS = load_texts()

#: Короче этого — не отзыв, а «ок». Записывать такое значит завести
#: список из десятка «спасибо» и одного настоящего мнения.
_REVIEW_MIN_LENGTH = 40

#: Согласие на показ отзыва: `rev:yes` / `rev:no`.
_REVIEW_CALLBACK = "rev:"

#: Карточки ступеней: что человек читает перед оплатой.
_PLAN_CARDS = load_cards()

#: Идентификатор цены в кассе для каждой ступени. Пустой — ступень оплатой
#: картой не закрывается и уходит на витрину.
_LAVA_OFFERS = {
    "buy_base": config.LAVATOP_OFFER_BASE,
    "buy_premium": config.LAVATOP_OFFER_PREMIUM,
    "buy_pro": config.LAVATOP_OFFER_PRO,
}

def _default_plan() -> "Plan | None":
    """Ступень для команды /buy: рекомендуемая, иначе первая продаваемая."""
    for plan in _PLANS:
        if plan.action == "buy_premium" and plan.stars:
            return plan
    return next((plan for plan in _PLANS if plan.stars), None)


_PREMIUM_UNLOCKED_TEXT = (
    "Отлично! Доступ открыт. Теперь тебе доступны все материалы Федерации Здоровья.\n"
    "Продолжай задавать вопросы — отвечу максимально подробно."
)

# Ролики, залитые до перехода на канал-библиотеку. Эти file_id действительны
# только для этого бота, поэтому /migrate_legacy перекладывает их в канал —
# оттуда они переиндексируются как обычные посты. После миграции блок можно
# удалить.
_LEGACY_VIDEOS: dict[str, str] = {
    "закаливание": "BAACAgIAAxkDAAIBfWpEezcX3nMGQU0RY8aSA3dp_HtEAALhlQAC5FcpSja2XjngTYNdPAQ",
    "снег": "BAACAgIAAxkDAAIBgGpEfUTbkFzB8Flt6RK_GSXKhJlyAALqlQAC5FcpSmtVPv4uGvoYPAQ",
    "бокс": "BAACAgIAAxkDAAIBgWpEfU33PREwDgfBYnPvozQJrU2QAALrlQAC5FcpSi8916ciVtpWPAQ",
    "пляж": "BAACAgIAAxkDAAIBkGpEiOMClAjxv3xG5LRKlmxHoSTnAAIKlgAC5FcpSj2V9d4AARU35TwE",
    "вода": "BAACAgIAAxkDAAIBkWpEiOnmo8Q9gOGQSE_s2RO0TPOMAAILlgAC5FcpSkUcjJ7zKjRGPAQ",
}


class TelegramBot:
    def __init__(self):
        self._app: Application | None = None
        # Держим ссылку, иначе задачу может собрать GC (см. start()).
        self._warmup_task: "asyncio.Task | None" = None
        self._library_task: "asyncio.Task | None" = None
        self._bootstrap_running = False
        self._update_tasks: set["asyncio.Task"] = set()
        # Очередь на чат: апдейты одного человека идут по одному. Держим
        # только те замки, которых кто-то ждёт, — иначе словарь растёт на
        # каждого написавшего и не уменьшается.
        self._chat_locks: dict[str, "asyncio.Lock"] = {}
        self._chat_waiting: dict[str, int] = {}
        # Варианты, предложенные кнопками в последнем вопросе, по чатам.
        # Кого мы спросили об отзыве и ждём ответа следующим сообщением.
        self._awaiting_review: set[str] = set()
        # chat_id -> conversation history for free chat
        self._conversations: dict[str, list[dict[str, str]]] = {}

    async def start(self) -> None:
        if not config.TELEGRAM_BOT_ENABLED:
            log_agent_action("Telegram", "Bot disabled (TELEGRAM_BOT_ENABLED not set) — skipping polling")
            return
        if not config.TELEGRAM_BOT_TOKEN:
            log_agent_action("Telegram", "Bot token not configured — disabled")
            return
        try:
            # concurrent_updates=False — для режима опроса, где очередь
            # библиотеки и решает порядок. В режиме вебхука порядок держит
            # _process_in_order: там мы зовём process_update сами, и эта
            # настройка до него не достаёт.
            self._app = (
                Application.builder()
                .token(config.TELEGRAM_BOT_TOKEN)
                .concurrent_updates(False)
                .build()
            )
            self._app.add_handler(CommandHandler("start", self._handle_start))
            self._app.add_handler(CommandHandler("checklist", self._handle_checklist))
            self._app.add_handler(CommandHandler("kurs", self._handle_course))
            self._app.add_handler(CommandHandler("status", self._handle_status))
            self._app.add_handler(CommandHandler("reindex", self._handle_reindex))
            self._app.add_handler(CommandHandler("migrate_legacy", self._handle_migrate_legacy))
            if config.PAYMENTS_ENABLED:
                self._app.add_handler(CommandHandler("buy", self._handle_buy))
                self._app.add_handler(CommandHandler("testpay", self._handle_testpay))
                self._app.add_handler(PreCheckoutQueryHandler(self._handle_precheckout))
                self._app.add_handler(
                    MessageHandler(filters.SUCCESSFUL_PAYMENT, self._handle_payment_success)
                )
            self._app.add_handler(CallbackQueryHandler(self._handle_callback))
            # Посты в канале-библиотеке — до общего текстового хендлера,
            # иначе подпись поста уйдёт в LLM как вопрос пользователя.
            self._app.add_handler(
                MessageHandler(filters.UpdateType.CHANNEL_POST, self._handle_channel_post)
            )
            self._app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
            )

            self._app.add_error_handler(self._on_handler_error)
            self._warn_about_config_gaps()

            await self._app.initialize()
            await self._app.start()
            if self.webhook_url:
                await self._start_webhook()
            else:
                # drop_pending_updates=False: посты в канал, сделанные пока
                # сервис спал, иначе потерялись бы вместе с индексом.
                await self._app.updater.start_polling(drop_pending_updates=False)
                log_agent_action("Telegram", "Bot started (polling)")
            # Всё, что ходит в сеть, уезжает в фон. Раньше загрузка из Sheets
            # висела на пути запуска: порт открывается только после неё, и
            # медленный ответ Google валил весь деплой (Exited with status 3).
            #
            # Ссылку на задачу держим обязательно: event loop хранит только
            # слабую ссылку, и без этого сборщик мусора вправе убить прогрев
            # посреди сетевого вызова — молча, без единой строчки в логе.
            self._warmup_task = asyncio.create_task(self._warmup())
            self._warmup_task.add_done_callback(self._on_warmup_done)
        except Exception as e:
            log_agent_action("Telegram", f"Bot startup failed: {e} — running without Telegram", level="WARNING")
            # store.start() мог уже поднять фоновый флашер — иначе он останется
            # сиротой и будет ходить в Sheets каждые 10с до конца жизни процесса.
            await store.stop()
            self._app = None

    async def _on_handler_error(self, update: object, context) -> None:
        """Показать, что именно упало в обработчике.

        Без этого библиотека пишет только «No error handlers are registered», а
        человек видит полную тишину в ответ на нажатие — как было с кнопкой
        оффера, где падал вызов счёта.
        """
        error = getattr(context, "error", None)
        where = ""
        if isinstance(update, Update) and update.effective_chat:
            where = f", чат {update.effective_chat.id}"
        log_agent_action("Telegram", f"Обработчик упал: {error!r}{where}", level="ERROR")

    def _warn_about_config_gaps(self) -> None:
        """Молчаливая недонастройка дороже шумного лога: без CONTENT_CHANNEL_ID
        бот не отдаст ни одного ролика и никак об этом не сообщит."""
        if not config.CONTENT_CHANNEL_ID:
            log_agent_action(
                "Content",
                "CONTENT_CHANNEL_ID не задан — ролики отключены полностью, "
                "бот будет отвечать только текстом",
                level="ERROR",
            )
        if not config.ADMIN_CHAT_ID:
            log_agent_action(
                "Telegram",
                "ADMIN_CHAT_ID не задан — /reindex и /migrate_legacy недоступны, "
                "алерты о сбоях никуда не уйдут",
                level="WARNING",
            )

    def _warn_about_unreachable_premium(self) -> None:
        """С выключенной кассой is_premium ни у кого не станет True, поэтому
        ролики с tier: premium не увидит никто и никогда — молча."""
        if config.PAYMENTS_ENABLED:
            return
        locked = library.premium_count()
        if locked:
            log_agent_action(
                "Content",
                f"{locked} роликов помечены tier: premium, но оплата выключена — "
                "их не увидит никто. Перемаркируйте посты в канале как free.",
                level="WARNING",
            )

    # ------------------------------------------------------------------
    # Webhook: Telegram стучится к нам сам
    # ------------------------------------------------------------------

    WEBHOOK_PATH = "/telegram/webhook"

    @property
    def webhook_url(self) -> str:
        """Публичный адрес вебхука или пусто, если работаем поллингом."""
        if not config.PUBLIC_URL:
            return ""
        return config.PUBLIC_URL.rstrip("/") + self.WEBHOOK_PATH

    @property
    def webhook_secret(self) -> str:
        """Свой секрет, иначе производный от токена — чужие POST отсекаем всегда."""
        if config.TELEGRAM_WEBHOOK_SECRET:
            return config.TELEGRAM_WEBHOOK_SECRET
        digest = hashlib.sha256((config.TELEGRAM_BOT_TOKEN or "").encode()).hexdigest()
        return digest[:32]

    async def _start_webhook(self) -> None:
        """Поллинг требует, чтобы контейнер был жив; вебхук — наоборот, будит его.

        На free tier сервис засыпает через 15 минут, и при поллинге бот
        оказывается недоступен до первого чужого запроса. Здесь запрос делает
        сам Telegram: приходит задержка на холодный старт, но не потеря.
        """
        await self._app.bot.set_webhook(
            url=self.webhook_url,
            secret_token=self.webhook_secret,
            drop_pending_updates=False,
            allowed_updates=["message", "callback_query", "channel_post", "pre_checkout_query"],
        )
        log_agent_action("Telegram", f"Bot started (webhook): {self.webhook_url}")

    async def handle_webhook(self, data: dict, secret_header: str | None) -> bool:
        """Принять апдейт от Telegram. Возвращает False, если секрет не сошёлся.

        Обработка уходит в фон, а Telegram сразу получает 200: иначе он ждёт
        ответа, упирается в таймаут и присылает тот же апдейт снова — человек
        получил бы дубли.
        """
        if secret_header != self.webhook_secret:
            log_agent_action("Telegram", "Webhook: неверный секрет, запрос отброшен", level="WARNING")
            return False
        if not self._app:
            return True

        update = Update.de_json(data, self._app.bot)
        if update is None:
            return True

        task = asyncio.create_task(self._process_in_order(update))
        # Ссылку держим: без неё GC вправе убить обработку на первом await.
        self._update_tasks.add(task)
        task.add_done_callback(self._update_tasks.discard)
        return True

    async def _process_in_order(self, update: Update) -> None:
        """Обработать апдейт, дождавшись предыдущего апдейта этого же чата.

        ЗАЧЕМ. `concurrent_updates(False)` выше обещает, что апдейты не
        обрабатываются параллельно, — и в режиме вебхука это обещание не
        выполнялось: очередь библиотеки работает при опросе, а здесь мы сами
        зовём `process_update` в отдельной задаче на каждый апдейт. Нажатия
        подряд шли параллельно.

        Видно это было так: человек жмёт несколько кнопок, каждый обработчик
        ставит «⏳», уходит в LLM, возвращается в своё время, удаляет свой
        «⏳» и шлёт ролик с текстом. Сообщения появлялись вперемешку и на
        секунду-полторы, экран дёргался. Хуже незаметное: каждый обработчик
        читает состояние, ждёт модель и пишет состояние обратно — параллельные
        просто затирали счётчики друг друга, а на них держится вся воронка.

        Замок на чат, а не на бота: разные люди по-прежнему обслуживаются
        одновременно, ждёт только тот, кто нажал дважды.
        """
        # getattr, а не точка: сюда приходит то, что разобралось из чужого
        # JSON, и апдейт без чата — обычное дело (правки постов, инлайн).
        chat = getattr(update, "effective_chat", None)
        if chat is None:
            await self._app.process_update(update)
            return

        key = str(chat.id)
        lock = self._chat_locks.setdefault(key, asyncio.Lock())
        self._chat_waiting[key] = self._chat_waiting.get(key, 0) + 1
        try:
            async with lock:
                await self._app.process_update(update)
        finally:
            self._chat_waiting[key] -= 1
            # Замок живёт, пока есть кому ждать. Иначе словарь растёт на
            # каждого, кто когда-либо написал, и не уменьшается никогда.
            if self._chat_waiting[key] <= 0:
                self._chat_waiting.pop(key, None)
                self._chat_locks.pop(key, None)

    async def stop(self) -> None:
        if self._app:
            if not self.webhook_url:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            await store.stop()
            log_agent_action("Telegram", "Bot stopped")

    async def _handle_callback(self, update: Update, context) -> None:
        query = update.callback_query
        await query.answer()

        chat_id = str(update.effective_chat.id)
        data = query.data or ""

        # Клик — тоже активность: после него отсчёт тишины начинается заново.
        await store.save(replace(store.user(chat_id), last_seen_at=now_iso()))

        if data.startswith(_REVIEW_CALLBACK):
            await self._handle_review_consent(query, chat_id, data)
        elif data.startswith(_PAY_CALLBACK):
            await self._handle_pay_click(query, chat_id, data)
        elif data == _CHOICE_OTHER:
            await self._handle_choice_other(update, query, chat_id)
        elif data.startswith(_CHOICE_CALLBACK):
            await self._handle_choice_click(update, query, chat_id, data)
        elif data.startswith(_STEP_CALLBACK):
            await self._handle_step_click(update, query, chat_id, data)
        elif data.startswith(_TOPIC_CALLBACK):
            await self._handle_topic_click(update, query, chat_id, data)
        elif data == "offer":
            await self._handle_offer_click(query, chat_id)
        elif data == _GIFT_CALLBACK:
            await self._send_gift(query.message, chat_id)
        else:
            plan = next((p for p in _PLANS if p.action == data), None)
            if plan:
                await self._handle_plan_click(query, chat_id, plan)

    # --- Касса внутри бота: спит при PAYMENTS_ENABLED=false ------------------
    # Четыре метода ниже не зарегистрированы как хендлеры, пока флаг опущен.
    # Оставлены намеренно: продажа сейчас закрывается на внешней странице,
    # но Stars может понадобиться снова — код рабочий и покрыт.

    async def _send_invoice(self, message, plan: "Plan | None" = None) -> bool:
        """Счёт в Telegram Stars. Оплата не выходит из чата — ни лендинга, ни карты."""
        plan = plan or _default_plan()
        title = plan.title if plan else _OFFER.product_name
        amount = plan.stars if plan else _STARS_PRICE
        try:
            await message.reply_invoice(
                title=title,
                description=(
                    "Полный доступ к программе. Оплата проходит внутри Telegram, "
                    "карта не нужна."
                ),
                payload="premium_access",
                # Для Telegram Stars провайдер не нужен, но аргумент обязателен:
                # без него библиотека роняет обработчик, и клик по кнопке
                # оставался вообще без ответа.
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=title, amount=amount)],
            )
            return True
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send invoice: {e}", level="ERROR")
            return False

    async def _handle_buy(self, update: Update, context) -> None:
        if not update.message:
            return
        await self._send_invoice(update.message)

    async def _handle_testpay(self, update: Update, context) -> None:
        """Выдать доступ без оплаты — только владельцу.

        Команда открывает платный доступ бесплатно. Без проверки её мог бы
        набрать любой, кто её увидит или угадает, и продавать стало бы нечего.
        """
        if not update.message or await self._deny_non_admin(update, "/testpay"):
            return
        chat_id = str(update.effective_chat.id)
        await self._grant_premium(chat_id, "testpay")
        try:
            await update.message.reply_text(_PREMIUM_UNLOCKED_TEXT, parse_mode="HTML")
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send testpay confirm: {e}", level="ERROR")

    async def _handle_precheckout(self, update, context) -> None:
        query = update.pre_checkout_query
        if query.invoice_payload != "premium_access":
            await query.answer(ok=False, error_message="Неизвестный товар. Попробуй /buy заново.")
            log_agent_action(
                "Telegram", f"Rejected precheckout with payload {query.invoice_payload!r}", level="WARNING"
            )
            return
        await query.answer(ok=True)

    async def _handle_payment_success(self, update: Update, context) -> None:
        if not update.message:
            return
        chat_id = str(update.effective_chat.id)
        payment = update.message.successful_payment
        await self._grant_premium(
            chat_id,
            "stars",
            amount=getattr(payment, "total_amount", 0),
            charge_id=getattr(payment, "telegram_payment_charge_id", ""),
        )
        try:
            await update.message.reply_text(_PREMIUM_UNLOCKED_TEXT, parse_mode="HTML")
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send payment confirm: {e}", level="ERROR")

    async def grant_premium(self, chat_id: str, reason: str, **details: Any) -> None:
        """Публичная обёртка: доступ выдаёт не только чат, но и оплата картой.

        Уведомление LavaTop приходит по HTTP, минуя Telegram, и ему нужен тот
        же путь выдачи. Разные пути к одному доступу разошлись бы на первой же
        правке — а расходиться тут нельзя: на кону оплаченный доступ.
        """
        await self._grant_premium(chat_id, reason, **details)

    async def _grant_premium(self, chat_id: str, reason: str, **details: Any) -> None:
        """Persist the unlock immediately — a lost payment is not recoverable.

        Order matters: the local journal is written first and synchronously, so
        even a container killed before Sheets answers can restore the grant on
        the next start.
        """
        journal_premium(chat_id, reason, details)
        state = store.user(chat_id)
        persisted = await store.save(replace(state, is_premium=True), immediate=True)
        await store.event(chat_id, "premium_granted", reason=reason, **details)
        log_agent_action("Telegram", f"Premium granted to {chat_id} ({reason})")

        if not persisted:
            # Диск на free tier эфемерный, поэтому журнал переживает не всякий
            # рестарт. Telegram — единственный канал, который точно переживёт
            # подмену контейнера: пусть запись останется хотя бы в чате админа.
            await self._alert_admin(
                "⚠️ <b>Оплата не записалась в хранилище</b>\n"
                f"chat_id: <code>{chat_id}</code>\n"
                f"причина: {reason}\n"
                f"детали: <code>{details}</code>\n\n"
                "Доступ выдан в памяти. Если сервис перезапустится до того, как "
                "запись уйдёт, восстановите premium вручную по этому сообщению."
            )

    async def _alert_admin(self, text: str) -> None:
        if not self._app or not config.ADMIN_CHAT_ID:
            log_agent_action("Telegram", "ADMIN_CHAT_ID not set — alert dropped", level="ERROR")
            return
        try:
            await self._app.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID, text=text, parse_mode="HTML"
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to alert admin: {e}", level="ERROR")

    async def _handle_start(self, update: Update, context) -> None:
        if not update.message:
            return

        chat_id = str(update.effective_chat.id)
        # Deep link: t.me/<bot>?start=tiktok -> источник трафика.
        # Метка бывает составной — `buy_base__son`: с лендинга ведёт кнопка
        # «Звёздами в Telegram», стоящая рядом с конкретным уровнем.
        payload = (context.args[0] if getattr(context, "args", None) else "")[:64]
        plan_action, source = parse_start_payload(payload, frozenset(_PLAN_STARS))
        source = source[:40]
        state = store.user(chat_id, source=source)
        if source and not state.source:
            state = replace(state, source=source)
        # Отсчёт тишины идёт и от /start: человек, нажавший кнопку и пропавший
        # молча, — самая частая потеря в воронке, и догонять его надо тоже.
        await store.save(replace(state, last_seen_at=now_iso()))
        await store.event(chat_id, "start", bucket=state.bucket, source=state.source)

        # Приветствие своё на каждое направление: человек, пришедший со
        # страницы про сон, не должен первым сообщением получать речь о стопе
        # и коленях. Текст выбирается по метке из deep link, см.
        # prompts/welcome.txt.
        greeting = welcome_for(_WELCOME, state.source)
        if greeting is None:
            log_agent_action(
                "Telegram", "Приветствий нет — отправлено запасное", level="ERROR"
            )
        welcome = greeting.text if greeting else _WELCOME_FALLBACK
        photo = greeting.photo if greeting else ""

        if photo:
            await self._send_welcome_photo(update.message, photo)

        # Пришёл платить — меню приветствия молчит. Оно зовёт читать темы и
        # проходить курс, то есть уводит ровно в тот момент, когда человек уже
        # выбрал уровень на сайте. Кнопки ниже будут только про оплату.
        keyboard = None if plan_action else self._welcome_keyboard(greeting)
        try:
            await update.message.reply_text(
                with_hint(welcome),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send welcome: {e}", level="ERROR")

        # Пришёл по ссылке из рекламы или поста — отдаём подарок сразу, без клика
        if source.lower() in _GIFT_START_ARGS:
            await self._send_gift(update.message, chat_id)

        # Вернулся со страницы оплаты. Спрашиваем почту тут же: через час он
        # уже не вспомнит, что от него хотели, а доступ так и не откроется.
        if source.lower() == _PAID_START:
            await self._ask_to_claim(update.message, chat_id)
            return

        # Пришёл с лендинга по кнопке уровня — сразу к оплате. Приветствие
        # выше всё равно нужно: человек впервые открыл чат, и счёт без единого
        # слова выглядит как ошибка. Но выбирать уровень заново он не будет.
        plan = next((p for p in _PLANS if p.action == plan_action), None)
        if plan:
            await self._start_payment(update.message, chat_id, plan)

    async def _ask_to_claim(self, message, chat_id: str) -> None:
        """Человек пришёл из кассы после оплаты — связать платёж с этим чатом.

        Проверять всё равно будем у кассы (см. _handle_email): на слово здесь
        верить нельзя, иначе доступ откроет любой, кто дошёл по этой же ссылке.
        """
        state = store.user(chat_id)
        if state.is_premium:
            await message.reply_text(
                with_hint("Доступ уже открыт. Пиши /kurs — продолжим с того места, где остановились."),
                parse_mode="HTML",
            )
            return

        await store.event(chat_id, "returned_from_checkout")
        await message.reply_text(
            with_hint(
                "Спасибо за покупку." + "\n\n"
                "Напиши почту, которой платил, — по ней я найду твою оплату и открою доступ. "
                "Это займёт несколько секунд."
            ),
            parse_mode="HTML",
        )

    async def _send_welcome_photo(self, message, photo: str) -> None:
        """Картинка приветствия: файлом из репозитория, потом уже по file_id.

        Значение из welcome.txt может быть и готовым идентификатором — такие
        ссылки ещё встречаются, — но именем файла оно надёжнее: file_id
        принадлежит боту, а не картинке, и при смене бота перестаёт работать.
        """
        cached = _PHOTOS.get(photo)
        path = None if cached else photo_path(photo)
        try:
            if cached:
                await message.reply_photo(photo=cached)
                return
            if path is None:
                await message.reply_photo(photo=photo)
                return
            with path.open("rb") as handle:
                sent = await message.reply_photo(photo=handle)
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send welcome photo: {e}", level="WARNING")
            return

        # Запоминаем, чтобы следующему человеку картинка ушла без перезаливки.
        sizes = getattr(sent, "photo", None) or []
        if sizes:
            _PHOTOS.remember(photo, sizes[-1].file_id)

    @staticmethod
    def _welcome_keyboard(greeting) -> InlineKeyboardMarkup | None:
        """Темы направления кнопками, подарок последней строкой.

        Кнопка вместо списка жирным строк — не украшение: список нужно
        перепечатать, кнопку достаточно нажать. На первом экране это разница
        между разговором и тишиной.

        По одной кнопке в ряд: подписи длинные, в два столбца Telegram режет
        их многоточием, и человек не читает, что выбирает.
        """
        rows: list[list[InlineKeyboardButton]] = []

        # Курс — первой кнопкой: это продукт, а темы ниже — способ его
        # попробовать. Если поставить курс в конец, до него доходят единицы.
        course = course_for(_COURSES, greeting.key) if greeting else None
        if course:
            rows.append([
                InlineKeyboardButton(
                    f"▶️ Пройти курс по шагам ({course.length})",
                    callback_data=f"{_STEP_CALLBACK}{course.slug}:1",
                )
            ])

        if greeting:
            rows.extend(
                [InlineKeyboardButton(label, callback_data=f"{_TOPIC_CALLBACK}{greeting.key}:{i}")]
                for i, label in enumerate(greeting.topics)
            )
        if _GIFT_TEXT:
            rows.append([InlineKeyboardButton(_GIFT_BUTTON, callback_data=_GIFT_CALLBACK)])
        return InlineKeyboardMarkup(rows) if rows else None

    # --- пошаговый курс: шаг = ролик + текст --------------------------------

    async def _handle_course(self, update: Update, context) -> None:
        """/kurs — начать курс или продолжить с того места, где остановился."""
        if not update.message:
            return
        chat_id = str(update.effective_chat.id)
        state = store.user(chat_id)
        course = course_for(_COURSES, state.course or state.source)

        if course is None:
            await update.message.reply_text(
                with_hint(
                    "Пошаговый курс есть по бегу, сну и закаливанию. "
                    "Напиши, что из этого ближе, и начнём."
                ),
                parse_mode="HTML",
                reply_markup=self._topics_keyboard(state.source),
            )
            return

        # Курс тот же — идём дальше; сменился — начинаем сначала.
        next_number = state.step + 1 if state.course == course.slug else 1
        await self._send_step(update.message, state, course, next_number)

    async def _handle_step_click(self, update: Update, query, chat_id: str, data: str) -> None:
        """Кнопка «Дальше» под шагом."""
        slug, _, number = data[len(_STEP_CALLBACK) :].rpartition(":")
        course = _COURSES.get(slug)
        if course is None or not number.isdigit():
            log_agent_action("Steps", f"Неизвестная кнопка шага: {data}", level="WARNING")
            return
        await self._send_step(query.message, store.user(chat_id), course, int(number))

    async def _send_step(self, message, state: UserState, course, number: int) -> None:
        """Отдать шаг: сначала ролик, потом текст.

        Порядок не случаен. Ролик показывает движение, текст показывает меру —
        дозировку, порядок и чего не делать. Если сначала текст, ролик уже не
        смотрят.

        Ролика может не быть: часть направлений снята не полностью. Тогда шаг
        уходит текстом, и это лучше, чем не отдать написанное.
        """
        step = course.step(number)
        if step is None:
            await self._finish_course(message, state, course)
            return

        if step.video_tags:
            await self._send_step_video(message, state, step)

        rows = []
        if course.step(number + 1):
            rows.append([
                InlineKeyboardButton(
                    "Дальше →", callback_data=f"{_STEP_CALLBACK}{course.slug}:{number + 1}"
                )
            ])
        header = f"<i>{course.title} · шаг {number} из {course.length}</i>" + "\n\n"

        try:
            await message.reply_text(
                with_hint(header + step.text),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup(rows) if rows else None,
            )
        except TelegramError as e:
            log_agent_action("Steps", f"Шаг {number} не ушёл: {e}", level="ERROR")
            return

        await store.save(replace(state, course=course.slug, step=number))
        await store.event(state.chat_id, "step_sent", course=course.slug, step=number)

    async def _send_step_video(self, message, state: UserState, step) -> None:
        """Ролик к шагу, если он есть в канале.

        Ищем по тегам шага, а не по тексту: текст шага длинный, и подбор по
        нему притащил бы ролик по случайному совпадению слова.
        """
        if not config.CONTENT_CHANNEL_ID or not self._app:
            return
        self._ensure_library()
        item = library.match(
            " ".join(step.video_tags), is_premium=state.is_premium, exclude=()
        )
        if not item:
            log_agent_action(
                "Steps",
                f"К шагу {step.number} нет ролика (теги: {', '.join(step.video_tags)})",
            )
            return
        try:
            await self._app.bot.copy_message(
                chat_id=state.chat_id,
                from_chat_id=config.CONTENT_CHANNEL_ID,
                message_id=item.message_id,
            )
        except TelegramError as e:
            log_agent_action("Steps", f"Ролик к шагу {step.number} не ушёл: {e}", level="WARNING")

    async def _finish_course(self, message, state: UserState, course) -> None:
        """Курс пройден: сказать об этом и предложить следующий."""
        await store.event(state.chat_id, "course_finished", course=course.slug)
        others = [c for slug, c in _COURSES.items() if slug != course.slug]
        rows = [
            [InlineKeyboardButton(f"Начать: {c.title}", callback_data=f"{_STEP_CALLBACK}{c.slug}:1")]
            for c in others[:3]
        ]
        await message.reply_text(
            with_hint(
                f"<b>Курс «{course.title}» пройден.</b>\n\n"
                "Дальше всё решает регулярность, а не новые знания. "
                "Возвращайся к шагам, когда собьёшься — они никуда не денутся."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows) if rows else None,
        )

        # Отзыв просим здесь и только здесь. Человек прошёл курс целиком —
        # это единственный момент, когда ему есть что сказать и он ещё в
        # разговоре. Спросить раньше значит получить вежливость вместо опыта,
        # спросить через неделю — не получить ничего.
        await self._ask_for_review(message, state.chat_id)
        await self._offer_next(message, state)

    async def _offer_next(self, message, state: UserState) -> None:
        """Допродажа после пройденного курса.

        Только здесь и только одним сообщением. Допродажа сразу после оплаты
        читается как «мало заплатил», а в середине курса отвлекает от того,
        за чем человек пришёл. После пройденного направления она уместна:
        он уже получил обещанное и знает, чего стоит следующее.

        Что именно предложить, зависит от того, что у него есть. Прошедшему
        курс на базовом уровне предлагается уровень выше — там разбирают его
        видео. Тому, у кого уровень уже не базовый, предлагать нечего:
        следующее направление и так открыто, кнопки на него стоят выше.
        """
        text = _REVIEW_TEXTS.get("upsell_tier", "")
        if not text or not state.is_premium:
            return

        plan = next((p for p in _PLANS if p.action == "buy_premium"), None)
        if plan is None:
            return

        await store.event(state.chat_id, "upsell_shown", after="course")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Что меняется на «Премиуме»", callback_data=plan.action)]
        ])
        try:
            await message.reply_text(with_hint(text), parse_mode="HTML", reply_markup=keyboard)
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send upsell: {e}", level="ERROR")

    async def _ask_for_review(self, message, chat_id: str) -> None:
        """Попросить отзыв у прошедшего курс."""
        text = _REVIEW_TEXTS.get("request", "")
        if not text:
            return
        self._awaiting_review.add(chat_id)
        await store.event(chat_id, "review_asked")
        try:
            await message.reply_text(with_hint(text), parse_mode="HTML")
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to ask for review: {e}", level="ERROR")

    async def _handle_review(self, message, chat_id: str, text: str) -> bool:
        """Принять отзыв, если мы его ждём. True — сообщение обработано здесь.

        Публикация — отдельным вопросом и только по кнопке. Отзыв, отданный
        боту, и отзыв, который человек согласился показать на сайте, — разные
        вещи, и решать за него нельзя.
        """
        if chat_id not in self._awaiting_review:
            return False
        # Короткая реплика — это не отзыв, а «ок» или «спасибо». Такие не
        # записываем и вопрос не повторяем: настаивать после курса значит
        # испортить впечатление, ради которого всё и делалось.
        self._awaiting_review.discard(chat_id)
        if len(text.strip()) < _REVIEW_MIN_LENGTH:
            return False

        await store.event(chat_id, "review_left", text=text[:1000])
        log_agent_action("Reviews", f"Отзыв от {chat_id}: {text[:200]}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Да, можно показать", callback_data=f"{_REVIEW_CALLBACK}yes")],
            [InlineKeyboardButton("Нет, только для вас", callback_data=f"{_REVIEW_CALLBACK}no")],
        ])
        try:
            await message.reply_text(
                with_hint(
                    _REVIEW_TEXTS.get("thanks", "Спасибо.")
                    + "\n\n"
                    + _REVIEW_TEXTS.get("ask_publish", "")
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to confirm review: {e}", level="ERROR")
        return True

    async def _handle_review_consent(self, query, chat_id: str, data: str) -> None:
        """Ответ на вопрос, можно ли показать отзыв на сайте."""
        allowed = data.endswith("yes")
        await store.event(chat_id, "review_consent", allowed=allowed)
        log_agent_action(
            "Reviews", f"Чат {chat_id}: показывать отзыв — {'да' if allowed else 'нет'}"
        )
        key = "published_yes" if allowed else "published_no"
        await query.message.reply_text(
            with_hint(_REVIEW_TEXTS.get(key, "Принято.")), parse_mode="HTML"
        )

    @staticmethod
    def _topics_keyboard(source: str, *, exclude: str = "") -> InlineKeyboardMarkup | None:
        """Кнопки с темами под ответом — из раздела того направления, откуда человек.

        Меньше, чем в приветствии: там это меню, здесь подсказка «можно
        дальше». Тема, которую только что разобрали, исключается — предлагать
        её следующей строкой значит показать, что бот не слушал.
        """
        greeting = welcome_for(_WELCOME, source)
        if greeting is None or not greeting.topics:
            return None

        rows = [
            [InlineKeyboardButton(label, callback_data=f"{_TOPIC_CALLBACK}{greeting.key}:{i}")]
            for i, label in enumerate(greeting.topics)
            if label != exclude
        ][:_TOPICS_AFTER_ANSWER]
        return InlineKeyboardMarkup(rows) if rows else None

    @staticmethod
    def _choice_keyboard(options: tuple[str, ...]) -> InlineKeyboardMarkup:
        """Варианты ответа плюс выход из ветки.

        «Интересует другая тема» стоит всегда и последней: вопрос бота может
        не подходить человеку вовсе, и без выхода единственным способом уйти
        остаётся молчание — то есть уход насовсем.
        """
        rows = [
            [InlineKeyboardButton(label, callback_data=f"{_CHOICE_CALLBACK}{index}")]
            for index, label in enumerate(options)
        ]
        rows.append([InlineKeyboardButton(_CHOICE_OTHER_LABEL, callback_data=_CHOICE_OTHER)])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _clicked_label(query, data: str) -> str:
        """Подпись нажатой кнопки — из самого сообщения, а не из памяти.

        Варианты лежали в словаре процесса, и это было ошибкой: контейнер на
        Render засыпает от тишины и перезапускается на каждом выкате, после
        чего кнопка вчерашнего сообщения не находила ничего. Человек жал
        вариант и получал «этот вопрос уже позади» — тупик вместо ответа, да
        ещё и ход разговора при этом не засчитывался, то есть воронка стояла.

        Сообщение свою клавиатуру помнит всегда, сколько бы ни прошло.
        """
        markup = getattr(query.message, "reply_markup", None)
        for row in getattr(markup, "inline_keyboard", None) or ():
            for button in row:
                if button.callback_data == data:
                    return button.text or ""
        return ""

    async def _handle_choice_click(self, update: Update, query, chat_id: str, data: str) -> None:
        """Нажатый вариант — это ответ человека. Дальше обычный путь."""
        answer = self._clicked_label(query, data)
        if not answer:
            # Кнопки без подписи не бывает, так что сюда не попасть. Но если
            # попали — вести разговор вслепую нельзя, а обрывать тем более:
            # просим сказать словами и ход не тратим.
            log_agent_action(
                "Telegram", f"Кнопка варианта без подписи: {data}", level="WARNING"
            )
            await query.message.reply_text(
                with_hint("Не разобрал, что ты выбрал. Напиши словами — отвечу."),
                parse_mode="HTML",
            )
            return

        await store.event(chat_id, "choice_clicked", answer=answer)
        await self._answer(update, query.message, answer)

    async def _handle_choice_other(self, update: Update, query, chat_id: str) -> None:
        """«Интересует другая тема» — назад к списку направлений."""
        state = store.user(chat_id)
        await store.event(chat_id, "choice_other", source=state.source)

        greeting = welcome_for(_WELCOME, state.source)
        keyboard = self._welcome_keyboard(greeting)
        await query.message.reply_text(
            with_hint("Хорошо, вернёмся к началу. С чего продолжим?"),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    async def _handle_topic_click(self, update: Update, query, chat_id: str, data: str) -> None:
        """Клик по теме = вопрос по ней. Дальше обычный путь ответа.

        Кнопки намеренно не убираются после нажатия: человек часто хочет
        вторую тему, и заставлять его ради этого печатать — терять разговор.
        """
        parsed = topic_from_callback(data)
        if parsed is None:
            log_agent_action("Telegram", f"Неизвестная кнопка темы: {data}", level="WARNING")
            return

        key, topic = parsed

        # Направление запоминаем: кнопки под следующим ответом строятся по
        # нему. Без этого человек, спросивший про бег, получал под ответом
        # закаливание и самомассаж — общий список направлений, потому что
        # source оставался пустым у всех, кто пришёл без метки с лендинга.
        # Уйти в другое направление есть чем: кнопка «Интересует другая тема».
        state = store.user(chat_id)
        if state.source != key:
            await store.save(replace(state, source=key))

        await store.event(chat_id, "topic_clicked", source=key)
        log_agent_action("Telegram", f"Тема с кнопки: «{topic}» (чат {chat_id})")
        await self._answer(update, query.message, topic)

    async def _handle_checklist(self, update: Update, context) -> None:
        if not update.message:
            return
        await self._send_gift(update.message, str(update.effective_chat.id))

    async def _send_gift(self, message, chat_id: str) -> None:
        """Отдать чек-лист-подарок и записать выдачу в аналитику."""
        if not message:
            return
        if not _GIFT_TEXT:
            log_agent_action("Bot", "Запрошен подарок, но gift_checklist.txt пуст", level="WARNING")
            return
        try:
            await message.reply_text(
                with_hint(_GIFT_TEXT), parse_mode="HTML", disable_web_page_preview=True
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send gift: {e}", level="ERROR")
            return
        await store.event(chat_id, "gift_sent")

    async def _handle_message(self, update: Update, context) -> None:
        """Free-form chat with LLM."""
        if not update.message or not update.message.text:
            return
        text = update.message.text.strip()

        # Ждём отзыв — значит это он, а не вопрос. До модели: иначе она
        # ответит на отзыв советом про здоровье.
        if await self._handle_review(update.message, str(update.effective_chat.id), text):
            return

        # Адрес почты в реплике — не вопрос к модели, а либо «вот чем я
        # плачу», либо «я уже заплатил, вот чем». Разбираем до LLM: модель
        # ответила бы про здоровье и потеряла бы платёж.
        address = email_in(text)
        if address and await self._handle_email(update.message, str(update.effective_chat.id), address):
            return

        await self._answer(update, update.message, text)

    @staticmethod
    def _chat_holding(email: str, *, besides: str) -> str:
        """Чат, которому эта почта уже открыла доступ. Пусто — свободна."""
        wanted = email.strip().lower()
        for state in store.all_users():
            if state.chat_id == besides or not state.is_premium:
                continue
            if state.email and state.email.strip().lower() == wanted:
                return state.chat_id
        return ""

    async def _handle_email(self, message, chat_id: str, address: str) -> bool:
        """Запомнить почту и, если по ней уже платили, открыть доступ.

        Возвращает True, если сообщение обработано здесь и модели не нужно.

        Проверяем у кассы, а не верим на слово: иначе доступ выпишет себе
        любой, кто назовёт чужой адрес или выдумает его. И наоборот — человек,
        заплативший на витрине, иначе остался бы без доступа, потому что там
        его `chat_id` взять неоткуда: почта — единственное, что знают обе
        стороны.
        """
        state = store.user(chat_id)
        if state.email != address:
            state = replace(state, email=address)
            await store.save(state)

        if state.is_premium:
            await message.reply_text(
                with_hint("Записал почту. Доступ у тебя и так открыт."), parse_mode="HTML"
            )
            return True

        # Одна оплата — один доступ. Касса отвечает только «по этой почте
        # платили», а не «сколько раз и кому». Без этой проверки один
        # оплаченный адрес открывал бы премиум всем, кто его назовёт: узнать
        # чужую почту нетрудно, а покупка при этом всего одна.
        taken = self._chat_holding(address, besides=chat_id)
        if taken:
            log_agent_action(
                "Payments",
                f"Почта {address} уже открыла доступ чату {taken} — чату {chat_id} отказано",
                level="WARNING",
            )
            await store.event(chat_id, "email_already_claimed")
            await message.reply_text(
                with_hint(
                    "По этой почте доступ уже открыт — в другом чате." + "\n\n"
                    "Если это твоя покупка и ты пишешь с другого аккаунта, напиши мне: "
                    "перенесу доступ сюда."
                ),
                parse_mode="HTML",
            )
            return True

        paid = False
        if config.LAVA_API_KEY:
            try:
                paid = await lavatop.has_paid(config.LAVA_API_KEY, address)
            except lavatop.LavaError as e:
                log_agent_action("Lava", f"Проверка оплаты не удалась: {e}", level="ERROR")

        if paid:
            await self._grant_premium(chat_id, "lavatop_email")
            await message.reply_text(_PREMIUM_UNLOCKED_TEXT, parse_mode="HTML")
            return True

        await message.reply_text(
            with_hint(
                "Записал почту." + "\n\n"
                "Оплаты по ней пока не вижу. Если только что заплатил — доступ "
                "откроется сам через минуту. Если ещё нет — выбери уровень, "
                "и я пришлю ссылку."
            ),
            parse_mode="HTML",
            reply_markup=self._plans_keyboard(),
        )
        return True

    async def _answer(self, update: Update, message, text: str) -> None:
        """Ответ модели на вопрос — набранный руками или выбранный кнопкой.

        Кнопка темы в приветствии — это тот же вопрос, просто человек его не
        печатал. Поэтому путь у них один: два отдельных пути разошлись бы на
        первой же правке, и расходились бы тихо.
        """
        chat_id = str(update.effective_chat.id)

        state = store.user(chat_id)
        state = replace(state, messages=state.messages + 1, last_seen_at=now_iso())
        await store.save(state)
        is_premium = state.is_premium

        if chat_id not in self._conversations:
            system_prompt = (
                _CHAT_SYSTEM_PROMPT + entry_hint(state.source) + _OFFER.system_suffix()
            )
            self._conversations[chat_id] = [{"role": "system", "content": system_prompt}]
        else:
            # LRU: перекладываем в конец, чтобы вытеснялись самые давние чаты
            self._conversations[chat_id] = self._conversations.pop(chat_id)
        while len(self._conversations) > _MAX_CONVERSATIONS:
            self._conversations.pop(next(iter(self._conversations)))

        conv = self._conversations[chat_id]

        # Где мы в разговоре. Указание живёт ровно один ход: старое снимаем,
        # новое ставим. Накопившись, они противоречили бы друг другу — «задай
        # вопрос» и «вопросов больше не задавай» подряд, — и модель слушалась
        # бы последнего в лучшем случае.
        conv[:] = [item for item in conv if not item.get("stage")]
        stage = stage_for(
            _FUNNEL_STAGES, message_number=state.messages, is_premium=is_premium
        )
        if stage:
            conv.append({"role": "system", "content": stage, "stage": True})

        conv.append({"role": "user", "content": text})

        thinking_msg = None
        try:
            thinking_msg = await message.reply_text("⏳")
        except TelegramError:
            pass

        reply = await chat_completion(conv)

        _is_error = reply.startswith("Ошибка запроса:") or reply.startswith("DeepSeek API key")
        if _is_error:
            log_agent_action("Telegram", f"LLM error: {reply}", level="ERROR")
            conv.pop()
            safe = "⚠️ Не удалось получить ответ. Попробуй ещё раз."
            try:
                if thinking_msg:
                    await thinking_msg.edit_text(safe)
                else:
                    await message.reply_text(safe)
            except TelegramError:
                pass
            return

        # Промпт запрещает markdown, но модель его всё равно иногда ставит, и
        # человек видит «**бег**» вместо жирного. Правило уже есть и уже не
        # соблюдается — поэтому чиним на выходе, а не ещё одной строкой в
        # промпте.
        if has_markdown(reply):
            log_agent_action(
                "Telegram", f"В ответе был markdown, преобразован в HTML (chat {chat_id})"
            )
            reply = to_telegram_html(reply)

        reply, price_blocked = _OFFER.sanitize_reply(reply)
        if price_blocked:
            log_agent_action(
                "Telegram",
                f"Ответ с ценой заблокирован (оффер не настроен), chat {chat_id}",
                level="ERROR",
            )
            await store.event(chat_id, "price_talk_blocked", bucket=state.bucket)
            await self._alert_admin(
                "⚠️ Модель заговорила о цене при ненастроенном оффере.\n"
                f"chat_id: <code>{chat_id}</code>\n"
                "Ответ подменён. Заполни prompts/product.txt."
            )

        conv.append({"role": "assistant", "content": reply})
        if len(conv) > _MAX_HISTORY + 1:
            self._conversations[chat_id] = [conv[0]] + conv[-_MAX_HISTORY:]

        # Условие показа — одной функцией наверху модуля: те же числа выводит
        # /status, и разойтись им теперь негде.
        show_cta = should_show_cta_now(state)

        try:
            if thinking_msg:
                await thinking_msg.delete()
                thinking_msg = None
        except TelegramError:
            pass

        # Сначала видео — потом текст. Только по теме и только один раз:
        # случайный ролик не в тему обесценивает остальные.
        await self._send_topic_video(update, state, text)

        # Кнопки под ответом — продолжение того же меню, что в приветствии.
        # Без них человек, кликнувший тему, дальше обязан печатать, и разговор
        # чаще всего заканчивается именно здесь.
        # Бот спросил «или — или»? Тогда варианты идут кнопками: написать
        # ответ словами — работа, нажать — нет, и на этой разнице разговор
        # либо продолжается, либо заканчивается.
        reply, options = choices.extract(reply)

        # Пустой текст Telegram не примет: «Message text is empty», и человек
        # не получает вообще ничего. Так и случалось, когда модель отвечала
        # одной служебной строкой с вариантами — после её удаления не
        # оставалось ни слова.
        if not reply.strip():
            log_agent_action(
                "Telegram", f"Модель вернула пустой ответ (chat {chat_id})", level="ERROR"
            )
            reply = "Не уловил вопрос. Спроси иначе — отвечу."
            options = ()

        if options:
            keyboard = self._choice_keyboard(options)
        else:
            keyboard = self._topics_keyboard(state.source, exclude=text)

        try:
            await message.reply_text(with_hint(reply), parse_mode="HTML", reply_markup=keyboard)
        except TelegramError:
            try:
                await message.reply_text(with_hint(reply), reply_markup=keyboard)
            except TelegramError as e:
                log_agent_action("Telegram", f"Failed to send reply: {e}", level="ERROR")

        log_agent_action("Telegram", f"Chat reply sent ({len(reply)} chars)")

        if show_cta:
            await self._send_offer_cta(message, state)

    @staticmethod
    def _keyboard(buttons: tuple[CtaButton, ...]) -> InlineKeyboardMarkup | None:
        """Клавиатура из кнопок, описанных в промпте.

        По одной в ряд: подписи длинные, в два столбца Telegram обрезает их
        многоточием, и человек не читает, куда ведёт кнопка.
        """
        if not buttons:
            return None
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(b.label, callback_data=b.action)] for b in buttons]
        )

    async def _send_offer_cta(self, message, state: UserState) -> None:
        """Оффер отдельным сообщением с кнопками — так виден и показ, и клик.

        Кнопок несколько и они разные по смыслу: одна ведёт к условиям, вторая
        отдаёт чек-лист. Второй выход нужен не меньше первого — человеку, для
        которого сейчас рано, иначе остаётся только промолчать.
        """
        keyboard = self._cta_keyboard()
        # Отзыв идёт впереди оффера, а не после: чужой опыт отвечает на «а у
        # меня получится» до того, как этот вопрос станет возражением. Нет
        # подходящего под направление — идём без него, выдумывать нельзя.
        testimonial = pick_testimonial(_TESTIMONIALS, state.source)
        text = _OFFER.cta_text
        if testimonial:
            text = testimonial.text + "\n\n" + text
        try:
            await message.reply_text(
                with_hint(text), parse_mode="HTML", reply_markup=keyboard
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send CTA: {e}", level="WARNING")
            return

        await store.save(replace(state, cta_shown=state.cta_shown + 1))
        await store.event(
            state.chat_id, "cta_shown", bucket=state.bucket, at_message=state.messages
        )

    # ------------------------------------------------------------------
    # Догоняющие сообщения
    # ------------------------------------------------------------------

    async def run_followups(self, *, limit: int = _FOLLOWUP_BATCH) -> dict[str, Any]:
        """Разослать созревшие догоняющие сообщения.

        Вызывается снаружи по расписанию, а не внутренним планировщиком: на
        бесплатном тарифе контейнер засыпает через 15 минут тишины, и таймер
        внутри процесса просто не проснётся. Будильник обязан быть внешним.
        """
        if not self._app or not _FOLLOWUPS:
            return {"sent": 0, "reason": "disabled"}

        now = datetime.now(timezone.utc)
        if is_quiet_hour(now):
            # Ночью очередь не разбираем: шаги никуда не денутся, сообщение
            # уйдёт утром. Разбудить человека в четыре утра — потерять его.
            return {"sent": 0, "reason": "quiet_hours"}

        sent = skipped = blocked = failed = 0
        for state in store.all_users():
            if sent >= limit:
                break

            step, advanced = next_step(
                steps=_FOLLOWUPS,
                last_seen_at=state.last_seen_at,
                followups_sent=state.followups_sent,
                is_premium=state.is_premium,
                now=now,
                offer_ready=_OFFER.is_ready,
            )

            if step is None:
                if advanced != state.followups_sent:
                    await store.save(replace(state, followups_sent=advanced))
                    skipped += 1
                continue

            try:
                await self._app.bot.send_message(
                    chat_id=state.chat_id,
                    text=with_hint(step.text),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=self._keyboard(step.buttons),
                )
            except Forbidden:
                # Человек заблокировал бота. Продолжать очередь бессмысленно:
                # доводим счётчик до конца, чтобы не долбиться каждый запуск.
                await store.save(replace(state, followups_sent=len(_FOLLOWUPS)))
                await store.event(state.chat_id, "followup_blocked", step=step.index)
                blocked += 1
                continue
            except TelegramError as e:
                # Счётчик не двигаем — шаг попробуем на следующем запуске.
                log_agent_action(
                    "Followups",
                    f"Шаг {step.index} не ушёл в чат {state.chat_id}: {e}",
                    level="WARNING",
                )
                failed += 1
                continue

            await store.save(replace(state, followups_sent=advanced))
            await store.event(
                state.chat_id,
                "followup_sent",
                step=step.index,
                bucket=state.bucket,
                source=state.source,
            )
            sent += 1
            await asyncio.sleep(_FOLLOWUP_PAUSE)

        if sent or blocked or failed:
            log_agent_action(
                "Followups",
                f"Отправлено {sent}, пропущено {skipped}, заблокировали {blocked}, ошибок {failed}",
            )
        return {"sent": sent, "skipped": skipped, "blocked": blocked, "failed": failed}

    def _sellable_plans(self) -> tuple[Plan, ...]:
        """Ступени, за которые сейчас реально можно заплатить.

        Кнопка, ведущая в никуда, хуже отсутствующей: человек нажимает,
        получает извинение и уходит.
        """

        def sellable(plan: Plan) -> bool:
            # Три двери, и любой одной достаточно: звёзды внутри Telegram,
            # счёт в кассе по ключу API, внешняя страница как запасной путь.
            by_stars = bool(plan.stars and config.PAYMENTS_ENABLED)
            by_card = bool(config.LAVA_API_KEY and _LAVA_OFFERS.get(plan.action))
            return by_stars or by_card or bool(_OFFER.purchase_url)

        return tuple(plan for plan in _PLANS if sellable(plan))

    def _plans_keyboard(self) -> "InlineKeyboardMarkup | None":
        """Кнопки ступеней — тем же способом, что и в блоке «что входит».

        Отдельная сборка разошлась бы с той: у человека появились бы две
        разные витрины в одном чате.
        """
        plans = self._sellable_plans()
        if not plans:
            return None
        return self._keyboard(tuple(CtaButton(plan.action, plan.label) for plan in plans))

    def _cta_keyboard(self) -> "InlineKeyboardMarkup | None":
        """Кнопки под оффером: ступени тарифа плюс всё, что описано в промпте.

        Подпись ступени берётся из _PLANS, а не из offer_cta.txt: цена в чате
        должна приходить из одного места, иначе в одном разговоре появятся две
        витрины с разными суммами.

        Ступень, за которую сейчас нельзя заплатить, выпадает. Её callback не
        найдётся среди _PLANS, и нажатие не сделает вообще ничего — молчащая
        кнопка читается как поломка бота.
        """
        sellable = {plan.action: plan.label for plan in self._sellable_plans()}
        buttons: list[CtaButton] = []
        for button in _OFFER.cta_buttons:
            if button.action in _PLAN_STARS:
                label = sellable.get(button.action)
                if label:
                    buttons.append(CtaButton(button.action, label))
            else:
                buttons.append(button)
        return self._keyboard(tuple(buttons))

    async def _handle_offer_click(self, query, chat_id: str) -> None:
        """Клик по «что входит» — состав и ступени, а не сразу счёт.

        Кнопка обещает рассказать, что входит и сколько стоит. Счёт вместо
        ответа выглядит так, будто рассказывать нечего: человек видит сумму,
        не увидев продукта, и закрывает чат.
        """
        state = store.user(chat_id)
        await store.event(chat_id, "offer_clicked", bucket=state.bucket, at_message=state.messages)

        if not _OFFER.is_ready:
            log_agent_action(
                "Telegram", "Offer clicked but not configured: " + "; ".join(_OFFER.blockers), level="ERROR"
            )
            await query.message.reply_text("Подробности скоро — напиши мне, всё расскажу.")
            return

        details = _OFFER.details_message()
        plans = self._sellable_plans()

        if not plans:
            log_agent_action("Telegram", "Offer clicked, but no payment path is configured", level="WARNING")
            await query.message.reply_text(
                f"{details}\n\nОплату сейчас подключаем — напиши мне, и я открою доступ вручную."
                if details
                else "Страница оплаты ещё подключается. Напиши мне — расскажу про программу.",
                parse_mode="HTML",
            )
            return

        try:
            await query.message.reply_text(details, parse_mode="HTML")
            await query.message.reply_text(
                _PLANS_TEXT,
                parse_mode="HTML",
                reply_markup=self._keyboard(
                    tuple(CtaButton(plan.action, plan.label) for plan in plans)
                ),
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send offer details: {e}", level="ERROR")
            return

        await store.event(chat_id, "offer_details_shown", bucket=state.bucket, plans=len(plans))

    async def _handle_plan_click(self, query, chat_id: str, plan: Plan) -> None:
        """Выбрана ступень кнопкой в чате."""
        await self._start_payment(query.message, chat_id, plan)

    async def _start_payment(self, message, chat_id: str, plan: Plan) -> None:
        """Ступень выбрана — предложить способ оплаты, а не форму.

        РАНЬШЕ ЗДЕСЬ БЫЛА ОШИБКА, И ДОРОГАЯ. Человек, пришедший с лендинга по
        кнопке уровня, первым же сообщением получал «пришли почту». В момент
        самого сильного намерения — анкета: не продажа, а препятствие. Почта
        нужна только карте (касса шлёт на неё чек), звёздам она не нужна
        вовсе, и спрашивать её до выбора способа значило спрашивать у всех.

        Теперь первым идёт выбор, и он в один тап. Почта — потом и только у
        того, кто выбрал карту: там она уже часть оплаты, а не анкета.
        """
        state = store.user(chat_id)
        await store.event(chat_id, "plan_clicked", plan=plan.action, bucket=state.bucket)

        ways = self._payment_ways(plan)
        if not ways:
            await message.reply_text(
                with_hint("Эту ступень пока нельзя оплатить в чате. Напиши мне — договоримся."),
                parse_mode="HTML",
            )
            return

        # Способ один — выбирать не из чего, ведём сразу. Экран с единственной
        # кнопкой это не выбор, а задержка.
        if len(ways) == 1:
            await self._pay_by(message, chat_id, plan, ways[0])
            return

        rows = [
            [
                InlineKeyboardButton(
                    _PAY_LABELS[way], callback_data=f"{_PAY_CALLBACK}{plan.action}:{way}"
                )
            ]
            for way in ways
        ]
        rows.append([InlineKeyboardButton("Сравнить уровни", callback_data="offer")])
        try:
            await message.reply_text(
                with_hint(self._plan_card(plan) + "\n\n" + "Как удобнее заплатить?"),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to offer payment ways: {e}", level="ERROR")

    @staticmethod
    def _plan_card(plan: Plan) -> str:
        """Что человек читает перед оплатой.

        Первое сообщение после лендинга не может состоять из цены и вопроса
        «как заплатить»: нажавший цену на сайте ещё не обязательно решил — он
        нажал, чтобы узнать. Карточка отвечает, что это, что даёт эта ступень
        и чем отличаются соседние: сама по себе цена не значит ничего,
        значение ей придаёт цена рядом.
        """
        card = card_for(_PLAN_CARDS, plan.action, price_in(plan.label))
        if card:
            return card

        # Карточки нет — говорим хотя бы то, что знаем наверняка. Скупое
        # сообщение здесь лучше пустого.
        log_agent_action(
            "Offer", f"Нет карточки ступени {plan.action} в plan_cards.txt", level="WARNING"
        )
        return (
            f"<b>{plan.title}</b>" + "\n\n"
            "Доступ ко всем шести направлениям сразу, 68 шагов по порядку. "
            "Открывается сразу после оплаты."
        )

    @staticmethod
    def _payment_ways(plan: Plan) -> tuple[str, ...]:
        """Чем реально можно заплатить за эту ступень прямо сейчас."""
        ways: list[str] = []
        if config.PAYMENTS_ENABLED and plan.stars:
            ways.append(_PAY_STARS)
        if (config.LAVA_API_KEY and _LAVA_OFFERS.get(plan.action)) or _OFFER.purchase_url:
            ways.append(_PAY_CARD)
        return tuple(ways)

    async def _handle_pay_click(self, query, chat_id: str, data: str) -> None:
        """Выбран способ оплаты."""
        action, _, way = data[len(_PAY_CALLBACK) :].rpartition(":")
        plan = next((p for p in _PLANS if p.action == action), None)
        if plan is None or way not in _PAY_LABELS:
            log_agent_action("Telegram", f"Неизвестная кнопка оплаты: {data}", level="WARNING")
            return
        await store.event(chat_id, "pay_way_chosen", plan=plan.action, way=way)
        await self._pay_by(query.message, chat_id, plan, way)

    async def _pay_by(self, message, chat_id: str, plan: Plan, way: str) -> None:
        """Довести до оплаты выбранным способом."""
        state = store.user(chat_id)

        if way == _PAY_STARS:
            if await self._send_invoice(message, plan):
                await store.event(chat_id, "invoice_sent", plan=plan.action, bucket=state.bucket)
            return

        if way == _PAY_PAGE:
            await self._send_storefront_link(message, chat_id, plan)
            return

        # Карта. Счёт выставляем сами, а не отправляем на витрину: витрина не
        # знает, кто пришёл, и платёж потом не с кем связать.
        offer_id = _LAVA_OFFERS.get(plan.action, "")
        if config.LAVA_API_KEY and offer_id:
            if not state.email:
                await self._ask_for_email(message, plan)
                return
            if await self._send_invoice_link(message, chat_id, state.email, plan, offer_id):
                return
            # Касса не ответила — уводим на витрину, чтобы человек всё же мог
            # заплатить. Доступ тогда выдаётся по почте, см. _handle_email.

        await self._send_storefront_link(message, chat_id, plan)

    async def _send_storefront_link(self, message, chat_id: str, plan: Plan) -> None:
        """Страница кассы — когда счёт выставить нечем или человек выбрал её сам."""
        if not _OFFER.purchase_url:
            await message.reply_text(
                with_hint("Оплату картой сейчас настраиваем. Напиши мне — открою доступ вручную."),
                parse_mode="HTML",
            )
            return

        separator = "&" if "?" in _OFFER.purchase_url else "?"
        url = f"{_OFFER.purchase_url}{separator}uid={chat_id}&plan={plan.action}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Перейти к оплате", url=url)]])
        try:
            await message.reply_text(
                with_hint(
                    f"{plan.title} — вот страница оплаты." + "\n\n"
                    "После оплаты пришли сюда почту, которой платил, — открою доступ."
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send purchase link: {e}", level="ERROR")

    @staticmethod
    async def _ask_for_email(message, plan: Plan) -> None:
        """Спросить почту — но уже после того, как человек выбрал карту.

        Здесь вопрос перестаёт быть анкетой: чек на почту — обычная часть
        оплаты картой, и человек этого ждёт. Кнопка рядом оставляет выход:
        не хочет оставлять адрес в чате — та же оплата на странице кассы,
        где он введёт его сам.
        """
        rows = []
        if _OFFER.purchase_url:
            rows.append(
                [
                    InlineKeyboardButton(
                        "Лучше на странице оплаты",
                        callback_data=f"{_PAY_CALLBACK}{plan.action}:{_PAY_PAGE}",
                    )
                ]
            )
        try:
            await message.reply_text(
                with_hint(
                    f"<b>{plan.title}</b> — принято." + "\n\n"
                    "Напиши почту: касса пришлёт на неё чек, и по ней же я узнаю твою оплату. "
                    "Ссылка придёт сюда следующим сообщением."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows) if rows else None,
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to ask for email: {e}", level="ERROR")

    async def _send_invoice_link(
        self, message, chat_id: str, email: str, plan: Plan, offer_id: str
    ) -> bool:
        """Выставить счёт в кассе и прислать кнопку оплаты."""
        try:
            invoice = await lavatop.create_invoice(
                config.LAVA_API_KEY,
                email=email,
                offer_id=offer_id,
                chat_id=chat_id,
                currency=config.LAVATOP_CURRENCY,
            )
        except lavatop.LavaError as e:
            log_agent_action("Lava", f"Счёт не выставлен: {e}", level="ERROR")
            return False

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Оплатить картой", url=invoice.payment_url)]]
        )
        try:
            await message.reply_text(
                with_hint(
                    f"{plan.title} — ссылка на оплату готова." + "\n\n"
                    "Доступ откроется сам, как только платёж пройдёт."
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send invoice link: {e}", level="ERROR")
            return False

        await store.event(chat_id, "invoice_created", plan=plan.action)
        return True

    # ------------------------------------------------------------------
    # Библиотека роликов (приватный канал)
    # ------------------------------------------------------------------

    def _topic_query(self, chat_id: str, text: str) -> str:
        """Текст, по которому ищем ролик.

        В живом диалоге половина реплик — продолжения: «ещё», «а подробнее»,
        «давай». Темы в них нет, она осталась в предыдущих сообщениях, поэтому
        при пустом сообщении ищем по нескольким последним репликам.
        """
        if tags_for_text(text):
            return text
        conv = self._conversations.get(chat_id, [])
        recent = [m["content"] for m in conv[-4:] if m.get("role") != "system"]
        return "\n".join([*recent, text])

    def _ensure_library(self) -> None:
        """Собрать библиотеку по живому трафику, если прогрев её не наполнил.

        Прогрев при запуске конкурирует с поднятием поллинга и переживает не
        каждый старт. Здесь задача рождается внутри обработчика сообщения —
        никаких гонок со стартом приложения.
        """
        if len(library) or not config.CONTENT_CHANNEL_ID:
            return
        if self._library_task and not self._library_task.done():
            return
        log_agent_action("Content", "Библиотека пуста — собираю по ходу диалога")
        self._library_task = asyncio.create_task(self._bootstrap_content())
        self._library_task.add_done_callback(
            lambda t: log_agent_action(
                "Content",
                f"Сбор библиотеки: {len(library)} роликов"
                + (f", ошибка {t.exception()!r}" if not t.cancelled() and t.exception() else ""),
            )
        )

    async def _send_topic_video(self, update: Update, state: UserState, text: str) -> None:
        """Отправить релевантный ролик из канала, если он есть и ещё не показан."""
        if not config.CONTENT_CHANNEL_ID or not self._app:
            return

        self._ensure_library()

        query = self._topic_query(state.chat_id, text)
        item = library.match(query, is_premium=state.is_premium, exclude=state.seen_content)
        if not item:
            # Без этой строки «не нашёл» и «не отправил» выглядят одинаково —
            # то есть никак.
            wanted = ", ".join(tags_for_text(query)) or "тем не распознано"
            log_agent_action(
                "Content",
                f"Ролик не подобран (в запросе: {wanted}; в библиотеке: {len(library)}) "
                f"— вопрос: «{text[:60]}»",
            )
            return

        try:
            await self._app.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=config.CONTENT_CHANNEL_ID,
                message_id=item.message_id,
            )
        except TelegramError as e:
            log_agent_action("Telegram", f"Failed to send video {item.message_id}: {e}", level="WARNING")
            return

        log_agent_action(
            "Content",
            f"Ролик #{item.message_id} [{', '.join(library.topics_of(item))}] отправлен в чат {state.chat_id}",
        )
        await store.save(replace(state, seen_content=state.seen_content + (item.message_id,)))
        await store.event(
            state.chat_id, "video_sent", message_id=item.message_id, title=item.title
        )

    async def _handle_channel_post(self, update: Update, context) -> None:
        """Индексировать новый пост в канале-библиотеке."""
        post = update.channel_post
        if not post or not config.CONTENT_CHANNEL_ID:
            return
        if str(post.chat_id) != str(config.CONTENT_CHANNEL_ID):
            return
        if not (post.video or post.video_note or post.animation):
            return

        item = parse_caption(post.caption, post.message_id)
        await library.upsert(item)
        log_agent_action(
            "Content",
            f"Indexed post {item.message_id}: tags={','.join(item.tags) or '—'} tier={item.tier}",
        )

    async def _deny_non_admin(self, update: Update, command: str) -> bool:
        """True, если вызвавший не админ. Молчаливый отказ неотличим от
        «команда не дошла», поэтому всегда отвечаем и логируем реальный id."""
        chat_id = str(update.effective_chat.id)
        if config.ADMIN_CHAT_ID and chat_id == str(config.ADMIN_CHAT_ID):
            log_agent_action("Telegram", f"{command} запущена админом {chat_id}")
            return False

        log_agent_action(
            "Telegram",
            f"{command} отклонена: chat_id={chat_id}, "
            f"ADMIN_CHAT_ID={config.ADMIN_CHAT_ID or 'не задан'}",
            level="WARNING",
        )
        try:
            await update.message.reply_text(
                "Команда только для администратора.\n"
                f"Твой chat_id: <code>{chat_id}</code>\n"
                "Если это ты — впиши его в ADMIN_CHAT_ID на Render.",
                parse_mode="HTML",
            )
        except TelegramError:
            pass
        return True

    async def _scan_channel(self, probe_chat: str, limit: int) -> list[ContentItem]:
        """Собрать ролики, уже лежащие в канале.

        Bot API не отдаёт историю канала, поэтому каждый пост пересылается и
        сразу удаляется — единственный способ увидеть подпись.
        """
        found: list[ContentItem] = []
        for message_id in range(1, limit + 1):
            try:
                forwarded = await self._app.bot.forward_message(
                    chat_id=probe_chat,
                    from_chat_id=config.CONTENT_CHANNEL_ID,
                    message_id=message_id,
                )
            except TelegramError:
                continue  # дырка в нумерации или пост удалён
            if forwarded.video or forwarded.video_note or forwarded.animation:
                found.append(parse_caption(forwarded.caption, message_id))
            try:
                await self._app.bot.delete_message(
                    chat_id=probe_chat, message_id=forwarded.message_id
                )
            except TelegramError:
                pass
            await asyncio.sleep(_REINDEX_PAUSE)
        return found

    def _on_warmup_done(self, task: "asyncio.Task") -> None:
        """Молчаливо умерший прогрев — худший вариант: роликов нет, причин нет."""
        if task.cancelled():
            log_agent_action("Telegram", "Прогрев отменён", level="WARNING")
            return
        error = task.exception()
        if error:
            log_agent_action("Telegram", f"Прогрев упал: {error!r}", level="ERROR")
        else:
            log_agent_action("Telegram", "Прогрев завершён")

    async def _warmup(self) -> None:
        """Подтянуть состояние и контент уже после того, как бот отвечает."""
        try:
            await store.start()
            await library.load()
            self._warn_about_unreachable_premium()
            log_agent_action("Content", f"Библиотека при старте: {len(library)} роликов")
            await self._bootstrap_content()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log_agent_action("Telegram", f"Warmup failed: {e} — бот продолжает работать", level="ERROR")

    def _report_library(self) -> None:
        """Показать, по каким темам ролики реально подберутся.

        Ролик без тегов и без узнаваемого названия молча не подберётся никогда —
        это надо видеть, а не гадать.
        """
        for item in sorted(library._items.values(), key=lambda i: i.message_id):
            topics = ", ".join(sorted(library.topics_of(item))) or "НЕТ ТЕМ"
            log_agent_action(
                "Content", f"  #{item.message_id}: [{topics}] {item.title[:60] or '(без подписи)'}"
            )
        blind = library.untagged()
        if blind:
            log_agent_action(
                "Content",
                f"{len(blind)} роликов не подберутся ни по одному запросу. "
                "Допишите в подпись поста теги, например: #закаливание #снег",
                level="WARNING",
            )

    async def _await_channel_access(self) -> bool:
        """Дождаться, пока бота добавят в канал.

        Проверка только на старте бесполезна: бота добавляют руками и уже после
        того, как сервис поднялся. Поэтому пробуем повторно — тогда ролики
        появятся сами, без перезапуска.
        """
        waited = 0
        complained = False
        while True:
            try:
                chat = await self._app.bot.get_chat(config.CONTENT_CHANNEL_ID)
                log_agent_action("Content", f"Канал доступен: {chat.title or chat.id}")
                return True
            except TelegramError as e:
                if not complained:
                    log_agent_action(
                        "Content",
                        f"НЕТ ДОСТУПА К КАНАЛУ {config.CONTENT_CHANNEL_ID} ({e}). "
                        "Добавьте бота администратором в канал — проверяю раз в минуту, "
                        "перезапуск не нужен. Если бот уже добавлен, сверьте ID: "
                        "он должен начинаться с -100 и принадлежать каналу.",
                        level="ERROR",
                    )
                    complained = True
                if waited >= _BOOTSTRAP_MAX_WAIT:
                    log_agent_action(
                        "Content",
                        f"Канал так и не открылся за {_BOOTSTRAP_MAX_WAIT // 60} минут — "
                        "перестаю проверять до следующего запуска",
                        level="ERROR",
                    )
                    return False
                await asyncio.sleep(_BOOTSTRAP_RETRY)
                waited += _BOOTSTRAP_RETRY

    async def _bootstrap_content(self) -> None:
        """Наполнить библиотеку без участия человека.

        Сначала подбираем то, что уже лежит в канале; если там пусто — заливаем
        легаси-ролики. Иначе индекс пришлось бы каждый раз восстанавливать
        руками, а команду в Telegram может нажать только владелец.
        """
        if not config.CONTENT_CHANNEL_ID or not self._app:
            return
        if len(library):
            return
        # Прогрев и ленивый сбор могут стартовать одновременно; два перебора
        # канала подряд — лишний десяток forward/delete и риск словить лимит.
        if self._bootstrap_running:
            return
        self._bootstrap_running = True
        try:
            await self._do_bootstrap()
        finally:
            self._bootstrap_running = False

    async def _do_bootstrap(self) -> None:
        if not await self._await_channel_access():
            return

        probe_chat = str(config.ADMIN_CHAT_ID or config.CONTENT_CHANNEL_ID)
        try:
            found = await self._scan_channel(probe_chat, _BOOTSTRAP_SCAN)
            if found:
                await library.upsert_many(found)
                log_agent_action("Content", f"Авто-индексация: найдено роликов {len(found)}")
                self._report_library()
                return

            log_agent_action("Content", "В канале роликов нет — переношу легаси")
            moved = 0
            for tag, file_id in _LEGACY_VIDEOS.items():
                try:
                    await self._app.bot.send_video(
                        chat_id=config.CONTENT_CHANNEL_ID,
                        video=file_id,
                        caption=f"#{tag}\ntier: free",
                    )
                    moved += 1
                except TelegramError as e:
                    log_agent_action("Content", f"Легаси-ролик {tag} не перенесён: {e}", level="ERROR")
                await asyncio.sleep(_REINDEX_PAUSE)
            log_agent_action("Content", f"Перенесено легаси-роликов: {moved}")
        except Exception as e:  # старт бота важнее наполнения библиотеки
            log_agent_action("Content", f"Авто-наполнение прервано: {e}", level="ERROR")

    async def _handle_status(self, update: Update, context) -> None:
        """Что настроено, а что нет — видно прямо из бота."""
        if not update.message or await self._deny_non_admin(update, "/status"):
            return

        def mark(ok: bool) -> str:
            return "✅" if ok else "❌"

        offer_line = (
            f"{mark(_OFFER.is_ready)} оффер"
            + (" (ДЕМО-данные)" if _OFFER.is_demo else "")
            + ("" if _OFFER.is_ready else ": " + "; ".join(_OFFER.blockers))
        )
        lines = [
            "<b>Состояние бота</b>",
            f"{mark(bool(config.CONTENT_CHANNEL_ID))} канал с роликами",
            f"{mark(len(library) > 0)} роликов в индексе: {len(library)}",
            offer_line,
            f"{mark(True)} оффер на ответе №{_OFFER_TURN} и дальше",
            f"{'💳' if config.PAYMENTS_ENABLED else '➖'} касса в боте: "
            + ("включена" if config.PAYMENTS_ENABLED else "выключена"),
        ]

        # Своя строка воронки. Без неё «почему мне не пришёл оффер» не
        # отвечается вообще ничем: показ зависит от трёх чисел, которые лежат
        # в базе и наружу ниоткуда не видны. Дважды подряд ответом было
        # «должно прийти» — а не приходило, и причина была здесь.
        state = store.user(str(update.effective_chat.id))
        # Следующий ответ бота будет на единицу дальше по счётчику — /status
        # сам его не увеличивает.
        due = should_show_cta_now(replace(state, messages=state.messages + 1))
        lines += [
            "",
            "<b>Твоя строка воронки</b>",
            f"ответов бота: {state.messages}",
            f"оффер показан раз: {state.cta_shown} из {_CTA_MAX_TIMES}",
            f"доступ оплачен: {'да' if state.is_premium else 'нет'}",
            f"направление: {state.source or '—'}",
            f"{mark(due)} оффер под следующим ответом: " + ("да" if due else "нет"),
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _handle_reindex(self, update: Update, context) -> None:
        """/reindex <from_id> <to_id> — пересобрать индекс по постам канала.

        Bot API не умеет читать историю канала, поэтому каждый пост
        пересылается сюда (единственный способ увидеть подпись) и сразу
        удаляется.
        """
        if not update.message or await self._deny_non_admin(update, "/reindex"):
            return
        if not config.CONTENT_CHANNEL_ID:
            await update.message.reply_text("CONTENT_CHANNEL_ID не задан.")
            return

        args = getattr(context, "args", None) or []
        if len(args) != 2 or not all(a.isdigit() for a in args):
            await update.message.reply_text("Формат: /reindex <от_id> <до_id>")
            return

        start_id, end_id = int(args[0]), int(args[1])
        if end_id < start_id or end_id - start_id >= _REINDEX_MAX_SPAN:
            await update.message.reply_text(f"Диапазон до {_REINDEX_MAX_SPAN} сообщений.")
            return

        progress = await update.message.reply_text(f"⏳ Сканирую {start_id}–{end_id}...")
        count = await self.reindex_range(str(update.effective_chat.id), start_id, end_id)
        await progress.edit_text(
            f"✅ Проиндексировано роликов: {count}. Всего в библиотеке: {len(library)}"
        )

    async def reindex_range(self, via_chat: str, start_id: int, end_id: int) -> int:
        """Пересобрать индекс по диапазону постов канала.

        Bot API не умеет читать историю канала, поэтому каждый пост
        пересылается в чат `via_chat` — это единственный способ увидеть
        подпись, — и сразу удаляется.

        Отдельным методом, а не внутри команды: тем же кодом пользуется
        служебный маршрут. Своих постов бот в `channel_post` не получает
        вовсе, поэтому после загрузки роликов его же токеном переиндексация —
        не запасной путь, а единственный.
        """
        found: list[ContentItem] = []
        for message_id in range(start_id, end_id + 1):
            try:
                forwarded = await self._app.bot.forward_message(
                    chat_id=via_chat,
                    from_chat_id=config.CONTENT_CHANNEL_ID,
                    message_id=message_id,
                )
            except TelegramError:
                continue  # дырка в нумерации или пост удалён
            if forwarded.video or forwarded.video_note or forwarded.animation:
                found.append(parse_caption(forwarded.caption, message_id))
            try:
                await self._app.bot.delete_message(
                    chat_id=via_chat, message_id=forwarded.message_id
                )
            except TelegramError:
                pass
            await asyncio.sleep(_REINDEX_PAUSE)

        return await library.upsert_many(found)

    async def _handle_migrate_legacy(self, update: Update, context) -> None:
        """Перелить ролики из старых file_id в канал — без перезаливки файлов."""
        if not update.message or await self._deny_non_admin(update, "/migrate_legacy"):
            return
        if not config.CONTENT_CHANNEL_ID:
            await update.message.reply_text("CONTENT_CHANNEL_ID не задан.")
            return

        moved = 0
        errors: list[str] = []
        for tag, file_id in _LEGACY_VIDEOS.items():
            try:
                await self._app.bot.send_video(
                    chat_id=config.CONTENT_CHANNEL_ID,
                    video=file_id,
                    caption=f"#{tag}\ntier: free",
                )
                moved += 1
            except TelegramError as e:
                errors.append(f"{tag}: {e}")
                log_agent_action("Telegram", f"Legacy migration failed for {tag}: {e}", level="ERROR")
            await asyncio.sleep(_REINDEX_PAUSE)

        log_agent_action(
            "Telegram", f"/migrate_legacy: перенесено {moved} из {len(_LEGACY_VIDEOS)}"
        )
        report = f"Перенесено в канал: {moved} из {len(_LEGACY_VIDEOS)}."
        if errors:
            report += "\n\nОшибки:\n" + "\n".join(errors[:5])
        else:
            report += "\nПосты проиндексируются автоматически как обычные публикации."
        await update.message.reply_text(report)



telegram_bot = TelegramBot()
