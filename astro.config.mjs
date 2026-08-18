import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// Static multi-page build: `/` chooser, `/bez-boli` (A), `/sila` (B).
// Output goes to `dist/`, which is what Render serves.
export default defineConfig({
  site: process.env.PUBLIC_SITE_URL || 'https://beg.example.com',
  output: 'static',
  integrations: [sitemap()],
  build: {
    format: 'directory',
    inlineStylesheets: 'auto',
  },
  compressHTML: true,
});
