/**
 * Структура контента лендинга.
 *
 * Одной схемой описываются и два беговых лендинга из хендоффа, и страницы
 * остальных направлений. Разница в том, что у направления материала меньше:
 * поэтому всё, кроме первого экрана, вопросов и финального призыва —
 * необязательно. Секция без данных просто не рисуется, а не показывает
 * пустую рамку.
 */

export interface NavLink {
  readonly label: string;
  readonly href: string;
}

export interface Meta {
  readonly title: string;
  readonly description: string;
  /** Путь к OG-картинке относительно `public/`. */
  readonly ogImage: string;
}

/** Вторичная кнопка: «узнать больше», без обязательств. */
export interface HeroSecondary {
  readonly label: string;
  readonly href: string;
  /** Место в аналитике. */
  readonly placement: string;
}

export interface Hero {
  readonly kicker: string;
  readonly title: string;
  readonly lead: string;
  readonly image: string;
  /** Затемнение фонового фото, если в макете задан filter: brightness(). */
  readonly imageBrightness?: number;
  readonly trust: readonly string[];
  /**
   * Куда ведёт вторая кнопка. Не задана — предлагаем посмотреть состав
   * направления.
   *
   * Демо-урок сюда ставят только там, где он по теме: ролик у нас один и он
   * про технику бега, а на странице сна кнопка «посмотреть демо-урок» вела бы
   * человека к разбору стопы.
   */
  readonly secondary?: HeroSecondary;
}

export interface MirrorCard {
  readonly label: string;
  readonly title: string;
  readonly text: string;
}

export interface Mirror {
  readonly kicker: string;
  readonly title: string;
  readonly cards: readonly MirrorCard[];
  readonly closer: string;
}

export interface ReasonCard {
  readonly num: string;
  readonly title: string;
  readonly text: string;
  readonly solution: string;
}

export interface Reasons {
  readonly kicker: string;
  readonly title: string;
  readonly cards: readonly ReasonCard[];
}

export interface TitledText {
  readonly title: string;
  readonly text: string;
}

export interface Mechanism {
  readonly kicker: string;
  readonly title: string;
  readonly items: readonly TitledText[];
  readonly note: string;
  readonly image: string;
  readonly imageAlt: string;
}

export interface Effects {
  readonly kicker: string;
  readonly title: string;
  readonly items: readonly TitledText[];
}

export interface ProgramBlock extends TitledText {
  readonly label: string;
}

export interface Program {
  readonly kicker: string;
  readonly title: string;
  readonly blocks: readonly ProgramBlock[];
  readonly extras: readonly TitledText[];
}

export interface PlanItem extends TitledText {
  readonly label: string;
  /** Подстрочник через border-top — только у варианта `weeks` (лендинг Б). */
  readonly note?: string;
}

export interface Plan {
  readonly kicker: string;
  readonly title: string;
  /** `days` — карточки-линии (А), `weeks` — карточки с фоном (Б). */
  readonly variant: 'days' | 'weeks';
  readonly items: readonly PlanItem[];
  readonly closer: string;
}

export interface Metric {
  readonly value: string;
  readonly label: string;
}

export interface Author {
  readonly kicker: string;
  readonly title: string;
  readonly text: string;
  readonly image: string;
  readonly imageAlt: string;
  /** Сторона, с которой стоит фото: А — слева, Б — справа. */
  readonly imageSide: 'left' | 'right';
  readonly metrics: readonly Metric[];
}

/**
 * Уровень подписки: то, что видно на карточке.
 *
 * Цены и ссылки оплаты здесь нет — она в site.subscription.tiers и
 * подставляется по `id`. Так коммерческие данные остаются в одном месте,
 * а копирайт правится без риска задеть ссылку на оплату.
 */
export interface SubscriptionTier {
  /** Ключ уровня: связывает контент с ценой и уезжает в аналитику. */
  readonly id: string;
  readonly label: string;
  readonly text: string;
  readonly features: readonly string[];
  /** Подпись кнопки, когда оплата заведена. Иначе зовём на бесплатную ступень. */
  readonly ctaLabel: string;
  /**
   * Метка над карточкой («РЕКОМЕНДУЮ»). Она же помечает уровень как основной:
   * его подставляют мобильная панель и финальный призыв. Ставится ровно
   * одному уровню — два «рекомендую» не рекомендуют ничего.
   */
  readonly badge?: string;
}

