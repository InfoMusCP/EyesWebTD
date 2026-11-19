import type { Operator } from './types';

export const l4: Operator[] = [
  {
    slug: 'ensemble-dominance',
    title: 'Ensemble Dominance',
    opType: 'Ewensembledominance',
    label: 'EW L4 Ensemble Dominance',
    layer: 'L4',
    kind: 'frame',
    tagline: 'Who leads the group? The member with the least complex movement.',
    about: `In an ensemble, the participant whose movement is most regular and predictable acts as the anchor the others react to. Given the complexity index of each participant (from <a href="multi-scale-entropy">Multi Scale Entropy</a>), this operator scores each one and names the leader: the lowest complexity.`,
    formula: 'Dᵢ = 1 − CIᵢ / maxⱼ CIⱼ · leader = argminᵢ CIᵢ',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'one per participant (complexity index)', samples: 'the first sample is read', example: ['complexity0', 'complexity1', 'complexity2'], desc: 'NaN = participant ignored. Negative or infinite = INVALID_INPUT.' },
    ],
    output: {
      shape: 'N + 2 channels × 1 sample',
      channels: [
        { name: 'dominance<i>', desc: 'Score of participant i', range: '0 – 1, NaN if ignored' },
        { name: 'leader_index', desc: 'Index of the leader', range: '0 … N−1, −1 = none' },
        { name: 'leader_complexity', desc: 'Complexity index of the leader' },
      ],
    },
    params: [],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'An infinite or negative index.' },
    ],
    network: [['Dancer A CHOP — speed', 'Merge CHOP', 'Trail CHOP — 10 s', 'EW Multi Scale Entropy', 'Select CHOP — complexity*', 'EW Ensemble Dominance'], ['Dancer B CHOP — speed', 'Merge CHOP'], ['Dancer C CHOP — speed', 'Merge CHOP']],
    recipe: [
      'Compute one scalar per participant (e.g. kinetic energy or speed) and Merge them: one channel each.',
      'Trail a long window (10 s or more) and feed <b>EW AP Multi Scale Entropy</b>.',
      'Select the <code>complexity*</code> channels and wire into <b>EW L4 Ensemble Dominance</b>.',
    ],
    related: ['multi-scale-entropy'],
  },
];

