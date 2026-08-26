/**
 * Реестр направлений Федерации здоровья.
 *
 * План проекта называет десять тем: бег, сон, еда, зарядка, тренировки,
 * голодание, похудение, самомассаж, закаливание, вредные привычки. Массаж
 * добавлен одиннадцатым — под него есть отдельный материал заказчика.
 *
 * Реестр — единственный источник правды о том, какие направления существуют
 * и какие из них уже открыты. Из него собираются главная, навигация и список
 * того, что входит в подписку: добавить направление = добавить сюда запись,
 * а не править пять файлов и не забыть шестой.
 */

/**
 * `live` — материал готов, направление входит в подписку.
 * `soon` — тема заявлена, материала на полноценный курс пока нет.
 *
 * Статус — про **продукт**, а не про страницу. У направления может быть
 * готовый лендинг и при этом статус `soon`: страница собирает заявки в бота,
 * но в состав подписки направление не заявляется. Обещать в подписке то,
 * что не открывается, — самый дорогой способ получить возврат.
 */
export type DirectionStatus = 'live' | 'soon';

export interface Direction {
  /** Стабильный ключ: уезжает в аналитику и в метку сегмента для бота. */
  readonly slug: string;
  readonly title: string;
  /** Обещание в одну строку — то, что человек получит, а не тема урока. */
  readonly promise: string;
  readonly status: DirectionStatus;
  /** Адрес страницы, если она есть. У `soon` может быть, а может и не быть. */
  readonly href?: string;
  /** Фон карточки на главной. У `soon` может отсутствовать. */
  readonly image?: string;
}

export const directions: readonly Direction[] = [
  {
    slug: 'beg',
    title: 'Бег',
    promise: 'Бегать легко и без тяжести наутро — за счёт техники, а не километров.',
    status: 'live',
    href: '/beg/',
    image: '/img/race-road.jpg',
  },
  {
    slug: 'son',
    title: 'Сон',
    promise: 'Засыпать вовремя и просыпаться выспавшимся — десять привычек вечера.',
    status: 'live',
    href: '/son/',
    image: '/img/son-night.jpg',
  },
  {
    slug: 'zaryadka',
    title: 'Зарядка',
    promise: 'Утро по порядку: от подъёма до первого приёма пищи, без спешки.',
    status: 'soon',
    href: '/zaryadka/',
    image: '/img/zaryadka-sunrise.jpg',
  },
  {
    slug: 'samomassazh',
    title: 'Самомассаж',
    promise: 'Снимать напряжение своими руками — пятнадцать минут и шесть приёмов.',
    status: 'soon',
    href: '/samomassazh/',
    image: '/img/samomassazh-face.jpg',
  },
  {
    slug: 'massazh',
    title: 'Массаж',
    promise: 'Разобраться в видах массажа и выбрать свой, не переплачивая за незнание.',
    status: 'live',
    href: '/massazh/',
    image: '/img/massazh-spa.jpg',
  },
  {
    slug: 'eda',
    title: 'Еда',
    promise: 'Что и когда есть, чтобы хватало сил на день.',
    status: 'soon',
  },
  {
    slug: 'trenirovki',
    title: 'Тренировки',
    promise: 'Силовые без зала: нагрузка, которую выдерживает обычная неделя.',
    status: 'soon',
  },
  {
    slug: 'golodanie',
    title: 'Голодание',
    promise: 'Паузы в еде: зачем, кому и как входить и выходить.',
    status: 'soon',
  },
  {
    slug: 'pohudenie',
    title: 'Похудение',
    promise: 'Вес как следствие привычек, а не диеты на три недели.',
    status: 'soon',
  },
  {
    slug: 'zakalivanie',
    title: 'Закаливание',
    promise: 'Холод по порядку: от прохладной воды до снега, без геройства.',
    status: 'soon',
  },
  {
    slug: 'vrednye-privychki',
    title: 'Вредные привычки',
    promise: 'Чем заменить то, что держит, — и почему запрет не работает.',
    status: 'soon',
  },
];

export const liveDirections: readonly Direction[] = directions.filter(
  (direction) => direction.status === 'live',
);

export const soonDirections: readonly Direction[] = directions.filter(
  (direction) => direction.status === 'soon',
);
