import type { Operator } from './types';

export const l1: Operator[] = [
  {
    slug: 'hit-cell-detector',
    title: 'Hit Cell Detector',
    opType: 'Ewhitcelldetector',
    label: 'EW L1 Hit Cell Detector',
    layer: 'L1',
    kind: 'sample',
    state: 'verified',
    sourceDesc: 'Stream: a live source. The output is always <b>one sample</b>: the cell of the newest point (a source can give 1 or 2 points in a frame, only the newest counts). Clip: a recording, one cell for every point.',
    tagline: 'Which cell of a 2D grid each point falls in.',
    about: `Divides a rectangular area into a uniform grid of <code>Cells Along X × Cells Along Y</code> cells and tells, for every point, the row and column of the cell it hits.

Use it to turn a hand, a centroid or a blob position into a discrete zone: trigger samples per cell, build a step sequencer on the floor, count visits per zone.`,
    formula: 'col = ⌊(x − Xmin) / (Xmax − Xmin) · CellsX⌋ · row = ⌊(y − Ymin) / (Ymax − Ymin) · CellsY⌋',
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: '2 (x, y)', samples: 'one point per sample: a live source (1 or 2 points per frame) or a clip', example: ['x', 'y'], desc: 'Extra channels are ignored. Coordinates in the same unit as Xmin…Ymax (0–1 for normalised MediaPipe).' },
    ],
    output: {
      shape: '2 channels × 1 sample (Stream) · one sample per point (Clip)',
      channels: [
        { name: 'cell_row', desc: 'Row of the hit cell (y axis)', range: '0 … Cells Along Y − 1, −1 = none' },
        { name: 'cell_col', desc: 'Column of the hit cell (x axis)', range: '0 … Cells Along X − 1, −1 = none' },
      ],
      notes: 'In <b>Stream</b> (default) the output is always one sample, the cell of the <b>newest</b> point: when the source gives two points in a frame, only the newest counts, so an expression like <code>op("hit")["cell_col"]</code> always reads the current cell and the viewer never flips between a value and a series. In <b>Clip</b> every point of the recording gets its cell.<br><br>With Clip Values off, a point outside the area makes the cook INVALID_INPUT and the outputs −1 (Stream: only the newest point is checked; Clip: the whole recording).',
    },
    params: [
      { name: 'Cellsalongx', label: 'Cells Along X', default: '10', range: '≥ 1', desc: 'Number of columns.' },
      { name: 'Cellsalongy', label: 'Cells Along Y', default: '10', range: '≥ 1', desc: 'Number of rows.' },
      { name: 'Xmin', label: 'X Min', default: '0', desc: 'Left edge of the area.' },
      { name: 'Xmax', label: 'X Max', default: '1', desc: 'Right edge of the area.' },
      { name: 'Ymin', label: 'Y Min', default: '0', desc: 'Start of the area along y (row 0).' },
      { name: 'Ymax', label: 'Y Max', default: '1', desc: 'End of the area along y (the upper edge belongs to the last row).' },
      { name: 'Clipvalues', label: 'Clip Values', default: 'On', desc: 'Clamp points outside the area to the border cells. Off: an outside point invalidates the cook.' },
    ],
    statuses: [
      { status: 'OK', when: 'Every point was assigned a cell.' },
      { status: 'INVALID_INPUT', when: 'Fewer than 2 channels, NaN / infinity, or a point outside the area with Clip Values off.' },
    ],
    network: [['MediaPipe COMP — pose', 'Select CHOP — wrist x, y', 'EW Hit Cell Detector', 'Null CHOP'], ['EW Hit Cell Detector', 'Math CHOP — row·cols+col', 'Logic CHOP — on change']],
    recipe: [
      'Select the x and y of one landmark (e.g. right wrist) with a Select CHOP: two channels, x first.',
      'Wire it to <b>EW L1 Hit Cell Detector</b>. Leave Source on <em>Stream</em> for a live input: the output is one sample, the cell of the newest point.',
      'Set Cells Along X / Y to your grid (e.g. 4 × 4) and the area to the range of your coordinates.',
      'Combine the output into one index with a Math CHOP (<code>row * cols + col</code>) to drive a Switch or a sample trigger.',
    ],
    checks: [
      'Move the point to the four corners: row and col reach 0 and N − 1.',
      'Is y = 0 at the top or the bottom in your source? Check that row 0 is where you expect it.',
      'Turn Clip Values off and leave the area: status becomes INVALID_INPUT and both outputs go to −1.',
    ],
    related: ['silhouette-centroids', 'points-density'],
  },
  {
    slug: 'silhouette-body-parts',
    title: 'Silhouette Body Parts',
    opType: 'Ewsilhouettebodyparts',
    label: 'EW L1 Silhouette Body Parts',
    layer: 'L1',
    kind: 'frame',
    state: 'verified',
    tagline: 'Bounding boxes of head, trunk, arms and legs from a silhouette mask.',
    about: `Splits a human silhouette into six regions (left leg, right leg, trunk, left arm, right arm, head) from its horizontal and vertical projection histograms, and returns the bounding box of each region in pixels.

It works on a <b>binary mask</b>, not on a colour video: key the body first (background subtraction, a depth threshold, a segmentation model) and feed the mask. "Left" is the smaller x of the image, not the performer's left.`,
    inputs: [
      { port: 'TOP', family: 'TOP', channels: '1 (mask, red channel)', samples: 'one frame per cook', example: ['mask'], desc: 'Not wired: name the TOP in the <code>Top</code> parameter. A <b>binary mask</b>: any non-zero pixel is body. Threshold it before the operator (a Threshold TOP): the operator has no threshold of its own. A colour TOP is read through its red channel.' },
    ],
    output: {
      shape: '30 channels × 1 sample',
      channels: [
        { name: 'regions_<part>_x', desc: 'Left edge of the part bounding box', range: 'pixels, 0 = left' },
        { name: 'regions_<part>_y', desc: 'Top edge of the part bounding box', range: 'pixels, 0 = top' },
        { name: 'regions_<part>_width', desc: 'Width of the box', range: 'pixels' },
        { name: 'regions_<part>_height', desc: 'Height of the box', range: 'pixels' },
        { name: 'is_found_<part>', desc: '1 when the part was found', range: '0 / 1' },
      ],
      notes: '<code>&lt;part&gt;</code> = left_leg, right_leg, trunk, left_arm, right_arm, head (in this order). A part not found has a box of 0.<br><br><b>y points down.</b> Coordinates follow the image convention of EyesWeb and PyEyesWeb: (0, 0) is the <b>top-left</b> pixel and y grows downward. TouchDesigner draws with y up (0 at the bottom), so flip y before overlaying on a TOP: <code>y_td = height − 1 − y</code>, where height is the height of the mask TOP, not of the video if you resized it. For a box: bottom edge in TD = <code>height − y − height_of_box</code>, top edge = <code>height − y</code>.',
    },
    params: [
      { name: 'Top', label: 'TOP', default: '—', desc: 'The mask TOP (path or drag the TOP onto the field). Required: the operator has no TOP input.' },
      { name: 'Armpercentage', label: 'Arm Percentage', default: '0.8', range: '0 – 1', desc: 'Projection-histogram heuristic of the arms (EyesWeb BlobSubRegions). Tune while watching <code>is_found_*_arm</code>.' },
      { name: 'Legssearch', label: 'Legs Search', default: '0.5', range: '0 – 1', desc: 'Fraction of the silhouette where the legs are searched (heuristic).' },
      { name: 'Legsoffset', label: 'Legs Offset', default: '0.2', range: '0 – 1', desc: 'Offset of the legs search region (heuristic).' },
      { name: 'Armsminthreshold', label: 'Arms Min Threshold', default: '0.2', range: '0 – 1', desc: 'Lower histogram threshold for the arms (heuristic).' },
      { name: 'Armsmaxthreshold', label: 'Arms Max Threshold', default: '0.5', range: '0 – 1', desc: 'Upper histogram threshold for the arms (heuristic).' },
      { name: 'Leftleg … Head', label: 'Parts page', default: 'all On', desc: 'One toggle per part: switch off what you do not need.' },
    ],
    statuses: [
      { status: 'OK', when: 'The mask had foreground pixels (some parts may still be not found).' },
      { status: 'INVALID_INPUT', when: 'No TOP, a TOP that cannot be read, or a mask without foreground pixels.' },
    ],
    network: [['Video Device In TOP', 'Nvidia Background TOP', 'Threshold TOP — mask'], ['EW Silhouette Body Parts — Top = mask', 'Select CHOP — regions_head_*', 'Rectangle SOP / Render']],
    recipe: [
      'Produce a clean body mask: white body on black (Nvidia Background, a Chroma Key, a depth threshold…), then a <b>Threshold TOP</b> so that it is strictly black and white.',
      'Lower the resolution (e.g. 640 × 360): every cook downloads the texture from the GPU.',
      'Add <b>EW L1 Silhouette Body Parts</b> and set its <code>Top</code> parameter to the mask TOP (drag the TOP onto the field).',
      'Select <code>regions_head_*</code> to draw a box on the head, or use <code>is_found_*</code> as gates.',
      '<b>Flip y for TouchDesigner</b>: Select CHOP <code>regions_*_y</code> → Math CHOP, <em>Range</em> page: From Range <code>0</code> … <code>op("mask").height - 1</code>, To Range <code>op("mask").height - 1</code> … <code>0</code>. Merge it back with the x channels. Subtract each box height after the flip to get its bottom edge.',
    ],
    checks: [
      'Stand in T-pose: all six <code>is_found</code> should be 1.',
      'Swap sides: is <code>left_arm</code> the arm on the left of the image?',
      'Feed an empty (black) mask: INVALID_INPUT and all zeros.',
      'Measure the cook time at full HD vs a reduced resolution.',
    ],
    notes: ['Silhouette operators need a real mask TOP, not a colour video.', 'The GPU readback costs ~20 ms at 1920×1088: downscale the mask.'],
    related: ['silhouette-centroids'],
  },
  {
    slug: 'silhouette-centroids',
    title: 'Silhouette Centroids',
    opType: 'Ewsilhouettecentroids',
    label: 'EW L1 Silhouette Centroids',
    layer: 'L1',
    kind: 'buffer',
    state: 'verified',
    tagline: 'Centre of gravity, head, hands, elbows, knees and feet of a silhouette — no skeleton tracker needed.',
    about: `Finds up to 14 hierarchical centroids of a human silhouette (centre of gravity, head, shoulders, elbows, forearms, hands, knees, feet) from a binary mask, in pixels. To get coordinates in 0–1, divide by the width and height of the mask after the operator.

A light alternative to a pose tracker when you already have a mask (a Kinect body index, a background subtraction). An optional alpha filter smooths each centroid over time.`,
    inputs: [
      { port: 'TOP', family: 'TOP', channels: '1 (mask, red channel)', samples: 'one frame per cook', example: ['mask'], desc: 'Not wired: named in the <code>Top</code> parameter. A <b>binary mask</b>: any non-zero pixel is body. Threshold it before the operator (a Threshold TOP): the operator has no threshold of its own.' },
    ],
    output: {
      shape: '28 channels × 1 sample',
      channels: [
        { name: 'centroids_<label>_x / _y', desc: 'Pixel coordinates of the centroid', range: 'pixels, y = 0 at top' },
      ],
      notes: '<code>&lt;label&gt;</code> = center_of_gravity, head, left_shoulder, left_elbow, left_forearm, left_hand, right_shoulder, right_elbow, right_forearm, right_hand, left_knee, left_foot, right_knee, right_foot. A centroid not requested or not found is <b>NaN</b>.<br><br><b>y points down.</b> Coordinates follow the image convention of EyesWeb and PyEyesWeb: (0, 0) is the <b>top-left</b> pixel and y grows downward. TouchDesigner draws with y up (0 at the bottom), so flip y before overlaying on a TOP: <code>y_td = height − 1 − y</code>, where height is the height of the mask TOP, not of the video if you resized it.',
    },
    params: [
      { name: 'Top', label: 'TOP', default: '—', desc: 'The mask TOP (path or drag the TOP onto the field). Required: the operator has no TOP input.' },
      { name: 'Silhouette', label: 'Silhouette', default: 'full', range: 'full · upper · lower · left · right', desc: 'Which part of the body the mask shows. Changing it restarts the filter.' },
      { name: 'Filtercentroids', label: 'Filter Centroids', default: 'Off', desc: 'Exponential smoothing of each centroid across cooks.' },
      { name: 'Alpha', label: 'Alpha', default: '0.75', range: '0 – 1', desc: 'Weight of the smoothing filter.' },
      { name: 'Addintermediatecentroids', label: 'Add Intermediate Centroids', default: 'Off', desc: 'Also compute the centroids between the main ones.' },
      { name: 'Centerofgravity … Rightfoot', label: 'Parts page', default: 'all On', desc: 'One toggle per centroid.' },
    ],
    statuses: [
      { status: 'OK', when: 'The mask had foreground.' },
      { status: 'INVALID_INPUT', when: 'No TOP, unreadable TOP, or an empty mask (outputs stay 0).' },
    ],
    network: [['Video Device In TOP', 'Nvidia Background TOP', 'Level TOP — mask'], ['EW Silhouette Centroids — Top = mask', 'Select CHOP — centroids_*_hand_*', 'Math CHOP — ÷ width, height', 'Lag CHOP'], ['EW Silhouette Centroids', 'EW Kinematics']],
    recipe: [
      'Build a mask TOP (white body on black) at a moderate resolution.',
      'Add <b>EW L1 Silhouette Centroids</b> and set its <code>Top</code> parameter to the mask TOP.',
      'Select the <code>centroids_*</code> channels you need and replace NaN (e.g. with a Math CHOP or by holding the last value) before using them downstream.',
      '<b>Normalise if you need 0–1</b>: Select the x channels and multiply by <code>1 / op("mask").width</code> with a Math CHOP (Gain); the same for the y channels with the height.',
      '<b>Flip y for TouchDesigner</b>: Select CHOP <code>centroids_*_y</code> → Math CHOP, <em>Range</em> page: From Range <code>0</code> … <code>op("mask").height - 1</code>, To Range <code>op("mask").height - 1</code> … <code>0</code>. Merge it back with the x channels.',
      'Feed <code>centroids_center_of_gravity_*</code> (pixels, or normalised as above) to Kinematics or Kinetic Energy for a mask-only movement pipeline.',
    ],
    checks: [
      'Compare <code>centroids_head</code> with where the head is in the image.',
      'Raise one arm: does the right hand centroid follow the arm on the right of the image?',
      'Toggle Filter Centroids: movement should become smoother and lag a little; Reset clears the filter.',
      'Switch off a part: its channels become NaN.',
    ],
    related: ['silhouette-body-parts', 'kinematics'],
  },
  {
    slug: 'time-window-synchronizer',
    title: 'Time Window Synchronizer',
    opType: 'Ewtimewindowsynchronizer',
    label: 'EW L1 Time Window Synchronizer',
    layer: 'L1',
    kind: 'buffer',
    state: 'to-check',
    tagline: 'Re-cuts one or two streams at different rates into aligned windows of the same duration.',
    about: `Two sensors rarely agree: an IMU at 100 Hz, a pose tracker at 30 Hz, chunks of irregular size. This operator appends every chunk to its stream and cuts both streams into windows <code>[t, t + Window)</code> on a common clock, so that window <em>k</em> of input 0 and window <em>k</em> of input 1 cover the same time span.

Each cook outputs the newest complete window. Use it before any operator that compares two signals (Phase Locking Value, Event Synchronization).`,
    inputs: [
      { port: 'Input 0', family: 'CHOP', channels: 'any', samples: 'new samples of stream A (a timeslice)', example: ['a1', 'a2'] },
      { port: 'Input 1', family: 'CHOP', channels: 'any', samples: 'new samples of stream B at its own rate', example: ['b1'], optional: true },
    ],
    output: {
      shape: 'C0 + C1 channels × max(rate · Window) samples',
      channels: [
        { name: 'in0_<name>', desc: 'The channels of input 0 in the window', range: 'as input' },
        { name: 'in1_<name>', desc: 'The channels of input 1 in the window', range: 'as input' },
      ],
      notes: 'The output rate is the one of input 0. A stream with fewer samples per window is padded with zeros at the end. When one cook completes several windows only the newest is output (Info: <code>windows_popped</code>).',
    },
    params: [
      { name: 'Window', label: 'Window (seconds)', default: '0.04', range: '≥ 0.0001', desc: 'Duration of a window. Structural: changing it restarts the buffers.' },
      { name: 'Starttime', label: 'Start Time (seconds)', default: '0', desc: 'Start of the first window.' },
    ],
    statuses: [
      { status: 'OK', when: 'At least one window was completed.' },
      { status: 'NO_OUTPUT', when: 'No complete window yet (output 0).' },
      { status: 'INVALID_INPUT', when: 'Input 0 not connected, or a window holds no sample at the rate of an input.' },
    ],
    network: [['OSC In CHOP — IMU 100 Hz', 'EW Time Window Synchronizer', 'Select CHOP — in0_*, in1_*', 'EW Phase Locking Value'], ['MediaPipe COMP — 30 Hz', 'EW Time Window Synchronizer']],
    recipe: [
      'Wire stream A to input 0 and stream B to input 1. Each must carry its real sample rate.',
      'Choose a Window long enough to hold at least one sample of the slowest stream (e.g. 1 s).',
      'Read the Info CHOP: <code>windows_popped</code> > 1 means windows are being dropped — enlarge Window.',
    ],
    checks: [
      'Feed two Pattern CHOPs at different sample rates and verify both appear in the window.',
      'Check that NO_OUTPUT appears before the first window is complete.',
      'Change Window and confirm the buffers restart.',
    ],
    notes: ['Presentation timestamps of the chunks are not used: a CHOP has no per-chunk time.'],
    related: ['phase-locking-value', 'event-synchronization'],
  },
  ];
