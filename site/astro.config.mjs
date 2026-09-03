import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// Статическая многостраничная сборка мини-сайта Федерации.
// Output goes to `dist/`, которую отдаёт Render.
export default defineConfig({
  // Адрес, от которого считаются canonical, OG-теги, hreflang и sitemap.
  //
  // По умолчанию — тот адрес, по которому сайт РЕАЛЬНО открывается. До
  // 03.09.2026 здесь стоял адрес отдельного сервиса лендингов, а сайт давно
  // переехал внутрь сервиса бота: каждая страница отдавала canonical на чужой
  // домен, то есть сама сообщала поисковику, что настоящая версия живёт не
  // здесь. Вместе с hreflang это стоило бы обеих языковых версий сразу.
  //
  // Появится свой домен — задать PUBLIC_SITE_URL в переменных окружения
  // Render, менять код не нужно.
  site: process.env.PUBLIC_SITE_URL || 'https://mvp-health-funnel-bot.onrender.com',
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
