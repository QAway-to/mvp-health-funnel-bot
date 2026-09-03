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
import { subscriptionByLang } from '../content/subscription';
import type { SubscriptionTier } from '../content/types';
import { DEFAULT_LANG, type Lang } from '../i18n';
import { botUrl, freeStepUrl, isLeadSegment } from './leadLink';

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
  /**
   * Вторая дверь к тому же доступу: оплата звёздами внутри Telegram.
   * Пусто — второй двери нет, и поп-ап не нужен.
   */
  readonly starsHref: string;
  readonly starsLabel: string;
}

/**
 * Цена с периодом: «$20 в месяц», «$20 per month».
 *
 * Период приходит из контента языка, а не из конфига: сумма одна на оба
 * языка, а слово рядом с ней — разное. Раньше английская карточка честно
 * показывала «$20 в месяц».
 */
const priceLabelFor = (price: string, period: string): string => {
  if (!isFilled(price)) return '';
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
export const resolveTiers = (
  segment?: string,
  lang: Lang = DEFAULT_LANG,
): readonly ResolvedTier[] =>
  subscriptionByLang[lang].tiers.map((tier) => {
    if (!isTierId(tier.id)) {
      throw new Error(
        `[subscription] уровень «${tier.id}» описан в контенте, но цены для него нет в site.subscription.tiers`,
      );
    }

    const { price } = tierPrices[tier.id];
    // Своя ссылка у уровня перебивает общую: продукт в кассе один, но если
    // однажды появится ссылка прямо на план, она и должна выиграть.
    const payUrl = tierPrices[tier.id].payUrl || site.subscription.payUrl;
    const hasCheckout = isFilled(payUrl);

    return {
      ...tier,
      priceLabel: priceLabelFor(price, subscriptionByLang[lang].period),
      hasCheckout,
      href: hasCheckout ? payHref(payUrl, segment) : freeStepUrl(segment, lang),
      kind: hasCheckout ? 'sales' : 'primary',
      ctaLabel: hasCheckout ? tier.ctaLabel : subscriptionByLang[lang].ui.freeCta,
      /**
       * Дверей две, и они не равнозначны для разных людей. Картой платят те,
       * у кого она под рукой; звёздами — те, кто живёт в Telegram и не хочет
       * вводить карту на чужом сайте. Показывать одну — терять вторых.
       *
       * Появляется только рядом с оплатой картой: пока её нет, обе кнопки
       * вели бы в одно и то же место, и выбор был бы ненастоящим.
       */
      starsHref:
        hasCheckout && isFilled(site.lead.telegramUrl)
          ? botUrl(site.lead.telegramUrl, segment, tier.id)
          : '',
      starsLabel: subscriptionByLang[lang].starsLabel,
    };
  });

/**
 * Рекомендуемый уровень — тот, что помечен `badge`.
 *
 * Он подставляется в сквозные места: мобильную панель и финальный призыв.
 * Метка ставится ровно одному уровню: два «рекомендую» не рекомендуют ничего.
 */
export const featuredTier = (segment?: string, lang: Lang = DEFAULT_LANG): ResolvedTier => {
  const tiers = resolveTiers(segment, lang);
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
  isFilled(site.subscription.payUrl) ||
  Object.values(tierPrices).some((tier) => isFilled(tier.payUrl));
