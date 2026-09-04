/**
 * Pure knowledge helpers shared by the Astro config and site pages.
 *
 * URL + audio contract (aligned with slugify() in the root repository's
 * github.py and scripts/generate_audio.py):
 *   knowledge/<category>/<slug>.md  ->  /<category-dir>/<slug>/
 *                                   ->  /audio/<category-dir>/<slug>.mp3
 */

// Controlled vocabulary - mirrors CATEGORIES in server.py (spec section 8).
export const CATEGORIES = [
  'AI',
  'Backend',
  'Cloud',
  'Databases',
  'DevOps',
  'Frontend',
  'Hardware',
  'Linux',
  'Security',
  'Web Development',
  'Programming',
  'Open Source',
  'Tools',
  'Other',
];

// URL segments must be filesystem-safe: lowercase, hyphenated.
const SPACE_SEGMENTS = {
  'web development': 'web-development',
  'open source': 'open-source',
};

export function categoryDir(category) {
  const lower = String(category).toLowerCase();
  if (SPACE_SEGMENTS[lower]) return SPACE_SEGMENTS[lower];
  if (CATEGORIES.map((c) => c.toLowerCase()).includes(lower)) return lower;
  // Fallback for any multi-word category not covered above.
  return lower.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

/**
 * Join a site-absolute route with the configured base path. Astro's
 * import.meta.env.BASE_URL has no trailing slash by default ("/shared-knowledge"),
 * so links are built as withBase('articles/') -> "/shared-knowledge/articles/".
 */
export function withBase(route) {
  const base = import.meta.env.BASE_URL; // e.g. "/shared-knowledge" (no trailing slash)
  return `${base.replace(/\/+$/, '')}/${String(route).replace(/^\/+/, '')}`;
}

export function normalizeSlug(text, maxLength = 80) {
  // Mirrors slugify() in the root repository's github.py: ASCII-folded,
  // lowercased, non-alphanumerics collapsed to single hyphens.
  const folded = text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\x00-\x7F]/g, '');
  const slug = folded
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, maxLength)
    .replace(/-+$/g, '');
  return slug || 'article';
}
