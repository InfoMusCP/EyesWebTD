import type { Operator } from './types';

const SPEED_IN = {
  port: 'Input 0', family: 'CHOP' as const, channels: '1 (speed profile; extra channels ignored)',
  samples: 'a window of ≥ 10 samples over time (Trail CHOP)', example: ['speed'],
  desc: 'The sample rate of the CHOP is used as the sampling rate: keep it real (e.g. 30 or 60 Hz).',
};

export const l2: Operator[] = [
  {
    slug: 'bounding-box-filled-area',
    title: 'Bounding Box Filled Area',
    opType: 'Ewboundingboxfilledarea',
    label: 'EW L2 Bounding Box Filled Area',
    layer: 'L2',
    kind: 'sample',
    tagline: 'How much of its bounding box the body fills: a 3D contraction index.',
    about: `Takes the joints of a body as a point cloud and compares the surface of their 3D convex hull with the surface of their axis-aligned bounding box. A body curled up fills its box; a body with limbs spread out leaves it mostly empty.

It is the classic EyesWeb <em>contraction index</em>: low values = expansion, high values = contraction.`,
    formula: 'contraction_index = area(convex hull) / area(bounding box)',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '3N, joint-major: j0x j0y j0z j1x …', samples: 'one pose per sample', example: ['j0x', 'j0y', 'j0z', 'j1x', '…'], desc: 'At least 4 joints. The channel count must be a multiple of 3.' },
    ],
    output: {
      shape: '1 channel × one sample per input sample',
      channels: [{ name: 'contraction_index', desc: 'Hull surface over box surface', range: '≈ 0 – 1' }],
    },
    params: [
      { name: 'Epsilon', label: 'BBox Area Epsilon', default: '1e-6', desc: 'A box with a smaller surface is considered empty (INVALID_INPUT for that sample).' },
    ],
    statuses: [
      { status: 'OK', when: 'Every sample was computed.' },
      { status: 'INVALID_INPUT', when: 'Channels not a multiple of 3, fewer than 4 points, a box with no extent, NaN / infinity, or the input is not a timeslice in Stream mode.' },
    ],
    network: [['MediaPipe COMP — pose', 'Select CHOP — 33 × x,y,z', 'Shuffle CHOP — joint-major', 'EW Bounding Box Filled Area', 'Filter CHOP', 'Null CHOP']],
    recipe: [
      'Select the x, y, z channels of the joints you want, ordered joint by joint (<code>j0x j0y j0z j1x …</code>).',
      'Wire into <b>EW L2 Bounding Box Filled Area</b>. Source = Stream for live data, Clip for a recorded clip.',
      'Smooth the output (Filter / Lag CHOP) and map it to a visual parameter.',
    ],
    related: ['points-density', 'ellipsoid-sphericity'],
  },
  {
    slug: 'curvature-velocity-correlation',
    title: 'Curvature Velocity Correlation',
    opType: 'Ewcurvaturevelocitycorrelation',
    label: 'EW L2 Curvature Velocity Correlation',
    layer: 'L2',
    kind: 'buffer',
    tagline: 'Smoothness from the two-thirds power law: does speed slow down in the curves?',
    about: `Natural human movement slows down where the path bends (the two-thirds power law). This operator computes curvature and speed of a trajectory with Savitzky–Golay filters and relates their logarithms: a fluid movement follows the law closely.

<b>Simplified</b> (default) gives <code>1 / (std log k · std log v)</code>, capped at Upper Limit; <b>Pearson</b> gives the correlation of the logarithms (negative for movement that follows the law).`,
    formula: 'Simplified: 1 / (σ(log κ) · σ(log v)) · Pearson: corr(log κ, log v)',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '1, 2 or 3 (x [, y [, z]])', samples: 'a window of positions (≥ Filter Window + 1 samples)', example: ['x', 'y', 'z'] },
    ],
    output: {
      shape: '5 channels × as many samples as the input',
      channels: [
        { name: 'smoothness', desc: 'The index (repeated on every sample)', range: 'Simplified: 0 – Upper Limit · Pearson: −1 – 1' },
        { name: 'curvature', desc: 'Curvature at each sample' },
        { name: 'velocity', desc: 'Speed at each sample (per second unless Differentiate is on)' },
        { name: 'log_curvature_std', desc: 'Std of log curvature (repeated)' },
        { name: 'log_speed_std', desc: 'Std of log speed (repeated)' },
      ],
    },
    params: [
      { name: 'Filterwindowlength', label: 'Filter Window Length (odd)', default: '9', range: '5 – 201', desc: 'Savitzky–Golay window. Even values are made odd.' },
      { name: 'Filterpolyorder', label: 'Filter Polyorder', default: '3', range: '3 – 10', desc: 'Polynomial order of the filter (< window).' },
      { name: 'Differentiate', label: 'Differentiate', default: 'Off', desc: 'Output velocity per sample instead of per second.' },
      { name: 'Standarddeviationthreshold', label: 'Standard Deviation Threshold', default: '0.0001', desc: 'Below it a std is considered zero.' },
      { name: 'Upperlimit', label: 'Upper Limit', default: '100', desc: 'Cap of the Simplified index.' },
      { name: 'Correlationtype', label: 'Correlation Type', default: 'simplified', range: 'simplified · pearson', desc: 'Formula of the index.' },
      { name: 'Inputkind', label: 'Input Kind', default: 'stream', range: 'stream · static', desc: 'Stream: successive windows of a moving signal; Static: one recording.' },
    ],
    statuses: [
      { status: 'OK', when: 'The index was computed.' },
      { status: 'WARMING_UP', when: 'Fewer than Filter Window + 1 samples, or the first window of a given shape (the filters need a previous window).' },
      { status: 'INVALID_INPUT', when: 'Curvature or speed does not vary, a non-finite series, or NaN / infinity in the input.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — wrist x,y', 'Trail CHOP — 2 s', 'EW Curvature Velocity Correlation', 'Select CHOP — smoothness']],
    recipe: [
      'Select the x, y (or x, y, z) of a joint and keep a 1–2 s window with a Trail CHOP.',
      'Wire into <b>EW L2 Curvature Velocity Correlation</b>; wait one cook for the filters.',
      'Draw circles and figure-eights in the air: fluid drawing raises the Simplified index.',
    ],
    notes: ['With Pearson, expect negative values on real movement: curvature and speed vary in opposite directions (the two-thirds power law).'],
    related: ['kinematics', 'spectral-arc-length', 'log-dimensionless-jerk'],
  },
  {
    slug: 'direction-change',
    title: 'Direction Change',
    opType: 'Ewdirectionchange',
    label: 'EW L2 Direction Change',
    layer: 'L2',
    kind: 'frame',
    tagline: 'Sharp right-angle turns of a path, and the area it sweeps.',
    about: `Two measures of the path of one point over a window.

<b>Cosine</b>: compares the first half and the second half of the path (oldest → middle → newest). It is 1 for a turn of about 90° and falls to 0 at <code>Epsilon</code> from it; a straight line or a U-turn give 0. A marker of impulsive, sudden changes.

<b>Polygon</b>: subsamples the path to N points and returns the area of the polygon they enclose: large for broad sweeping gestures, small for narrow or linear ones.`,
    formula: 'a = 1 − θ/π · cosine = 1 − |a − 0.5| / ε  (if |a − 0.5| < ε, else 0)',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '2 or 3 (x, y [, z])', samples: 'a window of ≥ 3 positions over time (Trail CHOP)', example: ['x', 'y', 'z'] },
    ],
    output: {
      shape: '1 or 2 channels × 1 sample',
      channels: [
        { name: 'cosine', desc: 'Right-angle turn score', range: '0 – 1' },
        { name: 'polygon', desc: 'Area enclosed by the subsampled path', range: '≥ 0, unit²' },
      ],
      notes: 'The channels follow the Cosine / Polygon toggles. With both off, cosine is output.',
    },
    params: [
      { name: 'Epsilon', label: 'Cosine Epsilon', default: '0.5', range: '> 0', desc: 'Half-width of the interval around a right angle where the cosine metric is non-zero.' },
      { name: 'Numberofsubsamples', label: 'Number of Subsamples', default: '20', range: '≥ 1', desc: 'Points of the polygon.' },
      { name: 'Cosine', label: 'Cosine Metric', default: 'On', desc: 'Output the cosine channel.' },
      { name: 'Polygon', label: 'Polygon Metric (area)', default: 'On', desc: 'Output the polygon channel.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than 3 samples.' },
      { status: 'INVALID_INPUT', when: 'Not 2 or 3 channels, or NaN / infinity.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — hand x,y', 'Trail CHOP — 1 s', 'EW Direction Change', 'Trigger CHOP — cosine > 0.8']],
    recipe: [
      'Select one joint (x, y [, z]) and keep a short window (0.5–1 s) with a Trail CHOP.',
      'Wire into <b>EW L2 Direction Change</b>.',
      'Trigger events when <code>cosine</code> exceeds a threshold; map <code>polygon</code> to size or spread.',
    ],
    related: ['directness', 'kinematics'],
  },
  {
    slug: 'directness',
    title: 'Directness',
    opType: 'Ewdirectness',
    label: 'EW L2 Directness',
    layer: 'L2',
    kind: 'frame',
    tagline: 'Straight or wandering? Distance travelled vs ground covered.',
    about: `Ratio between the straight-line distance from the oldest to the newest point of the window and the length of the path actually travelled. 1 is a perfectly direct movement; values near 0 are meandering or back-and-forth movements.`,
    formula: 'directness = |p_newest − p_oldest| / Σ |p_i+1 − p_i|',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '2 or 3 (x, y [, z])', samples: 'a window of ≥ 2 positions over time', example: ['x', 'y', 'z'] },
    ],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'directness_index', desc: 'Straightness of the path', range: '0 – 1' }],
    },
    params: [],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Only one sample.' },
      { status: 'INVALID_INPUT', when: 'Fewer than 2 channels, or NaN / infinity.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — hand x,y', 'Trail CHOP — 1 s', 'EW Directness', 'Lag CHOP']],
    recipe: [
      'Select a joint and keep a window with a Trail CHOP (try 1 s).',
      'Wire into <b>EW L2 Directness</b> and smooth the output.',
    ],
    related: ['direction-change', 'trajectory-non-planarity'],
  },
  {
    slug: 'ellipsoid-sphericity',
    title: 'Ellipsoid Sphericity',
    opType: 'Ewellipsoidsphericity',
    label: 'EW L2 Ellipsoid Sphericity',
    layer: 'L2',
    kind: 'sample',
    tagline: 'How round the body volume is: Wadell sphericity of the best-fit ellipsoid.',
    about: `Fits an ellipsoid to the joints of the body (PCA) and measures how close it is to a sphere: 1 for a sphere, lower for an elongated or flat shape. A standing body is elongated; a crouched, compact body is rounder.

In <em>sizes</em> mode, give the three axes yourself and only the sphericity is computed.`,
    formula: 'ψ = π^⅓ (6V)^⅔ / A  (A: Thomsen surface of the ellipsoid)',
    inputs: [
      { port: 'Input 0 (points)', family: 'CHOP', channels: '3N, joint-major', samples: 'one point cloud per sample', example: ['j0x', 'j0y', 'j0z', '…'], desc: 'At least 2 points.' },
      { port: 'Input 0 (sizes)', family: 'CHOP', channels: '3 (size x, y, z)', samples: 'one ellipsoid per sample', example: ['sx', 'sy', 'sz'], desc: 'Positive sizes.', optional: true },
    ],
    output: {
      shape: '1 (sizes) or 5 (points) channels × one sample per input sample',
      channels: [
        { name: 'sphericity', desc: 'Wadell sphericity', range: '0 – 1' },
        { name: 'axis_ratio', desc: 'Minor / major radius (points mode)', range: '0 – 1' },
        { name: 'radii_0 … radii_2', desc: 'Major, middle, minor radius (points mode)', range: 'unit of the input' },
      ],
    },
    params: [
      { name: 'Inputmode', label: 'Input Mode', default: 'points', range: 'points · sizes', desc: 'Point cloud with PCA fit, or the three sizes directly.' },
    ],
    statuses: [
      { status: 'OK', when: 'Every sample was computed.' },
      { status: 'INVALID_INPUT', when: 'Wrong channel count, fewer than 2 points, no extent, non-positive sizes, NaN / infinity.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — joints x,y,z', 'EW Ellipsoid Sphericity', 'Select CHOP — sphericity', 'Null CHOP']],
    recipe: [
      'Select the joints (joint-major x, y, z).',
      'Wire into <b>EW L2 Ellipsoid Sphericity</b> with Input Mode = points.',
    ],
    related: ['bounding-box-filled-area', 'points-density'],
  },
  {
    slug: 'equilibrium',
    title: 'Equilibrium',
    opType: 'Ewequilibrium',
    label: 'EW L2 Equilibrium',
    layer: 'L2',
    kind: 'sample',
    tagline: 'Is the barycenter inside the support of the feet?',
    about: `Builds an elliptical support region between the two feet on the floor plane (major axis from foot to foot, enlarged by Margin) and measures where the barycenter falls in it: 1 when it is exactly in the centre, falling to 0 at the border and outside. Also outputs the direction of the foot-to-foot vector.`,
    formula: 'a = d/2 + m · b = m · w_y · E = 1 − √((x′/a)² + (y′/b)²), 0 outside',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '6: lf_x, lf_y, rf_x, rf_y, bary_x, bary_y', samples: 'one posture per sample', example: ['lf_x', 'lf_y', 'rf_x', 'rf_y', 'bary_x', 'bary_y'], desc: 'Coordinates on the <b>floor plane</b>: for Y-up data use x and z.' },
    ],
    output: {
      shape: '2 channels × one sample per input sample',
      channels: [
        { name: 'equilibrium', desc: 'Balance within the support', range: '0 – 1' },
        { name: 'angle', desc: 'Direction of the left → right foot vector', range: '−180 – 180°' },
      ],
    },
    params: [
      { name: 'Margin', label: 'Margin', default: '0.1', desc: 'Added to the support ellipse, in the unit of the data (0.1 = 10 cm for metres). Also sets the minor axis.' },
      { name: 'Yweight', label: 'Y Weight', default: '0.5', desc: 'Minor semi-axis = Margin × Y Weight.' },
    ],
    statuses: [
      { status: 'OK', when: 'Every sample was computed.' },
      { status: 'INVALID_INPUT', when: 'Fewer than 6 channels, coincident feet, NaN / infinity.' },
    ],
    network: [['Mocap / Kinect CHOP', 'Select CHOP — feet x,z', 'Merge CHOP', 'EW Equilibrium', 'Null CHOP'], ['Mocap / Kinect CHOP', 'Analyze CHOP — barycenter x,z', 'Merge CHOP']],
    recipe: [
      'Select the left and right foot positions on the floor plane (x and z for Y-up data).',
      'Compute the barycenter (e.g. average of the hip joints, or of all joints) on the same plane.',
      'Merge in the order lf_x, lf_y, rf_x, rf_y, bary_x, bary_y and wire into <b>EW L2 Equilibrium</b>.',
      'Adjust Margin to the unit of your data (metres: 0.1; normalised 0–1 image: smaller).',
    ],
    notes: ['With normalised MediaPipe image coordinates there is no floor plane; use world landmarks.'],
    related: ['points-density'],
  },
  {
    slug: 'kinematics',
    title: 'Kinematics',
    opType: 'Ewkinematics',
    label: 'EW L2 Kinematics',
    layer: 'L2',
    kind: 'stream',
    tagline: 'Smoothed velocity, acceleration, jerk, curvature and direction of a moving point.',
    about: `The workhorse of the library. Feeds a point sample after sample through Savitzky–Golay filters and outputs its derivatives: speed, acceleration, jerk, path curvature, direction of motion and the smoothed position.

<em>Tangential</em> gives magnitudes (one channel per quantity), <em>Components</em> gives one channel per axis. Its <code>velocity</code> output is the speed profile that Spectral Arc Length, Log Dimensionless Jerk and Submovement Count expect.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '1, 2 or 3 (x [, y [, z]])', samples: 'live timeslice (Stream) or a recording (Clip)', example: ['x', 'y', 'z'], desc: 'The sample rate gives dt: keep it real.' },
    ],
    output: {
      shape: 'one channel per selected quantity (× axes in Components) × one sample per input sample',
      channels: [
        { name: 'velocity', desc: 'Speed (or velocity_x/y/z)', range: 'unit/s' },
        { name: 'acceleration', desc: 'Acceleration magnitude (or per axis)', range: 'unit/s²' },
        { name: 'jerk', desc: 'Jerk magnitude (or per axis)', range: 'unit/s³' },
        { name: 'curvature', desc: 'Curvature of the path', range: '1/unit' },
        { name: 'direction_x/y/z', desc: 'Unit direction of motion (always a vector)', range: '−1 – 1' },
        { name: 'smoothed', desc: 'Filtered position', range: 'unit' },
      ],
      notes: 'Only the quantities whose toggle is on are output. With none on, velocity is output.',
    },
    params: [
      { name: 'Outputdims', label: 'Output Dims', default: 'tangential', range: 'tangential · components', desc: 'Magnitudes or per-axis components.' },
      { name: 'Vel', label: 'Output Velocity', default: 'On', desc: '' },
      { name: 'Acc', label: 'Output Acceleration', default: 'On', desc: '' },
      { name: 'Jerk', label: 'Output Jerk', default: 'Off', desc: '' },
      { name: 'Curv', label: 'Output Curvature', default: 'Off', desc: '' },
      { name: 'Dir', label: 'Output Direction', default: 'Off', desc: '' },
      { name: 'Smooth', label: 'Output Smoothed Pos', default: 'Off', desc: '' },
      { name: 'Filterwindowlength', label: 'Filter Window Length (odd)', default: '15', range: '≥ 5', desc: 'Savitzky–Golay window in samples. Longer = smoother and more latency.' },
      { name: 'Filterpolyorder', label: 'Filter Polyorder', default: '3', range: '≥ 1', desc: 'Polynomial order (< window).' },
      { name: 'Movementthreshold', label: 'Movement Threshold', default: '0.005', desc: 'Below this speed the point is considered still (direction and curvature are not updated).' },
    ],
    statuses: [
      { status: 'OK', when: 'Samples processed.' },
      { status: 'INVALID_INPUT', when: 'Not 1–3 channels, NaN / infinity (sample skipped), or not a timeslice in Stream mode.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — wrist x,y,z', 'EW Kinematics', 'Select CHOP — velocity', 'Trail CHOP — 2 s', 'EW Spectral Arc Length']],
    recipe: [
      'Select one joint (x, y, z) and wire it into <b>EW L2 Kinematics</b>.',
      'Turn on the quantities you need. Leave Source = Stream for a live input.',
      'Use <code>velocity</code> directly for mapping, or trail it as the speed profile of the smoothness operators.',
    ],
    related: ['kinetic-energy', 'spectral-arc-length', 'log-dimensionless-jerk', 'submovement-count'],
  },
  {
    slug: 'kinetic-energy',
    title: 'Kinetic Energy',
    opType: 'Ewkineticenergy',
    label: 'EW L2 Kinetic Energy',
    layer: 'L2',
    kind: 'stream',
    tagline: 'Overall quantity of motion of the body: weighted sum of joint speeds squared.',
    about: `The total kinetic energy of a set of joints, ½ Σ mᵢ vᵢ². It is the simplest, most robust "how much is the body moving" signal: great for driving intensity, particle emission, sound level.

In <em>position</em> mode (default) the operator differentiates positions itself across cooks; in <em>velocity</em> mode it takes velocities.`,
    formula: 'E = ½ Σᵢ wᵢ · |vᵢ|²',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'N × Dims, joint-major', samples: 'live timeslice (Stream) or a recording (Clip)', example: ['j0x', 'j0y', 'j0z', 'j1x', '…'], desc: 'Position mode needs Dims = 3.' },
    ],
    output: {
      shape: '1 channel × one sample per input sample',
      channels: [{ name: 'kinetic_energy', desc: 'Total kinetic energy', range: '≥ 0' }],
    },
    params: [
      { name: 'Inputmode', label: 'Input Mode', default: 'position', range: 'position · velocity', desc: 'What the channels hold.' },
      { name: 'Dims', label: 'Dims', default: '3', range: '1 – 4', desc: 'Axes per joint.' },
      { name: 'Weight', label: 'Weight (mass)', default: '1', desc: 'Weight of every joint.' },
      { name: 'Weights', label: 'Weights per joint', default: '(empty)', desc: 'Space-separated list, one per joint in order (e.g. <code>1 2 0.5</code>). Missing ones use Weight.' },
      { name: 'Referencepoint', label: 'Reference Joint', default: '−1', desc: 'Position mode: measure motion relative to this joint (e.g. the pelvis) to ignore travelling. −1 = none.' },
    ],
    statuses: [
      { status: 'OK', when: 'Samples processed.' },
      { status: 'INVALID_INPUT', when: 'Position mode with Dims ≠ 3, reference joint invalid, NaN / infinity (sample skipped), not a timeslice in Stream mode.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — 33 joints', 'EW Kinetic Energy', 'Lag CHOP', 'Math CHOP — range', 'Null CHOP']],
    recipe: [
      'Select the joints (joint-major x, y, z) and wire into <b>EW L2 Kinetic Energy</b>.',
      'Smooth with a Lag CHOP and remap with a Math CHOP.',
      'Set Reference Joint to the pelvis to measure gesture energy only, not walking.',
    ],
    related: ['kinematics', 'points-density'],
  },
  {
    slug: 'log-dimensionless-jerk',
    title: 'Log Dimensionless Jerk',
    opType: 'Ewlogdimensionlessjerk',
    label: 'EW L2 Log Dimensionless Jerk',
    layer: 'L2',
    kind: 'frame',
    tagline: 'Smoothness of a speed profile from its jerk (LDLJ).',
    about: `A standard smoothness metric from motor control: integrates the squared jerk over the movement, normalises by duration and peak speed, and takes the negative logarithm. Values closer to 0 are smoother; more negative values are jerkier.`,
    formula: 'LDLJ = −ln( (T³ / v_peak²) ∫ |d²v/dt²|² dt )',
    inputs: [SPEED_IN],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'log_dimensionless_jerk', desc: 'Smoothness (higher = smoother)', range: '< 0' }],
    },
    params: [
      { name: 'Inputmode', label: 'Input Mode', default: 'velocity', range: 'velocity · acceleration', desc: 'What the profile holds.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than 10 samples.' },
      { status: 'INVALID_INPUT', when: 'No channel, or NaN / infinity.' },
    ],
    network: [['EW Kinematics — velocity', 'Trail CHOP — 1–2 s', 'EW Log Dimensionless Jerk', 'Null CHOP']],
    recipe: [
      'Get a speed profile from <b>EW L2 Kinematics</b> (velocity, tangential).',
      'Keep a window with a Trail CHOP matching one gesture (1–2 s).',
      'Wire into <b>EW L2 Log Dimensionless Jerk</b>.',
    ],
    notes: ['On a live MediaPipe pose the value moves around (e.g. between −12 and −16): tracking jitter adds jerk, and a sliding Trail cuts gestures at arbitrary points. Smooth the input and compare values over whole gestures rather than reading single values.'],
    related: ['spectral-arc-length', 'submovement-count', 'kinematics'],
  },
  {
    slug: 'points-density',
    title: 'Points Density',
    opType: 'Ewpointsdensity',
    label: 'EW L2 Points Density',
    layer: 'L2',
    kind: 'sample',
    tagline: 'Centroid of the body and how spread its joints are around it.',
    about: `Computes the centroid of a set of points and the dispersion of the points around it (mean, median, max or sum of the distances). Low density value = compact body; high = spread out. In Components mode the dispersion is given per axis.`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '3N, joint-major', samples: 'one point cloud per sample', example: ['j0x', 'j0y', 'j0z', '…'] },
    ],
    output: {
      shape: '4 (module) or 6 (components) channels × one sample per input sample',
      channels: [
        { name: 'centroid_x/y/z', desc: 'Centroid of the points', range: 'unit of the input' },
        { name: 'density', desc: 'Dispersion (module)', range: '≥ 0' },
        { name: 'density_x/y/z', desc: 'Dispersion per axis (components)', range: '≥ 0' },
      ],
    },
    params: [
      { name: 'Centroidtype', label: 'Centroid Type', default: 'mean', range: 'mean · median', desc: '' },
      { name: 'Distancetype', label: 'Distance Aggregator', default: 'mean', range: 'mean · median · max · sum', desc: 'How the distances to the centroid are aggregated.' },
      { name: 'Outputdims', label: 'Output Dims', default: 'module', range: 'module · components', desc: '' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'NaN / infinity, or not a timeslice in Stream mode.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — joints', 'EW Points Density', 'Select CHOP — density', 'Null CHOP']],
    recipe: ['Select joints joint-major and wire into <b>EW L2 Points Density</b>.', 'Use centroid as a stable body position, density as expansion.'],
    related: ['bounding-box-filled-area', 'ellipsoid-sphericity'],
  },
  {
    slug: 'spectral-arc-length',
    title: 'Spectral Arc Length',
    opType: 'Ewspectralarclength',
    label: 'EW L2 Spectral Arc Length',
    layer: 'L2',
    kind: 'frame',
    tagline: 'Smoothness from the shape of the speed spectrum (SPARC).',
    about: `SPARC measures the arc length of the normalised amplitude spectrum of a speed profile: a smooth movement has a compact, simple spectrum (short arc, value near 0); a jerky one has a long, ragged spectrum (more negative). More robust to noise than jerk-based metrics.`,
    inputs: [SPEED_IN],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'spectral_arc_length', desc: 'Smoothness (closer to 0 = smoother)', range: '< 0, typically −1 … −4' }],
    },
    params: [
      { name: 'Amplitudethreshold', label: 'Amplitude Threshold', default: '0.05', range: '0 – 1', desc: 'Spectrum below this normalised amplitude is cut off (adaptive cutoff).' },
      { name: 'Minimumcutofffrequency', label: 'Minimum Cutoff Frequency (Hz)', default: '2', desc: 'Lowest cutoff of the spectrum.' },
      { name: 'Maximumcutofffrequency', label: 'Maximum Cutoff Frequency (Hz)', default: '20', desc: 'Highest cutoff. Keep below half the sample rate.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than 10 samples.' },
      { status: 'INVALID_INPUT', when: 'NaN / infinity, or a profile that cannot support a result (all zeros).' },
    ],
    network: [['EW Kinematics — velocity', 'Trail CHOP — 1–2 s', 'EW Spectral Arc Length', 'Null CHOP']],
    recipe: ['Trail the <code>velocity</code> of Kinematics over one gesture.', 'Wire into <b>EW L2 Spectral Arc Length</b>.'],
    notes: ['On a live MediaPipe pose the value moves around (e.g. between −1 and −4), for the same reasons as <a href="log-dimensionless-jerk">Log Dimensionless Jerk</a>: smooth the input and compare whole gestures.'],
    related: ['log-dimensionless-jerk', 'submovement-count', 'kinematics'],
  },
  {
    slug: 'submovement-count',
    title: 'Submovement Count',
    opType: 'Ewsubmovementcount',
    label: 'EW L2 Submovement Count',
    layer: 'L2',
    kind: 'frame',
    tagline: 'How many separate "pushes" a movement is made of.',
    about: `Counts the prominent peaks of a speed profile. A single smooth reach has one peak; a hesitant or corrected movement has several. A peak counts when its prominence exceeds Prominence Factor × the maximum speed.`,
    inputs: [SPEED_IN],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'submovement_count', desc: 'Number of speed peaks', range: 'integer ≥ 0' }],
    },
    params: [
      { name: 'Prominencefactor', label: 'Prominence Factor', default: '0.1', range: '0 – 0.5', desc: 'Minimum peak prominence as a fraction of the peak speed.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'WARMING_UP', when: 'Fewer than 10 samples.' },
      { status: 'INVALID_INPUT', when: 'NaN / infinity.' },
    ],
    network: [['EW Kinematics — velocity', 'Trail CHOP — 2 s', 'EW Submovement Count', 'Null CHOP']],
    recipe: ['Trail the Kinematics velocity over a few seconds.', 'Wire into <b>EW L2 Submovement Count</b>.'],
    related: ['spectral-arc-length', 'log-dimensionless-jerk', 'scalar-peak-detector'],
  },
  {
    slug: 'symmetry',
    title: 'Symmetry',
    opType: 'Ewsymmetry',
    label: 'EW L2 Symmetry',
    layer: 'L2',
    kind: 'sample',
    tagline: 'Left–right mirror symmetry of joint pairs.',
    about: `<b>Reflection</b> (default): for each pair of joints (e.g. left and right wrist) reflects one across the body's centre and measures how close it lands to the other: one score per pair, 1 = perfectly symmetric.

<b>Ratio</b>: the EyesWeb symmetry index of named couples relative to a reference joint, aggregated into one value (or one per axis).`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'N × Dims, joint-major', samples: 'one pose per sample', example: ['j0x', 'j0y', 'j0z', '…'] },
    ],
    output: {
      shape: 'reflection: one channel per pair · ratio: 1 or 3 channels — one sample per input sample',
      channels: [
        { name: 'pair_symmetry_<a>_<b>', desc: 'Score of the pair (reflection)', range: '0 – 1' },
        { name: 'symmetry', desc: 'Aggregated index (ratio)', range: '0 – 1' },
        { name: 'symmetry_x/y/z', desc: 'Per axis (ratio, Components on)', range: '0 – 1' },
      ],
    },
    params: [
      { name: 'Method', label: 'Method', default: 'reflection', range: 'reflection · ratio', desc: '' },
      { name: 'Pairs', label: 'Joint Pairs', default: '0,1', desc: 'Space-separated pairs of joint indices, e.g. <code>15,16 13,14</code>.' },
      { name: 'Referencepoint', label: 'Reference Point', default: '−1', desc: 'Joint used as centre (−1 = barycenter). Required (≥ 0) in ratio.' },
      { name: 'Dims', label: 'Dims', default: '3', desc: 'Axes per joint. Ratio needs 3.' },
      { name: 'Aggregation', label: 'Aggregation (ratio)', default: 'mean', range: 'mean · min · max · weighted_mean', desc: '' },
      { name: 'Indextype', label: 'Index Type (ratio)', default: 'symmetry', range: 'symmetry · symmetry_asymmetry', desc: '' },
      { name: 'Components', label: 'One Value per Axis (ratio)', default: 'Off', desc: '' },
      { name: 'Normalizeskeleton', label: 'Normalize Skeleton (ratio)', default: 'On', desc: '' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'NaN / infinity; ratio with Dims ≠ 3, missing reference, or a pair outside the joints.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — 33 joints', 'EW Symmetry — Pairs 15,16 13,14', 'Null CHOP']],
    recipe: [
      'Select joints joint-major. Note the index of each joint (MediaPipe: 15/16 wrists, 13/14 elbows, 11/12 shoulders).',
      'Wire into <b>EW L2 Symmetry</b> and type the pairs, e.g. <code>15,16 13,14</code>.',
    ],
    related: ['triangle-symmetry'],
  },
  {
    slug: 'trajectory-non-planarity',
    title: 'Trajectory Non-Planarity',
    opType: 'Ewtrajectorynonplanarity',
    label: 'EW L2 Trajectory Non-Planarity',
    layer: 'L2',
    kind: 'frame',
    tagline: 'Does a 3D gesture stay on a plane, or twist out of it?',
    about: `Fits local planes over neighbourhoods of size Radius along a 3D path and averages the distance of the points from them. A circle or a swing stays in a plane (0); a spiral or a twisting gesture leaves it (larger value, in the unit of the data).`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '3 (x, y, z)', samples: 'a window of ≥ 2 positions', example: ['x', 'y', 'z'] },
    ],
    output: {
      shape: '1 channel × 1 sample',
      channels: [{ name: 'curvature_radius', desc: 'Mean distance from the local planes', range: '≥ 0, unit of the input' }],
    },
    params: [
      { name: 'Radius', label: 'Search Radius', default: '0.1', desc: 'Size of the neighbourhoods, in the unit of the data. Choose it of the size of the movement.' },
      { name: 'Nanfraction', label: 'NaN Fraction', default: '0.5', range: '0 – 1', desc: 'Largest share of undefined local planes before the result is invalid.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'Fewer than 3 channels or 2 points, NaN / infinity, no neighbour within Radius, too many undefined planes.' },
    ],
    network: [['Mocap CHOP — wrist x,y,z', 'Trail CHOP — 2 s', 'EW Trajectory Non-Planarity', 'Null CHOP']],
    recipe: ['Trail a 3D joint over 1–2 s.', 'Wire into <b>EW L2 Trajectory Non-Planarity</b>; set Radius to a fraction of the gesture size.'],
    notes: ['Needs real 3D data (world coordinates), not 2D image coordinates.'],
    related: ['directness', 'direction-change'],
  },
  {
    slug: 'triangle-symmetry',
    title: 'Triangle Symmetry',
    opType: 'Ewtrianglesymmetry',
    label: 'EW L2 Triangle Symmetry',
    layer: 'L2',
    kind: 'sample',
    tagline: 'Asymmetry of the triangle head – left hand – right hand.',
    about: `Three 2D points form a triangle (typically head on top, hands at the sides). <b>Area</b> (EyesWeb) returns a symmetry index (1 = symmetric). <b>Horizontal / Vertical / Spatial</b> are the asymmetry indices of Glowinski et al. 2011 (0 = symmetric).`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '6: ux, uy, lx, ly, rx, ry', samples: 'one triangle per sample', example: ['ux', 'uy', 'lx', 'ly', 'rx', 'ry'] },
    ],
    output: {
      shape: '1 channel × one sample per input sample',
      channels: [
        { name: 'symmetry', desc: 'Area method', range: '0 – 1, 1 = symmetric' },
        { name: 'horizontal_asymmetry / vertical_asymmetry / spatial_asymmetry', desc: 'Glowinski methods', range: '≥ 0, 0 = symmetric' },
      ],
    },
    params: [
      { name: 'Method', label: 'Method', default: 'area', range: 'area · horizontal · vertical · spatial', desc: 'Renames the output channel.' },
    ],
    statuses: [
      { status: 'OK', when: 'Computed.' },
      { status: 'INVALID_INPUT', when: 'Fewer than 6 channels, collinear vertices (area), undefined Glowinski index, NaN / infinity.' },
    ],
    network: [['MediaPipe COMP', 'Select CHOP — nose, wrists x,y', 'EW Triangle Symmetry', 'Null CHOP']],
    recipe: ['Select head (nose), left wrist and right wrist x, y — in that order.', 'Wire into <b>EW L2 Triangle Symmetry</b>.'],
    related: ['symmetry'],
  },
];
