/**
 * Тонкая обёртка над аналитикой.
 *
 * Провайдер не зашит: событие уходит в `dataLayer` (GTM) и в `gtag`, если они
 * подключены. Пока счётчика нет, вызовы просто ничего не делают — код страниц
 * от этого не зависит и не требует правок при смене счётчика.
 */

export type TrackPayload = Record<string, string | number | boolean>;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/** События воронки. Список закрытый, чтобы имена не разъезжались по файлам. */
export type TrackEvent =
  | 'view_hero'
  | 'cta_click'
  | 'click_free_cta'
  | 'quiz_start'
  | 'quiz_complete'
  | 'lead_submitted'
  | 'demo_played'
  | 'pricing_viewed'
  | 'checkout_started'
  | 'purchase'
  | 'scroll_depth';

export const track = (event: TrackEvent, payload: TrackPayload = {}): void => {
  window.dataLayer?.push({ event, ...payload });
  window.gtag?.('event', event, payload);
};

/** Срабатывает один раз на элемент: для просмотров секций и глубины скролла. */
export const observeOnce = (
  elements: Iterable<Element>,
  threshold: number,
  onSeen: (element: Element) => void,
): void => {
  if (!('IntersectionObserver' in window)) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        onSeen(entry.target);
        observer.unobserve(entry.target);
      });
    },
    { threshold },
  );

  for (const element of elements) observer.observe(element);
};
