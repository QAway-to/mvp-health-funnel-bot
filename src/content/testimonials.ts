/**
 * Отзывы. Заполняет заказчик — выдумывать их нельзя.
 *
 * Пока массив пуст, компонент `Testimonials` не отрисовывает секцию вообще,
 * а не показывает пустую рамку. Формат «было → стало»: `before` и `after`
 * дают читаемую пару без пересказа.
 *
 * `segment` определяет, где отзыв показывается:
 *   'pain'  — только на /bez-diskomforta/ (про уход дискомфорта)
 *   'gym'   — только на /sila/ (про выносливость и форму)
 *   'both'  — везде, включая главную
 */

export type TestimonialSegment = 'pain' | 'gym' | 'both';

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
  // Пример структуры — раскомментировать и заменить реальными данными:
  // {
  //   name: 'Имя',
  //   context: '42 года',
  //   before: 'Что было до: что мешало, что не получалось.',
  //   after: 'Что стало: через сколько и что именно изменилось.',
  //   photo: '/img/testimonials/imya.jpg',
  //   segment: 'pain',
  // },
];

export const testimonialsFor = (segment: TestimonialSegment): readonly Testimonial[] =>
  testimonials.filter((item) => item.segment === segment || item.segment === 'both');
