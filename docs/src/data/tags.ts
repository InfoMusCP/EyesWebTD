import type { Tag } from './types';

// The analysis tags of every operator (draft: to be agreed). An operator can have several.
export const tagsBySlug: Record<string, Tag[]> = {
  // L1
  'hit-cell-detector': ['space'],
  'silhouette-body-parts': ['pose'],
  'silhouette-centroids': ['pose'],
  'time-window-synchronizer': ['coordination'],
  // L2
  'bounding-box-filled-area': ['space', 'contraction'],
  'curvature-velocity-correlation': ['trajectory', 'smoothness'],
  'direction-change': ['trajectory'],
  'directness': ['trajectory', 'smoothness'],
  'ellipsoid-sphericity': ['space', 'contraction'],
  'equilibrium': ['space'],
  'kinematics': ['energy'],
  'kinetic-energy': ['energy'],
  'log-dimensionless-jerk': ['smoothness'],
  'points-density': ['space', 'contraction'],
  'spectral-arc-length': ['smoothness'],
  'submovement-count': ['smoothness', 'rhythm'],
  'symmetry': ['space'],
  'trajectory-non-planarity': ['trajectory', 'space'],
  'triangle-symmetry': ['space'],
  // L4
  'ensemble-dominance': ['coordination', 'complexity'],
  // AP
  'binary-pulses-regularity': ['rhythm'],
  'event-synchronization': ['coordination', 'rhythm'],
  'event-synchronization-mecs': ['coordination', 'rhythm'],
  'generalised-auto-correlation': ['rhythm'],
  'multi-scale-entropy': ['complexity'],
  'periodicity': ['rhythm'],
  'phase-locking-value': ['coordination'],
  'rarity': ['complexity'],
  'sample-entropy': ['complexity'],
  'scalar-peak-detector': ['rhythm'],
};
