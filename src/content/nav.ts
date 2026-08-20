import type { NavLink } from './types';

/** Якорная навигация одинакова на обоих лендингах. */
export const nav: readonly NavLink[] = [
  { label: 'Программа', href: '#program' },
  { label: 'Цена', href: '#price' },
  { label: 'Вопросы', href: '#faq' },
];

/**
 * Навигация для страниц вне лендингов: там нет якорных секций,
 * поэтому ведём на сами сценарии.
 */
export const standaloneNav: readonly NavLink[] = [
  { label: 'Бег без дискомфорта', href: '/bez-diskomforta/' },
  { label: 'Бег как сила', href: '/sila/' },
];
