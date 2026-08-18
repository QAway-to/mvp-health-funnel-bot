import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// Static multi-page build: `/` chooser, `/bez-boli/` (A), `/sila/` (B).
// Output goes to `dist/`, которую отдаёт Render.
export default defineConfig({
  site: process.env.PUBLIC_SITE_URL || 'https://beg.example.com',
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
