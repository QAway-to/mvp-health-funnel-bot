/**
 * Реестр направлений на языке страницы.
 *
 * Источник правды остаётся один — русский реестр `src/content/directions.ts`.
 * Он решает, какие направления существуют, какие открыты, где у них картинка
 * и раскрыты ли они курсом или пока материалами. Английский файл добавляет
 * только слова: название и обещание.
 *
 * Так сделано ради одной вещи — направление нельзя открыть на одном языке и
 * забыть на другом. Слаг, которого нет в русском реестре, роняет сборку; тем
 * же способом ловится и переименованный слаг.
 */

import { directions, liveDirections, soonDirections, type DirectionDepth } from '../content/directions';
import { enDirections, enSoonDirections } from '../content/en/directions';
import { DEFAULT_LANG, type Lang } from './index';

/** Карточка направления в том виде, в каком её рисуют главная и блок подписки. */
export interface DirectionCard {
  readonly slug: string;
  readonly title: string;
  readonly promise: string;
  /** Курс или пока набор материалов. Берётся из русского реестра. */
  readonly depth?: DirectionDepth;
  readonly href?: string;
  readonly image?: string;
  /** Сколько шагов в курсе. Есть только у английских карточек. */
  readonly steps?: number;
}

const bySlug = new Map(directions.map((direction) => [direction.slug, direction]));

const unknownSlugs = [...enDirections, ...enSoonDirections]
  .map((direction) => direction.slug)
  .filter((slug) => !bySlug.has(slug));

if (unknownSlugs.length > 0) {
  throw new Error(
    `[i18n] английские направления ссылаются на слаги, которых нет в реестре: ${unknownSlugs.join(', ')}`,
  );
}

const enLive: readonly DirectionCard[] = enDirections.map((direction) => {
  const russian = bySlug.get(direction.slug);
  return {
    slug: direction.slug,
    title: direction.title,
    promise: direction.promise,
    depth: russian?.depth,
    href: `/en/${direction.slug}/`,
    image: russian?.image,
    steps: direction.steps.length,
  };
});

const enSoon: readonly DirectionCard[] = enSoonDirections.map((direction) => ({
  slug: direction.slug,
  title: direction.title,
  promise: direction.promise,
}));

/**
 * Списки направлений должны совпадать по составу на обоих языках.
 *
 * Расхождение означало бы, что человек, переключивший язык, видит другое
 * предложение — а платит за одно и то же. Проверяются ОБА списка: открытые и
 * готовящиеся.
 *
 * Готовящиеся попали сюда не сразу, и зря. Проверка выше (`unknownSlugs`)
 * ловит только английский слаг, которого нет в реестре, то есть опечатку и
 * переименование. Добавленное направление она не ловит: русский список
 * растёт, английский остаётся прежним, сборка молчит — и на `/en/`
 * «готовятся» показывается меньше тем, чем на `/`. Ровно та ошибка, ради
 * которой этот файл и написан.
 */
const missingTranslations = [
  ...liveDirections.map((direction) => direction.slug).filter(
    (slug) => !enLive.some((card) => card.slug === slug),
  ),
  ...soonDirections.map((direction) => direction.slug).filter(
    (slug) => !enSoon.some((card) => card.slug === slug),
  ),
];

if (missingTranslations.length > 0) {
  throw new Error(
    `[i18n] направления без английской версии: ${missingTranslations.join(', ')}`,
  );
}

/**
 * Английская страница направления существует только у открытого направления.
 *
 * Иначе тема, которая по-русски ещё готовится, по-английски встаёт в сетку
 * открытых и в состав подписки — то есть продаётся то, чего нет. Статус живёт
 * в русском реестре, и спрашивать его надо там, а не выводить из того, в
 * какой файл попала запись.
 */
const notLiveInRegistry = enDirections
  .map((direction) => direction.slug)
  .filter((slug) => bySlug.get(slug)?.status !== 'live');

if (notLiveInRegistry.length > 0) {
  throw new Error(
    `[i18n] английская страница есть у направления, которое ещё не открыто: ${notLiveInRegistry.join(', ')}`,
  );
}

export const liveDirectionsFor = (lang: Lang): readonly DirectionCard[] =>
  lang === DEFAULT_LANG ? liveDirections : enLive;

export const soonDirectionsFor = (lang: Lang): readonly DirectionCard[] =>
  lang === DEFAULT_LANG ? soonDirections : enSoon;

export const directionsCountFor = (lang: Lang): number =>
  liveDirectionsFor(lang).length + soonDirectionsFor(lang).length;
