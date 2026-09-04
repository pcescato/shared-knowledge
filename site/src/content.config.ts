import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// Controlled vocabulary - mirrors CATEGORIES in server.py (spec section 8).
const CATEGORIES = [
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
] as const;

/**
 * The knowledge collection: every Markdown article in the repository of
 * record (the knowledge/ tree, all categories and slugs). Content is loaded
 * from the repo - never duplicated inside the site.
 *
 * `id` is the Astro content ID ("<category-dir>/<slug>", no extension), from
 * which stable URLs and audio paths are derived.
 */
export const collections = {
  knowledge: defineCollection({
    loader: glob({
      pattern: '**/*.md',
      base: new URL('../../knowledge/', import.meta.url),
    }),
    schema: z.object({
      title: z.string(),
      description: z.string(),
      category: z.enum(CATEGORIES),
      tags: z.array(z.string()).default([]),
      source: z.string().default('community'),
      created_at: z.string(),
    }),
  }),
};
