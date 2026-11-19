// The data model of an operator page. Every page of /operators is generated from one `Operator` record:
// edit the record, not the page. Text fields accept inline HTML (<code>, <em>, <b>, <br>).

export type Layer = 'L1' | 'L2' | 'L3' | 'L4' | 'AP';

/**
 * How the operator cooks (the base class of the CHOP):
 * - frame:  the input is the window (a Trail CHOP, a File In); one result per cook; nothing is kept between cooks.
 * - sample: every input sample is one frame (a pose, a point cloud); one output sample per input sample; no state.
 *           Gets the Source parameter (stream / clip).
 * - stream: fed sample after sample, keeps state between cooks. Gets Source and Reset.
 * - buffer: keeps state between cooks, but the output is not one sample per input sample. Gets Reset.
 */
export type Kind = 'frame' | 'sample' | 'stream' | 'buffer';

export type Status = 'OK' | 'WARMING_UP' | 'NO_OUTPUT' | 'INVALID_INPUT';

export interface Port {
  /** "Input 0", "Input 1", "TOP" */
  port: string;
  family: 'CHOP' | 'TOP';
  /** Channel layout, e.g. "2 or 3 (x, y [, z])" */
  channels: string;
  /** What the samples are, e.g. "a window of N positions over time" */
  samples: string;
  /** Example channel names, drawn in the diagram */
  example: string[];
  desc?: string;
  optional?: boolean;
}

export interface Channel {
  name: string;
  desc: string;
  range?: string;
}

export interface Param {
  /** Python name: op('x').par.<name> */
  name: string;
  label: string;
  default: string;
  range?: string;
  desc: string;
}

/** What kind of analysis an operator performs. An operator can have several; layers stay as they are. */
export type Tag = 'pose' | 'space' | 'contraction' | 'trajectory' | 'energy' | 'smoothness' | 'complexity' | 'rhythm' | 'coordination';

export const tagInfo: Record<Tag, { name: string; desc: string }> = {
  pose: { name: 'Pose', desc: 'Where the parts of the body are: the posture.' },
  space: { name: 'Space', desc: 'Shape, geometry and position of the body at one instant.' },
  contraction: { name: 'Contraction / Expansion', desc: 'How much space the body takes: gathered or open.' },
  trajectory: { name: 'Trajectory', desc: 'The shape of the path the body follows.' },
  energy: { name: 'Energy', desc: 'How much and how fast the body moves.' },
  smoothness: { name: 'Smoothness', desc: 'The quality of the movement: fluid or jerky.' },
  complexity: { name: 'Complexity', desc: 'Predictability and rarity: entropy and novelty.' },
  rhythm: { name: 'Rhythm', desc: 'Periodicity, events and regularity of beats.' },
  coordination: { name: 'Coordination', desc: 'Relations between signals or between people.' },
};

export interface Operator {
  slug: string;
  title: string;
  /** TouchDesigner operator type, e.g. Ewdirectness */
  opType: string;
  /** Operator label in the OP Create dialog */
  label: string;
  layer: Layer;
  kind: Kind;
  /** Overrides the description of the Source parameter of a sample-wise operator */
  sourceDesc?: string;
  /** Analysis tags, set in data/tags.ts */
  tags?: Tag[];
  /** One line, shown on the cards */
  tagline: string;
  /** What it measures and why you would use it (HTML paragraphs separated by \n\n) */
  about: string;
  /** Optional formula / definition shown in a callout */
  formula?: string;
  inputs: Port[];
  output: {
    /** e.g. "1 channel × 1 sample" */
    shape: string;
    channels: Channel[];
    notes?: string;
  };
  params: Param[];
  statuses: { status: Status; when: string }[];
  /** Typical network: each chain is a path of node labels, "Family" is the last word (CHOP, TOP, DAT, COMP) or EW ... */
  network: string[][];
  /** Step-by-step recipe to build the network */
  recipe: string[];
  /** Caveats, known issues, open questions */
  notes?: string[];
  related?: string[];
  references?: string[];
}

export const layerInfo: Record<Layer, { name: string; short: string; desc: string }> = {
  L1: { name: 'Physical signals', short: 'L1', desc: 'From sensors and images to clean, synchronised signals: grids, silhouettes, time windows.' },
  L2: { name: 'Low-level features', short: 'L2', desc: 'Instant descriptors of one body or one trajectory: kinematics, energy, symmetry, smoothness, shape.' },
  L3: { name: 'Mid-level features', short: 'L3', desc: 'Features over gestures and movement units. None in this release.' },
  L4: { name: 'High-level features', short: 'L4', desc: 'Expressive and social qualities, e.g. who leads a group.' },
  AP: { name: 'Analysis primitives', short: 'AP', desc: 'Signal tools usable at any layer: entropy, recurrence, synchronisation, periodicity, peaks.' },
};

export const kindInfo: Record<Kind, { name: string; desc: string }> = {
  frame: { name: 'Window', desc: 'The input is the window: feed it a Trail CHOP (live) or a File In (recording). One result per cook, nothing kept between cooks.' },
  sample: { name: 'Per sample', desc: 'Every input sample is one frame (a pose, a point cloud): one output sample per input sample, no memory.' },
  stream: { name: 'Stream', desc: 'Fed sample after sample; keeps its state between cooks (filters, previous frame).' },
  buffer: { name: 'Buffer', desc: 'Keeps state between cooks (a window, events, a filter) and outputs one result per cook.' },
};
