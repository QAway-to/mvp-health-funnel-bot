import type { APIRoute } from 'astro';

/**
 * robots.txt генерируется, а не лежит в `public/`: ссылка на sitemap должна
 * указывать на текущий домен из `PUBLIC_SITE_URL`, иначе после привязки
 * домена в файле останется адрес из конфига по умолчанию.
 */
export const GET: APIRoute = ({ site }) => {
  const sitemap = new URL('sitemap-index.xml', site).href;

  return new Response(`User-agent: *\nAllow: /\n\nSitemap: ${sitemap}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
