import { site } from '../config/site';
import type { Lang } from '../i18n';
import type { Subscription } from './types';

/**
 * Текст блока подписки. Один на весь сайт — потому что и продукт один.
 *
 * Раньше у каждого лендинга был свой набор тарифов, и одно и то же
 * предложение расходилось между страницами. Теперь страница направления
 * рассказывает про направление, а про деньги везде говорится одинаково.
 *
 * Уровни отличаются **обратной связью, а не объёмом материалов**: все
 * направления открыты на любом уровне. Это принципиально — иначе «База»
 * читалась бы как урезанный продукт, а не как способ идти самому.
 *
 * Цены и ссылки оплаты лежат в site.subscription.tiers и подставляются по `id`.
 * Языков два, `id` у уровней общие: цена в конфиге одна, меняются только
 * подписи. Разойтись они не могут — уровень без цены роняет сборку.
 */
const ru: Subscription = {
  kicker: 'Доступ',
  title: 'Одна подписка на все направления',
  lead: 'Здоровье не делится на курсы: сон тянет за собой утро, утро — нагрузку, нагрузка — восстановление. Поэтому доступ один и сразу ко всему. Уровни отличаются не материалами — они везде одинаковые, — а тем, насколько плотно я рядом.',

  features: [
    'Все открытые направления целиком',
    'Новые направления открываются без доплаты',
    'Доступ с телефона, без установки приложений',
  ],

  /* Период и условия отмены — коммерческие данные: живут в конфиге, где их
     правит заказчик, и оттуда же их берёт оферта. Здесь только ссылка. */
  period: site.subscription.period,
  terms: site.subscription.terms,
  starsLabel: 'Звёздами в Telegram',

  tiers: [
    {
      id: 'base',
      label: 'База',
      text: 'Все направления целиком, в правильном порядке. Для тех, кто готов идти сам.',
      features: [
        'Все направления без ограничений',
        'Новые темы сразу после выхода',
        'Порядок и дозировки по шагам',
        'Отмена в любой момент',
      ],
      ctaLabel: 'Оформить базу',
    },
    {
      id: 'premium',
      label: 'Премиум',
      text: 'Всё из базы плюс живая обратная связь: разбираю ваши вопросы и смотрю, что идёт не так.',
      features: [
        'Разбор вопросов в чате',
        'Ответ по вашей ситуации',
        'Разбор техники по видео',
        'Протокол на «что-то беспокоит»',
      ],
      ctaLabel: 'Оформить премиум',
      badge: 'РЕКОМЕНДУЮ',
    },
    {
      id: 'pro',
      label: 'Сопровождение',
      text: 'Веду лично: смотрю, как идёт, и правлю план под вас. Беру немного людей одновременно.',
      features: [
        'Еженедельный разбор видео',
        'План правится под ваш темп',
        'Личный чат: ответ за день',
        'Набор ограничен',
      ],
      ctaLabel: 'Пойти с сопровождением',
    },
  ],

  ui: {
    payTitle: 'Как удобнее оплатить?',
    payLead: 'Доступ один и тот же — отличается только способ оплаты.',
    payCard: 'Картой на LavaTop',
    payCardNote: 'Обычная оплата картой. Подписка, отменить можно в любой момент.',
    payStars: 'Звёздами в Telegram',
    payStarsNote: 'Оплата внутри чата: карту вводить не нужно, нужны звёзды Telegram.',
    payClose: 'Закрыть',
    includedTitle: 'На любом уровне открыто',
    materialsLabel: 'материалы',
    materialsNote: (names) =>
      `Пометка «материалы» — направление открыто целиком, но пошагового курса по нему пока нет: ${names.map((name) => `«${name}»`).join(' и ')}.`,
    soonNote: (names) => `Готовятся: ${names.join(', ')}.`,
    pendingCta: 'Забрать первый шаг бесплатно',
    pendingNote: 'Оплата подключается. Пока доступна бесплатная ступень — о запуске сообщим первым.',
    freeCta: 'Первый шаг бесплатно',
  },
};

/**
 * Английская версия того же предложения — адаптация, а не перевод.
 *
 * ЧТО ЗДЕСЬ СКАЗАНО ИНАЧЕ. Русскому читателю не нужно объяснять, на каком
 * языке материал. Англоязычному — нужно, и сказать это надо рядом с ценой,
 * а не сноской внизу: он платит за русский курс с английскими субтитрами
 * страницы, и узнать об этом после оплаты хуже, чем не продать вовсе.
 * Поэтому `warning` стоит прямо в блоке подписки.
 *
 * Уровни описаны теми же словами по смыслу, но без кальки: «Сопровождение» —
 * не «Support» (это техподдержка), а «One-on-one».
 */
const en: Subscription = {
  kicker: 'Access',
  title: 'One subscription, every direction',
  lead: 'Health does not split into courses: sleep pulls the morning, the morning pulls the load, the load pulls recovery. So access is one thing and covers everything. The levels differ not in material — that is the same on all three — but in how closely I am there.',

  features: [
    'Every open direction, in full',
    'New directions open at no extra cost',
    'Works from a phone, nothing to install',
  ],

  period: 'per month',
  terms: 'Cancel any time',
  starsLabel: 'With Telegram Stars',

  warning:
    'The material is in Russian — all 68 steps, the clips and the bot. This page is English; the course is not. Read that before you pay, not after.',

  tiers: [
    {
      id: 'base',
      label: 'Base',
      text: 'Every direction in full, in the right order. For people who are fine going alone.',
      features: [
        'Every direction, no limits',
        'New topics the day they open',
        'The order and the dose, step by step',
        'Cancel any time',
      ],
      ctaLabel: 'Take Base',
    },
    {
      id: 'premium',
      label: 'Premium',
      text: 'Everything in Base plus a live answer: I go through your questions and see what is going wrong.',
      features: [
        'Your questions answered in chat',
        'An answer for your situation, not a general one',
        'Technique reviewed from your video',
        'A protocol when something hurts',
      ],
      ctaLabel: 'Take Premium',
      badge: 'RECOMMENDED',
    },
    {
      id: 'pro',
      label: 'One-on-one',
      text: 'I run it with you: I watch how it goes and adjust the plan. A few people at a time.',
      features: [
        'Weekly video review',
        'The plan follows your pace',
        'Private chat, answered within a day',
        'Limited intake',
      ],
      ctaLabel: 'Go one-on-one',
    },
  ],

  ui: {
    payTitle: 'How would you like to pay?',
    payLead: 'The access is identical — only the way you pay differs.',
    payCard: 'By card, on LavaTop',
    payCardNote: 'An ordinary card payment. It is a subscription, cancel any time.',
    payStars: 'With Telegram Stars',
    payStarsNote: 'Paid inside the chat: no card details, you need Telegram Stars.',
    payClose: 'Close',
    includedTitle: 'Open on every level',
    materialsLabel: 'materials',
    materialsNote: (names) =>
      `Marked “materials” — the direction is open in full, but it is not laid out step by step yet: ${names.map((name) => `“${name}”`).join(' and ')}.`,
    soonNote: (names) => `In the works: ${names.join(', ')}.`,
    pendingCta: 'Take the first step free',
    pendingNote: 'Payment is being connected. The free step is open in the meantime.',
    freeCta: 'First step free',
  },
};

export const subscriptionByLang: Record<Lang, Subscription> = { ru, en };
