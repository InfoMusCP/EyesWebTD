import { defineConfig } from 'astro/config';

// Static site. Set `base` when it is served from a sub-path (e.g. GitHub Pages: '/EyesWebTD').
export default defineConfig({
  site: 'https://example.org',
  base: '/',
  trailingSlash: 'ignore',
});
