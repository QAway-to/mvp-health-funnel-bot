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
    'footer.contact': 'Связаться',
    'footer.legalAria': 'Правовая информация',
    'footer.rights': 'Все права защищены',
    /* На русской странице пометка не нужна: документ и так на русском. */
    'footer.docsLang': '',
    'brand': 'Федерация здоровья',
    'reviews.kicker': 'Как это проходит у других',
    'reviews.title': 'Было — стало',
    'reviews.before': 'Было',
    'reviews.after': 'Стало',
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
    'footer.contact': 'Contact',
    'footer.legalAria': 'Legal information',
    'footer.rights': 'All rights reserved',
    /* Документы русские. Сказать это у ссылки дешевле, чем дать человеку
       открыть оферту и обнаружить кириллицу. */
    'footer.docsLang': 'in Russian',
    'brand': 'Federation of Health',
    'reviews.kicker': 'How it goes for other people',
    'reviews.title': 'Before — after',
    'reviews.before': 'Before',
    'reviews.after': 'After',
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
