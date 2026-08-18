/**
 * Аналитика лендингов: два события из хендоффа.
 *
 * - `cta_click`  — клик по любой кнопке с `data-cta="<место>"`
 *   (hero / header / price_base / price_premium / final).
 * - `scroll_depth` — первое появление секции с `data-section="<имя>"` в вьюпорте.
 *
 * Провайдер не зашит: событие уходит в `dataLayer` (GTM) и в `gtag`, если они есть.
 * Пока счётчик не подключён, вызовы просто ничего не делают.
 */

type EventPayload = Record<string, string>;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

const track = (event: string, payload: EventPayload): void => {
  window.dataLayer?.push({ event, ...payload });
  window.gtag?.('event', event, payload);
};

const trackCtaClicks = (): void => {
  document.querySelectorAll<HTMLElement>('[data-cta]').forEach((element) => {
    element.addEventListener('click', () => {
      track('cta_click', {
        placement: element.dataset.cta ?? 'unknown',
        label: element.textContent?.trim() ?? '',
      });
    });
  });
};

const trackScrollDepth = (): void => {
  const sections = document.querySelectorAll<HTMLElement>('[data-section]');
  if (sections.length === 0 || !('IntersectionObserver' in window)) return;

  const seen = new Set<string>();

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;

        const name = (entry.target as HTMLElement).dataset.section;
        if (!name || seen.has(name)) return;

        seen.add(name);
        track('scroll_depth', { section: name });
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.4 },
  );

  sections.forEach((section) => observer.observe(section));
};

trackCtaClicks();
trackScrollDepth();

export {};
