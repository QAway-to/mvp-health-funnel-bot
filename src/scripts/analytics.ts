/**
 * Аналитика воронки. Подключается один раз на всех страницах.
 *
 * Собственной отправки здесь нет: события уходят через `track()`, который
 * складывает их в `dataLayer` и `gtag`. Раньше в этом файле лежала своя копия
 * отправщика — два списка событий расходились, и `checkout_started` из
 * мобильной панели попадал в один поток, а `cta_click` в другой.
 *
 * Что снимается:
 *   cta_click     — клик по любой кнопке с `data-cta`;
 *   scroll_depth  — первое появление секции (`data-section`) и проценты
 *                   прокрутки 25/50/75/100;
 *   view_hero     — первый экран увидели;
 *   pricing_viewed — дошли до блока подписки.
 *
 * Пока счётчик не подключён, всё это молча никуда не уходит — см. layouts/Landing.astro.
 */

import { observeOnce, track } from './track';

const trackCtaClicks = (): void => {
  document.querySelectorAll<HTMLElement>('[data-cta]').forEach((element) => {
    element.addEventListener('click', () => {
      track('cta_click', {
        placement: element.dataset.cta ?? 'unknown',
        kind: element.dataset.ctaKind ?? 'unknown',
        label: element.textContent?.trim().slice(0, 80) ?? '',
      });
    });
  });
};

/**
 * Просмотр секций.
 *
 * У первого экрана и блока подписки есть собственные события: это границы
 * воронки, и искать их в общем потоке `scroll_depth` с фильтром по имени
 * секции неудобно.
 */
const SECTION_EVENTS: Record<string, 'view_hero' | 'pricing_viewed'> = {
  hero: 'view_hero',
  price: 'pricing_viewed',
};

const trackSections = (): void => {
  const sections = document.querySelectorAll<HTMLElement>('[data-section]');

  observeOnce(sections, 0.4, (element) => {
    const name = (element as HTMLElement).dataset.section;
    if (!name) return;

    const own = SECTION_EVENTS[name];
    if (own) track(own, { page: document.body.dataset.page ?? location.pathname });

    track('scroll_depth', { section: name });
  });
};

/**
 * Проценты прокрутки.
 *
 * Секции отвечают на вопрос «что человек увидел», проценты — «докуда дочитал».
 * Второе сравнимо между страницами разной длины, первое нет.
 */
const trackScrollPercent = (): void => {
  const marks = [25, 50, 75, 100];
  const reached = new Set<number>();

  const update = (): void => {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    // Страница короче экрана: считаем прочитанной целиком, иначе 100% никогда
    // не наступит и отчёт будет врать в меньшую сторону.
    const depth = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 100;

    for (const mark of marks) {
      if (depth + 0.5 < mark || reached.has(mark)) continue;
      reached.add(mark);
      track('scroll_depth', { percent: mark });
    }

    if (reached.size === marks.length) {
      window.removeEventListener('scroll', onScroll);
    }
  };

  let ticking = false;
  const onScroll = (): void => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      update();
      ticking = false;
    });
  };

  update();
  window.addEventListener('scroll', onScroll, { passive: true });
};

trackCtaClicks();
trackSections();
trackScrollPercent();

export {};