/**
 * Подписи внутри блока подписки: поп-ап оплаты, служебные строки, сноски.
 *
 * Раньше они стояли прямо в разметке `Subscription.astro`, и это работало
 * ровно до второго языка: английская страница показывала цены русскими
 * словами и русский поп-ап оплаты. Теперь текста в компоненте нет вообще —
 * он весь приходит из контента того языка, на котором открыта страница.
 */
export interface SubscriptionUi {
  /** Заголовок поп-апа выбора способа оплаты. */
  readonly payTitle: string;
  readonly payLead: string;
  readonly payCard: string;
  readonly payCardNote: string;
  readonly payStars: string;
  readonly payStarsNote: string;
  readonly payClose: string;
  /** Заголовок блока «что открыто на любом уровне». */
  readonly includedTitle: string;
  /** Пометка у направления, раскрытого материалами, а не курсом. */
  readonly materialsLabel: string;
  /**
   * Сноска про эту пометку. Получает названия направлений списком, а не
   * склеенной строкой: «и» против «and» — решение языка, и принимать его
   * должен контент, а не разметка.
   *
   * Названия берутся в кавычки. «Массаж и самомассаж» — само по себе
   * перечисление, и без кавычек строка читалась как три направления вместо
   * двух: «зарядка и массаж и самомассаж».
   */
  readonly materialsNote: (names: readonly string[]) => string;
  /** Строка «готовятся: …». Получает названия направлений списком. */
  readonly soonNote: (names: readonly string[]) => string;
  /** Что показываем, пока ни у одного уровня нет ссылки оплаты. */
  readonly pendingCta: string;
  readonly pendingNote: string;
  /** Подпись кнопки уровня, у которого оплаты ещё нет. */
  readonly freeCta: string;
}

/**
 * Блок подписки. Продукт на сайте один — доступ ко всем направлениям сразу,
 * а уровни отличаются обратной связью, а не объёмом материалов.
 * Список направлений берётся из реестра, а не переписывается в контенте.
 */
export interface Subscription {
  readonly kicker: string;
  readonly title: string;
  readonly lead: string;
  /** Что даёт подписка на любом уровне. */
  readonly features: readonly string[];
  /** По возрастанию цены: читают слева направо. */
  readonly tiers: readonly SubscriptionTier[];
  /** Период списания рядом с ценой: «в месяц», «per month». */
  readonly period: string;
  /** Строка под кнопкой: условия отмены. Пусто — строки нет. */
  readonly terms: string;
  /** Вторая дверь к тому же доступу — оплата звёздами. */
  readonly starsLabel: string;
  readonly ui: SubscriptionUi;
  /**
   * Предупреждение рядом с ценой. Нужно только английской версии: материал
   * русский, и человек должен прочитать это до оплаты, а не после.
   */
  readonly warning?: string;
}

export interface FaqItem {
  readonly question: string;
  readonly answer: string;
}

export interface Faq {
  readonly kicker: string;
  readonly title: string;
  readonly items: readonly FaqItem[];
}

export interface FinalCta {
  readonly title: string;
  readonly lead: string;
  /** Строка под кнопкой. Пусто — строки нет: обещать нечего. */
  readonly note?: string;
  readonly image: string;
  readonly imageBrightness: number;
}

export interface LandingContent {
  readonly slug: string;
  readonly brand: string;
  readonly meta: Meta;
  readonly nav: readonly NavLink[];
  readonly hero: Hero;
  readonly mirror?: Mirror;
  readonly reasons?: Reasons;
  readonly mechanism?: Mechanism;
  /** Секция «Шесть эффектов» есть только на лендинге Б. */
  readonly effects?: Effects;
  readonly program?: Program;
  readonly plan?: Plan;
  /** Блок автора общий для всего сайта, но подпись у направлений своя. */
  readonly author?: Author;
  readonly faq: Faq;
  readonly finalCta: FinalCta;
}
