/**
 * Разбор ссылки на видео из конфига.
 *
 * Поле `site.demo.videoUrl` принимает то, что у заказчика есть под рукой:
 * ссылку на YouTube в любом виде или путь к файлу в `public/`. Что именно
 * вставили, определяется здесь, а не руками в разметке.
 *
 * TikTok сознательно не поддержан: у него нет обычного iframe-адреса,
 * официальное встраивание требует blockquote и стороннего скрипта embed.js,
 * а формат вертикальный. Понадобится — это отдельная работа, не «ещё один case».
 */

export type VideoSource =
  | { readonly kind: 'none' }
  | { readonly kind: 'file'; readonly src: string }
  | { readonly kind: 'youtube'; readonly id: string; readonly vertical: boolean };

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
