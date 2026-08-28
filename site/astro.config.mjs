import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// Статическая многостраничная сборка мини-сайта Федерации.
// Output goes to `dist/`, которую отдаёт Render.
export default defineConfig({
  // Адрес, от которого считаются canonical, OG-теги и sitemap.
  // По умолчанию — живой адрес на Render: несуществующий домен в canonical
  // сообщает поисковику, что настоящая страница живёт где-то ещё, а мессенджер
  // не может забрать превью-картинку. Появится свой домен — задать
  // PUBLIC_SITE_URL в переменных окружения Render, менять код не нужно.
  site: process.env.PUBLIC_SITE_URL || 'https://mvp-running-landings.onrender.com',
  output: 'static',
  integrations: [sitemap()],

  // Каждая страница — своя папка с index.html (dist/bez-boli/index.html).
  // Обработка адреса без слеша у хостингов различается и у Render не
  // задокументирована, поэтому канонический адрес всегда со слешем,
  // а вариант без слеша уводится редиректом в render.yaml.
  trailingSlash: 'always',

  build: {
    format: 'directory',
    inlineStylesheets: 'auto',
  },
  compressHTML: true,
});
