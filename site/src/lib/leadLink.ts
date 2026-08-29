/**
 * Ссылки бесплатной ступени: от кнопки на лендинге до входа в бота.
 *
 * Сегмент человека известен уже на лендинге — он пришёл либо за комфортом,
 * либо за выносливостью. Дальше эта метка едет с ним: сначала в адресе
 * `/start/?s=komfort`, потом в deep link `t.me/<bot>?start=komfort`. Бот кладёт
 * её в поле `source`, и первый вопрос в диалоге он уже не тратит на то, что
 * и так известно.
 *
 * Без этого весь трафик сливается в одну безымянную кучу, и вопрос «какой
 * сегмент окупается» остаётся без ответа при любом рекламном бюджете.
 */

import { routes } from '../config/site';

/**
 * Закрытый список сегментов. Именно закрытый: значение приезжает из адресной
 * строки и уходит в чужой домен, поэтому в deep link попадает только то,
 * что мы сами и завели.
 */
export const LEAD_SEGMENTS = [
  'komfort',
  'sila',
  'beg',
  'son',
  'zaryadka',
  // Самомассаж слит с массажем, но метка остаётся в списке: ссылки с ней уже
  // разошлись, а выкинуть её — значит потерять сегмент у тех, кто по ним придёт.
  'samomassazh',
  'massazh',
  'zakalivanie',
  'vrednye-privychki',
  'demo',
  'home',
] as const;

export type LeadSegment = (typeof LEAD_SEGMENTS)[number];

/** Метка по умолчанию: человек открыл `/start/` напрямую. */
export const DEFAULT_SEGMENT = 'site';

export const isLeadSegment = (value: unknown): value is LeadSegment =>
  typeof value === 'string' && (LEAD_SEGMENTS as readonly string[]).includes(value);

/** Ссылка на бесплатную ступень с пометкой, откуда пришёл человек. */
export const startUrl = (segment?: string): string =>
  isLeadSegment(segment) ? `${routes.start}?s=${segment}` : routes.start;

/**
 * Уровни подписки, которые бот умеет открыть сразу по ссылке.
 *
 * Список закрытый по той же причине, что и сегменты: значение уезжает в
 * чужой домен и возвращается боту как команда к оплате. Совпадает с ключами
 * `subscription.tiers` — расходиться им нельзя, иначе кнопка ведёт в бота, а
 * тот показывает выбор уровня заново.
 */
export const TIER_IDS = ['base', 'premium', 'pro'] as const;

export type TierId = (typeof TIER_IDS)[number];

export const isTierId = (value: unknown): value is TierId =>
  typeof value === 'string' && (TIER_IDS as readonly string[]).includes(value);

/** Разделитель уровня и сегмента в метке. Должен совпадать с utils/deeplink.py. */
const PAYLOAD_SEPARATOR = '__';

/**
 * Deep link в Telegram-бота.
 *
 * Существующие параметры адреса отбрасываются: у бота параметр ровно один —
 * `start`, и второй `?start=` в хвосте Telegram просто не прочитает.
 *
 * С `tier` метка становится составной — `buy_premium__son`. Уровень человек
 * выбрал на лендинге, и донести этот выбор до чата важнее, чем сохранить
 * простоту метки: иначе он выбирает второй раз то же самое, а на втором
 * выборе часть людей уходит.
 *
 * Разделитель двойной: дефис уже занят внутри сегментов
 * (`vrednye-privychki`), а Telegram пропускает в метке только буквы, цифры,
 * дефис и подчёркивание.
 */
export const botUrl = (base: string, segment?: string, tier?: string): string => {
  const clean = base.split('?')[0].split('#')[0];
  const label = isLeadSegment(segment) ? segment : DEFAULT_SEGMENT;
  const payload = isTierId(tier) ? `buy_${tier}${PAYLOAD_SEPARATOR}${label}` : label;
  return `${clean}?start=${payload}`;
};
