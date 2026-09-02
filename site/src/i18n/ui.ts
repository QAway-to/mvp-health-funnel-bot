/**
 * Строки оболочки: то, что окружает контент на любой странице.
 *
 * Только интерфейс — кнопки, подписи, навигация. Тексты страниц живут в
 * `src/content/` и переводятся отдельно: смешать их значило бы получить
 * словарь на тридцать страниц, в котором ничего не найти.
 *
 * Ключ отсутствует — берётся русский. Пустая строка на кнопке хуже строки на
 * другом языке: по второй хотя бы понятно, куда нажимать.
 */

import type { Lang } from './index';

export const ui = {
  ru: {
    'nav.home': 'На главную',
    'nav.directions': 'Направления',
    'nav.access': 'Доступ',
    'nav.menu': 'Меню',
    'nav.aria': 'Основная навигация',
    'cta.free': 'Первый шаг бесплатно',
    'cta.start': 'Забрать первый шаг бесплатно',
    'pay.how': 'Как удобнее заплатить?',
    'pay.card': 'Картой',
    'pay.stars': 'Звёздами в Telegram',
    'pay.compare': 'Сравнить уровни',
    'pay.close': 'Закрыть',
    'footer.offer': 'Оферта',
    'footer.privacy': 'Политика конфиденциальности',
    'lang.switch': 'English',
  },
  en: {
    'nav.home': 'Home',
    'nav.directions': 'Directions',
    'nav.access': 'Access',
    'nav.menu': 'Menu',
    'nav.aria': 'Main navigation',
    'cta.free': 'First step free',
    'cta.start': 'Take the first step free',
    'pay.how': 'How would you like to pay?',
    'pay.card': 'By card',
    'pay.stars': 'With Telegram Stars',
    'pay.compare': 'Compare levels',
    'pay.close': 'Close',
    'footer.offer': 'Terms',
    'footer.privacy': 'Privacy policy',
    'lang.switch': 'Русский',
  },
} as const;

export type UiKey = keyof (typeof ui)['ru'];

/** Переводчик для языка страницы. Нет перевода — отдаём русский. */
export const useTranslations = (lang: Lang) => {
  return (key: UiKey): string => {
    const table = ui[lang] as Record<string, string>;
    return table[key] ?? ui.ru[key];
  };
};
