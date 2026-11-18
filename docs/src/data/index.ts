import { l1 } from './l1';
import { l2 } from './l2';
import { l4, ap } from './ap';
import { tagsBySlug } from './tags';
import type { Operator, Layer, Tag } from './types';

export const operators: Operator[] = [...l1, ...l2, ...l4, ...ap].map((o) => ({ ...o, tags: tagsBySlug[o.slug] ?? [] }));
export const tagOrder: Tag[] = ['pose', 'space', 'contraction', 'trajectory', 'energy', 'smoothness', 'complexity', 'rhythm', 'coordination'];
export const layerOrder: Layer[] = ['L1', 'L2', 'L4', 'AP'];
export const bySlug = (slug: string) => operators.find((o) => o.slug === slug);
export const byLayer = (layer: Layer) => operators.filter((o) => o.layer === layer);