export const ap: Operator[] = [
  {
    slug: 'binary-pulses-regularity',
    title: 'Binary Pulses Regularity',
    opType: 'Ewbinarypulsesregularity',
    label: 'EW AP Binary Pulses Regularity',
    layer: 'AP',
    kind: 'frame',
    tagline: 'Are the beats in the window evenly spaced? A rhythm detector.',
    about: `A pulse is a non-zero sample (a step, a beat, the <code>is_peak</code> of <a href="scalar-peak-detector">Scalar Peak Detector</a>). Over a window, the operator measures the intervals between pulses: the window is regular when it holds at least three pulses and the spread of the intervals is below Threshold. To fire an event at the moment the rhythm <em>becomes</em> regular, take the rising edge of <code>is_regular</code> with a Logic CHOP (<em>Convert Input</em>: Off to On): the operator does not output it.`,
    formula: 'regular ⇔ pulses ≥ 3 and max(I) − min(I) < Threshold',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'exactly 1 (pulse train)', samples: 'a window of pulses (Trail CHOP): hold 3 beats or more', example: ['pulse'] },
    ],
    output: {
      shape: '2 channels × 1 sample',
      channels: [
        { name: 'is_regular', desc: 'The intervals are equal within Threshold', range: '0 / 1' },
        { name: 'pulse_count', desc: 'Pulses in the window', range: '≥ 0' },
      ],
    },
    params: [
      { name: 'Threshold', label: 'Threshold (samples)', default: '1', range: '≥ 1', desc: 'Largest spread of the intervals still regular, exclusive: 1 = intervals must be equal, 2 = may differ by one sample. The slider stops at 20, but you can type larger values, and you need them for human movement: at 50 fps, free movement easily varies by 50–80 samples between beats.' },
    ],
    statuses: [
      { status: 'OK', when: 'The window was evaluated.' },
      { status: 'WARMING_UP', when: 'Fewer than 3 samples: feed a window (a Trail CHOP).' },
      { status: 'INVALID_INPUT', when: 'Not 1 channel; a NaN or infinite sample in the window.' },
    ],
    network: [['EW Kinematics — velocity', 'EW Scalar Peak Detector', 'Trail CHOP — 3 s', 'EW Binary Pulses Regularity', 'Logic CHOP — off to on']],
    recipe: [
      'Produce a pulse train: Scalar Peak Detector on a speed, or a Logic CHOP on a threshold.',
      'Keep a window of the pulses with a Trail CHOP that holds 3 beats or more (e.g. 2–3 s), and wire it into <b>EW AP Binary Pulses Regularity</b>.',
      'Use <code>is_regular</code> as a state ("the rhythm is steady"), or its rising edge with a Logic CHOP (Off to On) to fire an event when a steady rhythm starts.',
    ],
    related: ['scalar-peak-detector', 'periodicity'],
  },
  {
    slug: 'event-synchronization',
    title: 'Event Synchronization',
    opType: 'Eweventsynchronization',
    label: 'EW AP Event Synchronization',
    layer: 'AP',
    kind: 'frame',
    tagline: 'Do two event trains fire together, and who comes first?',
    about: `Quian Quiroga event synchronization: counts how often an event in train x has a matching event in y within Max Lag, and in which order. <code>synchronization</code> (Q) is 1 when every event is matched; <code>delay</code> (q) is positive when x tends to lead, negative when y leads.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '2 (train x, train y)', samples: 'a window of the two trains (Trail CHOP); non-zero = event', example: ['x', 'y'] },
    ],
    output: {
      shape: '2 channels × 1 sample',
      channels: [
        { name: 'synchronization', desc: 'Q: strength of synchrony', range: '0 – 1' },
        { name: 'delay', desc: 'q: who leads (+ x, − y)', range: '−1 – 1' },
      ],
    },
    params: [
      { name: 'Maxlag', label: 'Max Lag (samples)', default: '5', range: '≥ 1', desc: 'Largest distance between two matching events.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than 2 samples: feed a window (a Trail CHOP).' },
      { status: 'INVALID_INPUT', when: 'Fewer than 2 channels.' },
    ],
    network: [['EW Scalar Peak Detector — A', 'Merge CHOP', 'Trail CHOP — 5 s', 'EW Event Synchronization'], ['EW Scalar Peak Detector — B', 'Merge CHOP']],
    recipe: ['Detect events on two signals (peaks, footsteps).', 'Merge them (x first) and trail a window.', 'Wire into <b>EW AP Event Synchronization</b>.'],
    related: ['event-synchronization-mecs', 'scalar-peak-detector'],
  },
  {
    slug: 'event-synchronization-mecs',
    title: 'Event Synchronization MECS',
    opType: 'Eweventsynchronizationmecs',
    label: 'EW AP Event Synchronization MECS',
    layer: 'AP',
    kind: 'frame',
    tagline: 'Synchronisation of many event trains with several event classes.',
    about: `Multi Event Class Synchronization extends event synchronization to N performers and C kinds of event (e.g. steps, claps, turns). Each class gets a synchronisation score, weighted by a kernel over the lag, and an event count. The input is the window (a Trail CHOP of the events): each window is analysed on its own.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'N × C: s0_c0, s0_c1, …, s1_c0, …', samples: 'a window of the trains (Trail CHOP); non-zero = event', example: ['s0_c0', 's0_c1', 's1_c0', 's1_c1'] },
    ],
    output: {
      shape: '2C channels × 1 sample',
      channels: [
        { name: 'synchronization_<k>', desc: 'Synchronisation of class k', range: '0 – 1' },
        { name: 'events_<k>', desc: 'Events of class k', range: '≥ 0' },
      ],
    },
    params: [
      { name: 'Numberofinputs', label: 'Number of Inputs', default: '2', range: '≥ 2', desc: 'Number of performers (series).' },
      { name: 'Numberofeventclasses', label: 'Number of Event Classes', default: '2', range: '≥ 1', desc: 'Classes per series.' },
      { name: 'Maxlag', label: 'Max Lag (samples)', default: '10', desc: 'Largest lag between matched events.' },
      { name: 'Kernel', label: 'Kernel Function', default: 'linear', range: 'uniform · linear · gaussian', desc: 'Weight of a match as a function of the lag.' },
      { name: 'Customgaussian', label: 'Custom Gaussian', default: 'Off', desc: 'Off: sigma = Max Lag, mean = Max Lag / 3.' },
      { name: 'Gaussiansigma', label: 'Gaussian Sigma', default: '10', desc: '' },
      { name: 'Gaussianmean', label: 'Gaussian Mean', default: '3.3333', desc: '' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than 2 samples: feed a window (a Trail CHOP).' },
      { status: 'INVALID_INPUT', when: 'Fewer than N × C channels.' },
    ],
    network: [['Events A CHOP — 2 classes', 'Merge CHOP', 'Trail CHOP — 5 s', 'EW Event Synchronization MECS'], ['Events B CHOP — 2 classes', 'Merge CHOP']],
    recipe: ['Build one binary channel per (performer, class), series-major.', 'Keep a window with a Trail CHOP (a few seconds), set Number of Inputs and Classes to match and wire into <b>EW AP Event Synchronization MECS</b>.'],
    related: ['event-synchronization'],
  },
  {
    slug: 'generalised-auto-correlation',
    title: 'Generalised Auto Correlation',
    opType: 'Ewgeneralisedautocorrelation',
    label: 'EW AP Generalised Auto Correlation',
    layer: 'AP',
    kind: 'frame',
    tagline: 'How often the movement returns to a state after τ samples — a nonlinear autocorrelation.',
    about: `Asks a simple question of a window of movement: <b>if I look τ samples later, how often is the body back in (almost) the same state?</b> That share, between 0 and 1, is the recurrence rate RR(τ). The operator computes it for every lag τ = 1 … Max Lag and outputs the whole curve.

For every pair of samples τ apart it measures the distance between the two states (all channels together, Euclidean distance) and counts the pair as a <i>recurrence</i> when the distance is at most <b>Epsilon</b>. RR(τ) is the fraction of pairs that recur.

How to read the curve: a <b>repetitive</b> movement of period P gives a peak of RR at τ = P (and at 2P, 3P…), because one period later the body is back where it was. A movement that never repeats gives a curve that starts high (at small τ the body has not moved much yet) and decays. Unlike the ordinary autocorrelation it works for several channels together and for nonlinear signals. Used for synchronisation analysis by Varni et al. (2010).`,
    formula: `RR(τ) = (1 / M) · #{ i &lt; M : ‖x[i] − x[i+τ]‖ ≤ ε },  M = N − τ`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'C (any): the state', samples: 'a window of N samples, N &gt; Max Lag', example: ['x', 'y', 'z'], desc: 'All channels form one state vector per sample (e.g. the x, y of a wrist, or a speed). The window is the whole CHOP: build it with a Trail CHOP. Use channels with the <b>same units</b>, because they are mixed in one distance.' },
    ],
    output: {
      shape: '1 channel × Max Lag samples (function) or 1 sample (scalar)',
      channels: [{ name: 'recurrence_rate', desc: 'Function: sample t is RR at lag τ = t + 1 (sample 0 → τ = 1). Scalar: RR at Lag.', range: '0 – 1' }],
      notes: 'In function mode the output is not a time series: its sample index is the lag. View it in the CHOP viewer; find the peak with an Analyze CHOP (Maximum) and its position with a Script/expression to get the period in samples (divide by the sample rate for seconds).',
    },
    params: [
      { name: 'Outputtype', label: 'Output Type', default: 'function', range: 'function · scalar', desc: '<b>Function of Tau</b>: the whole curve RR(1 … Max Lag), to find the period. <b>Scalar</b>: one number, RR at <code>Lag</code>, to monitor live "is the movement repeating with this period?" when you already know the period.' },
      { name: 'Epsilon', label: 'Recurrence Threshold (Epsilon)', default: '0.1', desc: 'How close two states must be to count as "the same", in the <b>units of the input</b> (distance over all channels). Too small: almost nothing recurs, RR ≈ 0 everywhere. Too large: everything recurs, RR ≈ 1 everywhere. Rule of thumb: about 10–20% of the range of the signal (normalised MediaPipe coordinates: 0.05–0.1; positions in mm: tens of mm). Tune it until the curve has visible peaks and valleys.' },
      { name: 'Maxlag', label: 'Max Lag (samples)', default: '10', desc: 'Function mode: the longest lag tested = the number of output samples. Set it a bit above the <b>longest period you expect</b>, in samples (period in seconds × sample rate). The slider stops at 100 but you can type larger values. Must be smaller than the window N; keep N ≥ 2–3 × Max Lag, because large lags rest on fewer pairs (N − τ) and get noisy. The default 10 is only good for very fast oscillations.' },
      { name: 'Lag', label: 'Lag (samples)', default: '1', desc: 'Scalar mode only: the lag τ at which RR is computed, e.g. the period found with the function mode. Must be smaller than N.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'Max Lag (function) or Lag (scalar) not smaller than the number of samples, or NaN / infinity.' },
    ],
    network: [['MediaPipe COMP — wrist x, y', 'Trail CHOP — 6 s', 'EW Generalised Auto Correlation', 'Analyze CHOP — max'], ['EW Generalised Auto Correlation', 'Null CHOP — RR(τ) curve']],
    recipe: [
      'Choose the state: e.g. the x, y of a wrist (same units). Note the sample rate (MediaPipe on a 50 fps video: 50).',
      'Estimate the longest period you care about. A gesture repeated every ~2 s at 50 fps = 100 samples.',
      'Trail CHOP with a window of at least 2–3 periods: 6 s = 300 samples.',
      'Add <b>EW AP Generalised Auto Correlation</b>: Output Type <em>Function of Tau</em>, Max Lag 120 (a bit above 100), Epsilon ≈ 10% of the range of the coordinates (0.05 for normalised MediaPipe).',
      'Look at the output curve: the highest peak after the initial decay is the period in samples (τ = sample index + 1). Divide by 50 for seconds.',
      'Optional: switch to <em>Scalar</em> with Lag = that period to get one live number of "how repetitive" the movement is.',
    ],
    related: ['periodicity'],
  },
  {
    slug: 'multi-scale-entropy',
    title: 'Multi Scale Entropy',
    opType: 'Ewmultiscaleentropy',
    label: 'EW AP Multi Scale Entropy',
    layer: 'AP',
    kind: 'frame',
    tagline: 'Complexity of a signal across time scales.',
    about: `Coarse-grains each channel at scales 1 … Max Scale and computes the sample entropy at each scale. The area under this curve is the <code>complexity</code> index: high for rich, unpredictable movement; low for regular or purely random movement. Feeds <a href="ensemble-dominance">Ensemble Dominance</a>.

The output has <b>one value per scale</b> (the signal averaged over k consecutive samples), not one per embedding. <code>complexity</code>, the area under that curve, is the number to use: low for very regular movement or plain noise, high for movement that is structured at several time scales. Each scale k has N / k points: with 300 samples, scale 6 has 50; below <em>Minimum Points</em> the scale is NaN. Use windows of several seconds.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'N (one per signal)', samples: 'a long window (≥ Minimum Points at the largest scale)', example: ['s0', 's1'] },
    ],
    output: {
      shape: 'N + N × Max Scale channels × 1 sample',
      channels: [
        { name: 'complexity<c>', desc: 'Complexity index of channel c', range: '≥ 0' },
        { name: 'entropy<c>_scale<k>', desc: 'Sample entropy at scale k (NaN if unused)', range: '≥ 0' },
      ],
    },
    params: [
      { name: 'Embeddingdimension', label: 'Embedding Dimension', default: '2', desc: 'Template length m.' },
      { name: 'Tolerance', label: 'Tolerance', default: '0.15', desc: 'r, as a fraction of the standard deviation.' },
      { name: 'Maxscale', label: 'Max Scale', default: '6', desc: 'Number of scales.' },
      { name: 'Minimumpoints', label: 'Minimum Points', default: '30', desc: 'Fewest samples a coarse-grained series must have to be used.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than Minimum Points samples.' },
      { status: 'INVALID_INPUT', when: 'NaN / infinity.' },
    ],
    network: [['EW Kinetic Energy', 'Trail CHOP — 10 s', 'EW Multi Scale Entropy', 'EW Ensemble Dominance']],
    recipe: ['Trail a scalar for 10 s or more.', 'Wire into <b>EW AP Multi Scale Entropy</b>.'],
    notes: ['Minimum Points is 30 by default (500 in PyEyesWeb) so that short live windows give a value; raise it for steadier entropy estimates on longer windows.'],
    related: ['sample-entropy', 'ensemble-dominance'],
  },
  {
    slug: 'periodicity',
    title: 'Periodicity',
    opType: 'Ewperiodicity',
    label: 'EW AP Periodicity',
    layer: 'AP',
    kind: 'frame',
    tagline: 'Which periods make up a repetitive movement (Sethares transform).',
    about: `The Sethares periodicity transform decomposes a window into periodic components and returns their periods (in samples) and powers. <b>Small to Large</b> scans every period up to half the window and keeps those above Threshold; <b>M-Best</b> keeps the M strongest. Good for finding the tempo of a dance.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'N', samples: 'a window (Trail CHOP): at least 2–3 periods', example: ['s0'] },
    ],
    output: {
      shape: '2N channels × (window/2 + 1) or M samples',
      notes: '<b>The samples are entries of a list, not time.</b> Sample k of <code>period0</code> is the k-th period found and sample k of <code>power0</code> its power; unused entries are −1. In the viewer it can look like a series that falls towards zero: it is not. Read <b>sample 0</b> with M-Best and Best Periods 1: the period in samples (divide by the sample rate for seconds) and its power. A power close to 1 means a very periodic window; about 0.7 or less is the level of noise. Use a Window of at least 3 × the longest period you expect. Small to Large gives several neighbouring periods even on a clean sine: prefer M-Best. M-Best can report a multiple of the true period (a sine of period 20 in 128 samples gives 40). Planned: one sample per channel with the dominant period (in seconds) and its strength.',
      channels: [
        { name: 'period<c>', desc: 'Periods found for channel c', range: 'samples, −1 = unused' },
        { name: 'power<c>', desc: 'Power of each period', range: '≥ 0, −1 = unused' },
      ],
    },
    params: [
      { name: 'Method', label: 'Method', default: 'small2large', range: 'small2large · mbest', desc: '' },
      { name: 'Threshold', label: 'Threshold (small2large)', default: '0.1', desc: 'Minimum relative power kept.' },
      { name: 'Bestperiods', label: 'Best Periods', default: '3', desc: 'M of M-Best.' },
      { name: 'Sortbypower', label: 'Sort by power', default: 'Off', desc: '' },
    ],
    statuses: [
      { status: 'OK', when: 'The window was evaluated.' },
      { status: 'WARMING_UP', when: 'Fewer than 8 samples: feed a window (a Trail CHOP).' },
      { status: 'NO_OUTPUT', when: 'No input.' },
      { status: 'INVALID_INPUT', when: 'A constant window, or a NaN / infinity in the window.' },
    ],
    network: [['EW Kinematics — velocity', 'Trail CHOP — 4 s', 'EW Periodicity — mbest', 'Select CHOP — period0', 'Math CHOP — to BPM']],
    recipe: ['Keep a window of a scalar with a Trail CHOP (2–3 periods or more) and wire it into <b>EW AP Periodicity</b>, M-Best with M = 3.', 'Convert the period to BPM: <code>60 · rate / period</code>.'],
    related: ['generalised-auto-correlation', 'binary-pulses-regularity'],
  },
  {
    slug: 'phase-locking-value',
    title: 'Phase Locking Value',
    opType: 'Ewphaselockingvalue',
    label: 'EW AP Phase Locking Value',
    layer: 'AP',
    kind: 'frame',
    tagline: 'Do two oscillating movements keep a constant phase relation?',
    about: `Extracts the instantaneous phase of two signals (Hilbert transform, optional band-pass) and measures how constant their phase difference is over the window. 1 = phase-locked (moving in unison or in a fixed offset), 0 = unrelated. Ideal for two dancers swaying together.`,
    formula: 'PLV = | (1/N) Σ e^{i(φₓ − φᵧ)} |',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '2 (x, y)', samples: 'a window of the same length', example: ['x', 'y'] },
    ],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'phase_locking_value', desc: 'Phase synchrony', range: '0 – 1' }],
    },
    params: [
      { name: 'Usefilter', label: 'Apply Bandpass Filter', default: 'Off', desc: 'Filter both signals before the Hilbert transform.' },
      { name: 'Lowfrequency', label: 'Low Frequency (Hz)', default: '0.5', desc: '' },
      { name: 'Highfrequency', label: 'High Frequency (Hz)', default: '4', desc: 'Keep below half the sample rate.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'Fewer than 2 channels, NaN / infinity, or a constant signal (no phase).' },
    ],
    network: [['Dancer A — hip x', 'Merge CHOP', 'Trail CHOP — 4 s', 'EW Phase Locking Value'], ['Dancer B — hip x', 'Merge CHOP']],
    recipe: ['Merge one oscillating signal per performer.', 'Trail a few periods and wire into <b>EW AP Phase Locking Value</b>.', 'Turn on the band-pass to focus on the sway frequency.'],
    related: ['time-window-synchronizer', 'event-synchronization'],
  },
  {
    slug: 'rarity',
    title: 'Rarity',
    opType: 'Ewrarity',
    label: 'EW AP Rarity',
    layer: 'AP',
    kind: 'stream',
    sourceDesc: 'Stream: a live source. The output is always <b>one sample</b>: the rarity of the newest sample (a source can give 1 or 2 samples in a frame, all of them feed the memory). Clip: a recording, one value for every sample, the memory starting afresh at every cook.',
    tagline: 'How unusual is the movement of the last moments compared with the recent past?',
    about: `Flags the <b>new gestures</b>. At every sample it takes the last <em>Pattern</em> seconds of the signal as a pattern and compares it with the patterns of the last <em>Memory</em> seconds. If something similar happened recently the value is about <b>1</b>; if nothing like it did, the value is larger (3 and above is a clear novelty). It works on <b>any signal</b>: a scalar (a speed, an energy), a position, several features together.

How it compares: the distance between two patterns is Euclidean, with every channel divided by its own standard deviation (so no channel dominates because of its unit); the operator averages the distance from the current pattern to its <em>Neighbours</em> nearest patterns in the memory and divides it by the median of that same distance, so the result has no unit. A movement you repeat becomes <b>familiar</b> (its patterns enter the memory) and its rarity falls back to about 1; a movement you did not do for <em>Memory</em> seconds is new again.

Unlike the EyesWeb Rarity (a bin of the <em>current level</em> of the signal), it sees a pause, a change of amplitude or of speed, a different shape. The two EyesWeb methods stay in PyEyesWeb.`,
    formula: 'rarity = d / median(d), d = mean distance to the nearest Neighbours patterns of the memory',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'N (any signal)', samples: 'live samples (1 or 2 per frame): the operator keeps its own memory; or a recording (Clip)', example: ['x', 'y'], desc: 'A position (x, y [, z]), a scalar (speed, energy) or several features. Channels with different units are fine: each one is scaled by its own standard deviation.' },
    ],
    output: {
      shape: '1 channel × 1 sample (Stream) · one sample per input sample (Clip)',
      channels: [{ name: 'rarity', desc: 'Novelty of the newest pattern: about 1 = familiar, larger = unusual', range: '≥ 0 (0 while warming up and for an exact repeat)' }],
      notes: 'The values are only meaningful once the memory holds twice the pattern length of patterns to compare with: about <b>3.5 × Pattern</b> after the start (1.75 s with the default 0.5 s). Until then the status is WARMING_UP and the output is 0. A rare event is <b>rarity &gt; 3</b>: take it with a Logic CHOP or a Trigger CHOP.',
    },
    params: [
      { name: 'Memory', label: 'Memory (s)', default: '5', range: '≥ 0.1', desc: 'How long the operator remembers. A movement that has not been repeated for this long is new again; a movement repeated within it becomes familiar. 5–10 s suits a performance; longer remembers more variants and costs more.' },
      { name: 'Pattern', label: 'Pattern (s)', default: '0.5', range: '≥ 0.02', desc: 'The length of a "gesture": the stretch of signal that is compared. Short (0.25–0.5 s): it notices changes of direction and rhythm. Long (1 s and more): it compares whole phrases and only larger changes stand out. The memory is at least 3 × Pattern.' },
      { name: 'Neighbours', label: 'Neighbours', default: '5', range: '≥ 1', desc: 'How many of the nearest patterns of the memory are averaged. Higher: a single chance resemblance does not make a gesture look familiar. Live: changing it keeps the memory.' },
      { name: 'Compare', label: 'Compare', default: 'values', range: 'values · shape', desc: '<b>values</b>: the pattern as it is, so the <em>level</em> counts too (use it for scalars: a burst of energy higher than usual is rare even if its shape is familiar). <b>shape</b>: the newest sample is subtracted from the pattern, so only the shape of the movement counts and not where it happens (use it for positions: the same gesture done somewhere else is familiar). Changing it restarts the memory.' },
    ],
    statuses: [
      { status: 'OK', when: 'The memory is full enough: the output is the rarity.' },
      { status: 'WARMING_UP', when: 'The memory is still filling (about 3.5 × Pattern after the start, a Reset, or a change of Memory, Pattern, Compare, the channels or the sample rate). The output is 0.' },
      { status: 'INVALID_INPUT', when: 'A NaN or infinite sample (skipped, not used); not a timeslice is accepted in Stream.' },
    ],
    network: [['MediaPipe COMP — wrist', 'Select CHOP — x, y', 'EW Rarity — Compare = shape', 'Logic CHOP — above 3', 'Trigger CHOP — new gesture'], ['EW Kinematics — velocity', 'EW Rarity — Compare = values']],
    recipe: [
      'Choose the signal: the x, y (z) of a joint, or a scalar such as the speed from <b>EW L2 Kinematics</b> or an energy. Several channels can go together.',
      'Add <b>EW AP Rarity</b>. For positions set <em>Compare</em> to <b>shape</b>; for scalars leave <b>values</b>.',
      'Set <em>Pattern</em> to the duration of a typical gesture (0.5 s) and <em>Memory</em> to a few seconds (5–10 s).',
      'Wait for the warm-up (about 1.75 s with the defaults). Then read <code>rarity</code>: about 1 while the movement is familiar.',
      'Fire an event when it crosses 3: a Logic CHOP (greater than 3) into a Trigger CHOP or a Count CHOP.',
    ],
    notes: [
      'It measures how new the <b>movement</b> is, not how rare the <em>current level</em> of the signal is (that is what the two methods of PyEyesWeb do).',
      'A perfectly regular signal makes its own typical distance tiny, so even small changes stand out: add a little noise tolerance by raising Neighbours, or smooth the input.',
      'Cost: the work per sample grows with Memory and with the number of channels; Memory 10 s at 60 fps with a few channels is comfortable.',
    ],
    related: ['kinematics', 'scalar-peak-detector', 'multi-scale-entropy'],
  },
  {
    slug: 'sample-entropy',
    title: 'Sample Entropy',
    opType: 'Ewsampleentropy',
    label: 'EW AP Sample Entropy',
    layer: 'AP',
    kind: 'frame',
    tagline: 'How predictable a signal is.',
    about: `Counts how often patterns of length m that are similar (within tolerance r) remain similar at length m + 1, and gives <b>one number</b>, SampEn(m, r) as in Richman &amp; Moorman (2000), with m = 2 by default.

How to read it: <b>0</b> = perfectly predictable (a clean sine); about <b>1 – 2.5</b> = irregular (noise gives high values); <b>inf</b> or NaN = no matching patterns (the window is too short or r too small). Compare values (the same gesture fluid vs jerky, the same dancer over time): the absolute number depends on the window, on r and on the sample rate.`,
    formula: 'SampEn = −ln(A / B)',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'exactly 1', samples: 'a window: at least 100–200 samples (and more than m + 1)', example: ['s'] },
    ],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'sample_entropy', desc: 'SampEn(m, r) of the window', range: '≥ 0 (inf if no match)' }],
    },
    params: [
      { name: 'Embeddingdimension', label: 'Embedding Dimension (m)', default: '2', desc: 'Template length m of the literature: patterns of m samples are compared, then of m + 1.' },
      { name: 'Useabsolutetolerance', label: 'Absolute Tolerance', default: 'Off', desc: 'Use Tolerance as an absolute r.' },
      { name: 'Relativetolerance', label: 'Relative Tolerance (× std)', default: '0.2', desc: 'r = this × the standard deviation of the window (the usual 0.2). Used unless Absolute Tolerance is on.' },
      { name: 'Tolerance', label: 'Absolute Tolerance (r)', default: '0.2', desc: 'r in the units of the signal, used when Absolute Tolerance is on.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'Not 1 channel, too few samples, NaN / infinity.' },
    ],
    network: [['EW Kinetic Energy', 'Trail CHOP — 5 s', 'EW Sample Entropy', 'Null CHOP']],
    recipe: ['Trail one scalar for a few seconds (at least 100–200 samples).', 'Wire into <b>EW AP Sample Entropy</b>: Embedding Dimension 2, Relative Tolerance 0.2.', 'Compare the value between gestures.'],
    related: ['multi-scale-entropy'],
  },
  {
    slug: 'scalar-peak-detector',
    title: 'Scalar Peak Detector',
    opType: 'Ewscalarpeakdetector',
    label: 'EW AP Scalar Peak Detector',
    layer: 'AP',
    kind: 'stream',
    tagline: 'Fires a pulse on every peak of a signal.',
    about: `Watches a stream through a sliding window and outputs 1 on the sample where a peak above Threshold is found. Turns a continuous signal (speed, energy) into events: accents, steps, hits. Feeds <a href="binary-pulses-regularity">Binary Pulses Regularity</a> and the event synchronisation operators.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'exactly 1', samples: 'live timeslice (Stream) or a recording (Clip)', example: ['s'] },
    ],
    output: {
      shape: '1 channel × one sample per input sample',
      channels: [{ name: 'is_peak', desc: '1 on a peak', range: '0 / 1' }],
    },
    params: [
      { name: 'Window', label: 'Window (samples)', default: '5', range: '≥ 2', desc: 'Samples compared at each step. For slow movements it must span a good part of a gesture: 0.5–1 s of samples (25–50 at 50 fps). The slider stops at 50, you can type more.' },
      { name: 'Threshold', label: 'Threshold', default: '0.01', desc: 'Minimum <b>range</b> <code>max − min</code> inside the window, in the <b>units of the signal</b>: it is not the height of the peak. Set it above the noise: about 10 % of the typical range of the signal (look at it in the viewer first). Too low: false peaks; too high: peaks missed.' },
    ],
    statuses: [
      { status: 'OK', when: 'Samples processed.' },
      { status: 'WARMING_UP', when: 'The first Window − 1 samples.' },
      { status: 'INVALID_INPUT', when: 'Not 1 channel; NaN / infinity (sample skipped); not a timeslice in Stream mode.' },
    ],
    network: [['EW Kinematics — velocity', 'EW Scalar Peak Detector', 'Trigger CHOP', 'Audio File In CHOP — cue']],
    recipe: ['Wire a speed or energy signal into <b>EW AP Scalar Peak Detector</b>.', 'Use is_peak with a Trigger or Count CHOP.'],
    notes: [
      'A peak is a switch from rising to falling: within the window the maximum comes <b>before</b> the minimum after the signal was rising. So it is reported with a <b>delay</b> of up to about Window samples after the real maximum (a longer Window = a later, but steadier, trigger).',
      'A live source can give 2 samples in a frame, and the pulse can sit on the first of them. Read is_peak with a <b>Count</b> or <b>Trigger CHOP</b>, which see every sample, not with an expression that reads one sample.',
    ],
    related: ['binary-pulses-regularity', 'submovement-count'],
  },
];
