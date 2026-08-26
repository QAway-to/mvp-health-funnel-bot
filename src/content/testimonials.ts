import { directions } from './directions';

/**
 * Отзывы. Заполняет заказчик — выдумывать их нельзя.
 *
 * Пока массив пуст, компонент `Testimonials` не отрисовывает секцию вообще,
 * а не показывает пустую рамку. Формат «было → стало»: `before` и `after`
 * дают читаемую пару без пересказа.
 *
 * `segment` определяет, где отзыв показывается. Это либо `slug` направления
 * из реестра (`komfort`, `sila`, `son`, `zaryadka`, `samomassazh`, `massazh`),
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
}

export const testimonials: readonly Testimonial[] = [
  // Пример структуры — раскомментировать и заменить реальными данными.
  // Ничего выдуманного здесь быть не должно: пустой список честнее
  // правдоподобного вымысла, и секция просто не покажется.
  // {
  //   name: 'Имя',
  //   context: '42 года',
  //   before: 'Что было до: что мешало, что не получалось.',
  //   after: 'Что стало: через сколько и что именно изменилось.',
  //   photo: '/img/testimonials/imya.jpg',
  //   segment: 'son',
  // },
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

/** Отзывы для страницы: свои плюс сквозные. */
export const testimonialsFor = (segment: string): readonly Testimonial[] =>
  testimonials.filter((item) => item.segment === segment || item.segment === 'all');
