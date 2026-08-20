/**
 * Разбор ссылки на видео из конфига.
 *
 * Поле `site.demo.videoUrl` принимает то, что у заказчика есть под рукой:
 * ссылку на YouTube или TikTok либо путь к файлу в `public/`. Что именно
 * вставили, определяется здесь, а не руками в разметке.
 *
 * Поддержаны YouTube, TikTok и прямые медиафайлы. У TikTok есть официальный
 * iframe-плеер (`/player/v1/{id}`), поэтому сторонний скрипт embed.js не нужен.
 * Оба видеохостинга вертикальные варианты отдают в 9:16.
 */

export type VideoSource =
  | { readonly kind: 'none' }
  /** Ссылка узнана, но ID из неё не достать — просим дать полную. */
  | { readonly kind: 'unresolvable'; readonly reason: string }
  | { readonly kind: 'file'; readonly src: string }
  | { readonly kind: 'youtube'; readonly id: string; readonly vertical: boolean }
  | { readonly kind: 'tiktok'; readonly id: string };

/** ID видео на YouTube — 11 символов из безопасного алфавита. */
const YOUTUBE_ID = /^[\w-]{11}$/;

const YOUTUBE_HOSTS = new Set([
  'youtube.com',
  'www.youtube.com',
  'm.youtube.com',
  'youtu.be',
  'www.youtu.be',
  'youtube-nocookie.com',
  'www.youtube-nocookie.com',
]);

/**
 * Достаёт ID из всех ходовых форм ссылки:
 *   youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID,
 *   youtube.com/shorts/ID, youtube.com/live/ID
 * Возвращает также признак вертикального формата — у Shorts другое соотношение.
 */
const parseYoutube = (url: URL): VideoSource | null => {
  if (!YOUTUBE_HOSTS.has(url.hostname)) return null;

  const segments = url.pathname.split('/').filter(Boolean);
  const vertical = segments[0] === 'shorts';

  const candidate =
    url.searchParams.get('v') ??
    (segments[0] === 'embed' || segments[0] === 'shorts' || segments[0] === 'live'
      ? segments[1]
      : url.hostname.endsWith('youtu.be')
        ? segments[0]
        : undefined);

  if (!candidate || !YOUTUBE_ID.test(candidate)) return null;

  return { kind: 'youtube', id: candidate, vertical };
};

const TIKTOK_HOSTS = new Set(['tiktok.com', 'www.tiktok.com', 'm.tiktok.com']);
/** Короткие ссылки-редиректы: ID в них нет, разрешить можно только запросом. */
const TIKTOK_SHORT_HOSTS = new Set(['vm.tiktok.com', 'vt.tiktok.com']);
/** ID поста — длинное число. */
const TIKTOK_ID = /^\d{6,25}$/;

/**
 * Достаёт ID поста из ссылки вида
 *   tiktok.com/@user/video/7234567890123456789
 *   tiktok.com/@user/photo/7234567890123456789
 *   tiktok.com/player/v1/7234567890123456789
 */
const parseTiktok = (url: URL): VideoSource | null => {
  if (TIKTOK_SHORT_HOSTS.has(url.hostname)) {
    return {
      kind: 'unresolvable',
      reason:
        'Это короткая ссылка TikTok — в ней нет ID ролика. Откройте видео на сайте и скопируйте полный адрес вида tiktok.com/@автор/video/123…',
    };
  }

  if (!TIKTOK_HOSTS.has(url.hostname)) return null;

  const segments = url.pathname.split('/').filter(Boolean);

  // /t/XXXX — тоже короткая форма
  if (segments[0] === 't') {
    return {
      kind: 'unresolvable',
      reason:
        'Это короткая ссылка TikTok — в ней нет ID ролика. Откройте видео на сайте и скопируйте полный адрес вида tiktok.com/@автор/video/123…',
    };
  }

  const marker = segments.findIndex((part) => part === 'video' || part === 'photo');
  const candidate =
    marker >= 0
      ? segments[marker + 1]
      : segments[0] === 'player'
        ? segments[segments.length - 1]
        : undefined;

  if (!candidate || !TIKTOK_ID.test(candidate)) return null;

  return { kind: 'tiktok', id: candidate };
};

export const parseVideoUrl = (raw: string): VideoSource => {
  const value = raw.trim();
  if (value.length === 0) return { kind: 'none' };

  // Путь к файлу в public/ — например /video/demo.mp4
  if (value.startsWith('/')) return { kind: 'file', src: value };

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { kind: 'none' };
  }

  const youtube = parseYoutube(url);
  if (youtube) return youtube;

  const tiktok = parseTiktok(url);
  if (tiktok) return tiktok;

  // Прямая ссылка на медиафайл на другом хосте
  if (/\.(mp4|webm|ogv|mov)(\?|$)/i.test(url.pathname)) {
    return { kind: 'file', src: value };
  }

  return { kind: 'none' };
};

/**
 * Адрес плеера. `youtube-nocookie.com` не ставит трекинг-куки до воспроизведения,
 * `rel=0` убирает чужие ролики в конце, `modestbranding` приглушает логотип.
 */
export const youtubeEmbedUrl = (id: string, autoplay = false): string => {
  const params = new URLSearchParams({
    rel: '0',
    modestbranding: '1',
    playsinline: '1',
  });
  if (autoplay) params.set('autoplay', '1');

  return `https://www.youtube-nocookie.com/embed/${id}?${params.toString()}`;
};

/**
 * Официальный плеер TikTok. `rel=0` показывает в конце ролики автора,
 * а не случайные чужие; описание и музыку убираем — на лендинге они мешают.
 */
export const tiktokEmbedUrl = (id: string, autoplay = false): string => {
  const params = new URLSearchParams({
    rel: '0',
    description: '0',
    music_info: '0',
    controls: '1',
    fullscreen_button: '1',
    progress_bar: '1',
    timestamp: '1',
  });
  if (autoplay) params.set('autoplay', '1');

  return `https://www.tiktok.com/player/v1/${id}?${params.toString()}`;
};
