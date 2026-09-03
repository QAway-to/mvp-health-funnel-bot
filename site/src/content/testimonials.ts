import { directions } from './directions';
import { DEFAULT_LANG, type Lang } from '../i18n';

/**
 * Отзывы. Заполняет заказчик — выдумывать их нельзя.
 *
 * Пока массив пуст, компонент `Testimonials` не отрисовывает секцию вообще,
 * а не показывает пустую рамку. Формат «было → стало»: `before` и `after`
 * дают читаемую пару без пересказа.
 *
 * `segment` определяет, где отзыв показывается. Это либо `slug` направления
 * из реестра (`komfort`, `sila`, `son`, `zaryadka`, `zakalivanie`, `massazh`),
 * либо `all` — тогда отзыв виден везде, включая главную. Беговые лендинги
 * ведут два своих сегмента: `komfort` и `sila`.
 */

/** Сегменты беговых лендингов: направления `beg` как страницы не существует. */
const RUNNING_SEGMENTS = ['komfort', 'sila'] as const;

export type TestimonialSegment = string;

export interface Testimonial {
  readonly name: string;
  /** Возраст или короткий контекст: «42 года», «жим 120 кг». Необязательно. */
  readonly context?: string;
  readonly before: string;
  readonly after: string;
  /** Фото в public/img/testimonials/. Пусто — покажем инициал. */
  readonly photo?: string;
  readonly segment: TestimonialSegment;
  /**
   * Откуда отзыв, если не из чата с ботом: «из книги Федерации».
   *
   * Поле не украшение. Отзыв из книги и отзыв покупателя читаются по-разному,
   * и умолчать о разнице — значит выдать одно за другое. Подпись стоит рядом
   * с отзывом, а не в сноске внизу страницы.
   */
  readonly source?: string;
  /**
   * Английская версия того же отзыва.
   *
   * Отзыв настоящий, и на английской странице он должен остаться настоящим:
   * переводится текст, не факты и не сроки. Подпись об источнике переводится
   * вместе с ним — «из книги Федерации» без перевода читалось бы как имя.
   *
   * Нет перевода — отзыв на английской странице не показывается вовсе.
   * Кириллица в англоязычном блоке отзывов хуже, чем блок без отзыва: она
   * сообщает, что страница собрана наспех, ровно там, где мы просим доверия.
   */
  readonly en?: {
    readonly name: string;
    readonly context?: string;
    readonly before: string;
    readonly after: string;
    readonly source?: string;
  };
}

export const testimonials: readonly Testimonial[] = [
  // Оба отзыва — из книги Федерации «ЗагартовуваннЯ», раздел «Відгуки від
  // учасників». Сокращены и переведены на русский; смысл, факты и сроки не
  // менялись. Имена настоящие, поэтому и стоят.
  //
  // Ничего выдуманного здесь быть не должно. Пустой список честнее
  // правдоподобного вымысла: придуманный отзыв ломает доверие ко всему
  // остальному на странице и проверяется одним вопросом — «а можно с ним
  // связаться?».
  {
    name: 'Дмитрий',
    context: 'тренер Федерации',
    before:
      'Всё детство провёл по больницам, болел всем подряд. Родители приучили бояться холода. В 2020-м начал обливаться сам, но делал вслепую — и периодически всё равно болел.',
    after:
      'Больше года закаливается осознанно. Болеет раз в полгода и выздоравливает быстрее. Больше всего любит росу и погружение — к погружению готовился не один месяц.',
    segment: 'zakalivanie',
    source: 'из книги Федерации',
    en: {
      name: 'Dmitry',
      context: 'Federation coach',
      before:
        'Spent his childhood in and out of hospitals, caught everything going. His parents taught him to fear the cold. He started pouring cold water in 2020, but blindly — and still got ill on and off.',
      after:
        'More than a year of doing it deliberately. Falls ill about twice a year and recovers faster. His favourites are dew and full immersion — the immersion took him months to prepare for.',
      source: 'from the Federation book',
    },
  },
  {
    name: 'Евгений',
    context: 'участник Федерации',
    before:
      'В 2019-м жил в общежитии, где целый месяц приходилось мыться холодной водой. Не по своему желанию.',
    after:
      'За тот месяц заметил, что день проходит легче. Потом разобрался с методиками осознанно и до сих пор моется в прохладной воде.',
    segment: 'all',
    source: 'из книги Федерации',
    en: {
      name: 'Yevgeny',
      context: 'Federation member',
      before:
        'In 2019 he lived in a dorm where the water was cold for a whole month. Not by choice.',
      after:
        'Over that month he noticed the days came easier. Later he went through the methods deliberately, and he still washes in cool water.',
      source: 'from the Federation book',
    },
  },
];

/**
 * Допустимые значения `segment` — направления из реестра плюс два беговых
 * сегмента и `all`. Проверяются на сборке: опечатка в слаге означала бы,
 * что отзыв молча не показывается нигде.
 */
const KNOWN_SEGMENTS: readonly string[] = [
  'all',
  ...RUNNING_SEGMENTS,
  ...directions.map((direction) => direction.slug),
];

const unknown = testimonials.filter((item) => !KNOWN_SEGMENTS.includes(item.segment));

if (unknown.length > 0) {
  throw new Error(
    `[testimonials] неизвестный сегмент: ${unknown.map((item) => `${item.name} → ${item.segment}`).join(', ')}`,
  );
}

/**
 * Отзывы для страницы: свои плюс сквозные, на языке страницы.
 *
 * Английская версия отдаёт только переведённые отзывы: непереведённый просто
 * не показывается. Секция сама решает, рисоваться ли ей, — значит английская
 * страница без переводов останется без блока, а не с русским текстом внутри.
 */
export const testimonialsFor = (
  segment: string,
  lang: Lang = DEFAULT_LANG,
): readonly Testimonial[] => {
  const own = testimonials.filter((item) => item.segment === segment || item.segment === 'all');
  if (lang === DEFAULT_LANG) return own;

  return own
    .filter((item) => item.en !== undefined)
    .map((item) => ({ ...item, ...item.en }));
};
