import type { NavLink } from './types';

/** Якорная навигация одинакова на всех страницах направлений. */
export const nav: readonly NavLink[] = [
  { label: 'Программа', href: '#program' },
  { label: 'Цена', href: '#price' },
  { label: 'Вопросы', href: '#faq' },
];

/**
 * Навигация для страниц вне лендингов: там нет якорных секций,
 * поэтому ведём на сами направления.
 */
export const standaloneNav: readonly NavLink[] = [
  { label: 'Все направления', href: '/' },
  { label: 'Бег', href: '/beg/' },
];

/** Навигация хаба: якоря его собственных секций. */
export const hubNav: readonly NavLink[] = [
  { label: 'Направления', href: '#directions' },
  { label: 'Доступ', href: '#price' },
];
