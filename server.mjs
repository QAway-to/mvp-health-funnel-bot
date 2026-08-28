import { createServer } from 'node:http';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import sirv from 'sirv';

/**
 * HTTP-сервер для раздачи `dist/` — нужен только если сайт развёрнут как
 * Render Web Service. Для Static Site он не используется: там всё берётся
 * из `render.yaml`, а процесса нет вообще.
 *
 * Web Service не умеет `headers` и `routes` из `render.yaml` — это поля
 * только для статики. Поэтому редиректы, кэш и заголовки безопасности
 * повторены здесь и должны меняться вместе с `render.yaml`.
 */

const PORT = Number(process.env.PORT) || 10000;
const HOST = '0.0.0.0';
const ROOT = join(import.meta.dirname, 'dist');

if (!existsSync(ROOT)) {
  throw new Error(`Каталог ${ROOT} не найден — сначала выполните npm run build`);
}

/** Адреса без слеша и короткие ссылки для рекламы. Значения — как в render.yaml. */
const REDIRECTS = new Map([
  ['/beg', '/beg/'],
  ['/komfort', '/komfort/'],
  ['/sila', '/sila/'],
  ['/son', '/son/'],
  ['/zaryadka', '/zaryadka/'],
  ['/massazh', '/massazh/'],
  ['/zakalivanie', '/zakalivanie/'],
  ['/vrednye-privychki', '/vrednye-privychki/'],
  // Самомассаж слит с массажем 28.08.2026: приёмы там одни и те же. Страницы
  // больше нет, но ссылки на неё уже разошлись — и по сайту, и в боте.
  ['/samomassazh', '/massazh/'],
  ['/samomassazh/', '/massazh/'],
  ['/start', '/start/'],
  ['/demo', '/demo/'],
  ['/a', '/komfort/'],
  ['/b', '/sila/'],
  // Прежние слаги сегмента: сначала «без боли», потом «без дискомфорта».
  // Обе формулировки были от отрицания, но ссылки на них уже разошлись.
  ['/bez-boli', '/komfort/'],
  ['/bez-boli/', '/komfort/'],
  ['/bez-diskomforta', '/komfort/'],
  ['/bez-diskomforta/', '/komfort/'],
]);

/** Хешированные ассеты и картинки кэшируются навсегда, HTML — никогда. */
const IMMUTABLE_PATH = /^\/(?:_astro|img)\//;

const notFoundPage = existsSync(join(ROOT, '404.html'))
  ? readFileSync(join(ROOT, '404.html'))
  : null;

const setSecurityHeaders = (res) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.setHeader('X-Frame-Options', 'SAMEORIGIN');
};

const sendNotFound = (res) => {
  setSecurityHeaders(res);
  res.setHeader('Cache-Control', 'no-cache');

  if (notFoundPage) {
    res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(notFoundPage);
    return;
  }

  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('404');
};

const serveStatic = sirv(ROOT, {
  etag: true,
  // Отдаём заранее сжатые .br/.gz, которые кладёт scripts/precompress.mjs:
  // за web service никто не сжимает ответы, в отличие от CDN у статики.
  brotli: true,
  gzip: true,
  setHeaders(res, pathname) {
    setSecurityHeaders(res);
    res.setHeader(
      'Cache-Control',
      IMMUTABLE_PATH.test(pathname) ? 'public, max-age=31536000, immutable' : 'no-cache',
    );
  },
  onNoMatch(_req, res) {
    sendNotFound(res);
  },
});

const server = createServer((req, res) => {
  // Совпадение ищем только по пути: query-параметры рекламы должны доезжать.
  const [pathname, query] = (req.url ?? '/').split('?');
  const target = REDIRECTS.get(pathname);

  if (target) {
    setSecurityHeaders(res);
    res.writeHead(301, { Location: query ? `${target}?${query}` : target });
    res.end();
    return;
  }

  serveStatic(req, res);
});

server.listen(PORT, HOST, () => {
  process.stdout.write(`Статика из ${ROOT} отдаётся на http://${HOST}:${PORT}\n`);
});

// Без этого Render ждёт таймаута на каждом деплое.
const shutdown = () => server.close(() => process.exit(0));
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
