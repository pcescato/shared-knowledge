import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { CATEGORIES, categoryDir } from './src/lib/knowledge.js';

// The site is deployed to GitHub Pages as a project page:
// https://pcescato.github.io/shared-knowledge/
const SITE = 'https://pcescato.github.io';
const BASE = '/shared-knowledge';

// Sidebar: one entry per category (stable URLs /<category-dir>/).
const categoryLinks = CATEGORIES.map((category) => ({
  label: category,
  link: `/${categoryDir(category)}/`,
}));

export default defineConfig({
  site: SITE,
  base: BASE,
  output: 'static',
  trailingSlash: 'never',
  integrations: [
    starlight({
      title: 'Shared Knowledge',
      description:
        'A community knowledge base: solved problems, shared on purpose.',
      // Restrained, documentation-first look: neutral accent, serious layout.
      customCss: ['./src/styles/custom.css'],
      social: [
        {
          icon: 'github',
          label: 'GitHub repository (source of truth)',
          href: 'https://github.com/pcescato/shared-knowledge',
        },
      ],
      // Full-text search via Pagefind (static, no external service).
      pagefind: {},
      sidebar: [
        { label: 'Categories', items: categoryLinks },
        { label: 'Browse', items: [
          { label: 'All articles', link: '/articles/' },
          { label: 'Tags', link: '/tags/' },
        ] },
      ],
    }),
  ],
});
