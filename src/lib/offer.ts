/**
 * Платная ступень: подписка на все направления Федерации, три уровня доступа.
 *
 * Главное правило здесь одно: **кнопка никогда не ведёт в никуда**. Пока
 * ссылка оплаты уровня не заведена, его кнопка превращается в бесплатную
 * ступень — человек уходит в бота, а не на 404. Раньше в вёрстку уезжал
 * литерал `{ССЫЛКА_ОПЛАТЫ}`, и клик по цене открывал ненайденную страницу.
 *
 * Здесь же склеиваются две половины уровня: цена и ссылка живут в конфиге,
 * а подпись и состав — в контенте. Соединяются по `id`, и если конфиг о таком
 * уровне не знает, сборка падает — это лучше, чем карточка без цены в проде.
 */

import { site } from '../config/site';
import { subscriptionContent } from '../content/subscription';
import type { SubscriptionTier } from '../content/types';
import { isLeadSegment, startUrl } from './leadLink';

/**
 * Заполнено ли поле конфига.
 *
 * Пустая строка означает «заказчик ещё не дал значение». Фигурные скобки
 * проверяются отдельно: старые плейсхолдеры вида `{ЦЕНА}` могли вернуться
 * в конфиг копипастой, и такой текст на странице выглядит как поломка.
 */
export const isFilled = (value: string | undefined): boolean =>
  typeof value === 'string' && value.trim().length > 0 && !value.includes('{');

type TierId = keyof typeof site.subscription.tiers;

const tierPrices = site.subscription.tiers;

const isTierId = (id: string): id is TierId => id in tierPrices;

/** Уровень, готовый к отрисовке: контент, цена и решение по кнопке. */
export interface ResolvedTier extends SubscriptionTier {
  /** Цена с периодом: «$20 в месяц». */
  readonly priceLabel: string;
  readonly href: string;
  readonly kind: 'sales' | 'primary';
  readonly ctaLabel: string;
  readonly hasCheckout: boolean;
}

const priceLabelFor = (price: string): string => {
  if (!isFilled(price)) return '';
  const { period } = site.subscription;
  return isFilled(period) ? `${price} ${period}` : price;
};

/**
 * Ссылка оплаты с меткой источника.
 *
 * Имя параметра задаётся в конфиге, и пока оно пустое, ссылка уходит как есть.
 * Выдумывать параметр за чужой сервис нельзя — лишний хвост в адресе может
 * просто сломать оплату.
 */
const payHref = (payUrl: string, segment?: string): string => {
  const { trackingParam } = site.subscription;
  if (!isFilled(trackingParam) || !isLeadSegment(segment)) return payUrl;

  const separator = payUrl.includes('?') ? '&' : '?';
  return `${payUrl}${separator}${encodeURIComponent(trackingParam)}=${encodeURIComponent(segment)}`;
};

/**
 * Уровни подписки в порядке контента, с подставленными ценами и ссылками.
 *
 * Подпись кнопки честна в каждом состоянии: есть оплата — зовём в неё,
 * нет — зовём на бесплатное, а не обещаем оплату, которой пока не существует.
 */
export const resolveTiers = (segment?: string): readonly ResolvedTier[] =>
  subscriptionContent.tiers.map((tier) => {
    if (!isTierId(tier.id)) {
      throw new Error(
        `[subscription] уровень «${tier.id}» описан в контенте, но цены для него нет в site.subscription.tiers`,
      );
    }

    const { price, payUrl } = tierPrices[tier.id];
    const hasCheckout = isFilled(payUrl);

    return {
      ...tier,
      priceLabel: priceLabelFor(price),
      hasCheckout,
      href: hasCheckout ? payHref(payUrl, segment) : startUrl(segment),
      kind: hasCheckout ? 'sales' : 'primary',
      ctaLabel: hasCheckout ? tier.ctaLabel : 'Первый шаг бесплатно',
    };
  });

/**
 * Рекомендуемый уровень — тот, что помечен `badge`.
 *
 * Он подставляется в сквозные места: мобильную панель и финальный призыв.
 * Метка ставится ровно одному уровню: два «рекомендую» не рекомендуют ничего.
 */
export const featuredTier = (segment?: string): ResolvedTier => {
  const tiers = resolveTiers(segment);
  const featured = tiers.filter((tier) => isFilled(tier.badge));

  if (featured.length > 1) {
    throw new Error('[subscription] метка «рекомендую» стоит больше чем у одного уровня');
  }

  const chosen = featured[0] ?? tiers.at(-1);

  if (!chosen) {
    throw new Error('[subscription] не описано ни одного уровня подписки');
  }

  return chosen;
};

/** Заведена ли оплата хоть у одного уровня. */
export const hasAnyCheckout = (): boolean =>
  Object.values(tierPrices).some((tier) => isFilled(tier.payUrl));
