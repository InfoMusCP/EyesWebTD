# Changelog

Version numbers follow `VERSION` (MAJOR.MINOR.PATCH). TouchDesigner compares MAJOR and MINOR of the operators saved in a
.toe with the installed ones: a MAJOR change breaks saved projects (renamed parameters or channels), MINOR adds operators or
parameters.

## 0.1.0 (unreleased)

First release of the layered operator set: 30 operators, one per feature of the first PyEyesWeb release that makes sense in
TouchDesigner (29) and `TimeWindowSynchronizer`, in five layers (physical signals, low-level, mid-level, high-level, analysis primitives).

- Operators are named after the PyEyesWeb features and carry the layer in the label (`EW L2 Kinetic Energy`); channel names
  follow PyEyesWeb.
- Parameter names are the PyEyesWeb public names without underscores (`Maxlag`, `Filterwindowlength`), menu entries the
  PyEyesWeb choices.
- Stream operators have `Source` (stream / clip) and `Reset`; buffer operators have `Reset`; parameters are applied live.
- Every operator has an Info CHOP / DAT with status, reason and sample counts.
- Gesture Segmenter gives the duration of each gesture and pause (Motion Duration merged in) and has no noise input.
- Parameter names are a capital followed by lowercase letters and digits (the TouchDesigner rule); checked by the package tests.
- Each DLL carries the package version (file properties and the operator's major / minor version).

### Design review (2026-11-17)

- One window model: a window operator analyses the input it is given (the whole input CHOP is the window: a Trail CHOP live,
  a File In for a recording) and keeps nothing between cooks; a stream operator takes the live signal and keeps its state.
  Binary Pulses Regularity, Event Synchronization and Event Synchronization MECS follow it now: Binary Pulses Regularity has
  no Window, Hop or Reset (only Threshold), Event Synchronization has no Reset Every Buffer or Reset, MECS has no Reset and
  carries no events over from a previous window, Periodicity has no Window, Hop or Reset (the algorithm is unchanged; the
  small2large output has window/2 + 1 samples, with window the length of the input). A window operator fed fewer samples than it needs says
  WARMING_UP with the reason "feed a window (a Trail CHOP, a File In)".
- The sample-wise operators (Bounding Box Filled Area, Ellipsoid Sphericity, Equilibrium, Points Density, Symmetry, Triangle Symmetry)
  output one sample in Stream, the newest, like Hit Cell Detector and Rarity.
- Analysis tags: pose, space, contraction, trajectory, energy, smoothness, complexity, rhythm, coordination.

- Six operators that stay in PyEyesWeb have no TouchDesigner operator (chops/_held_back): Videogram, Contour Curvature, Body Parts From
  Curvature (a contour has no practical source in TouchDesigner), Recurrence Plot, Cross Recurrence Plot and Partial Recurrence
  Synchronization (N x N matrices that can only become an image).
- Thresholding is left to the user: Silhouette Centroids and Silhouette Body Parts have no `Threshold`; the TOP is the `Top`
  parameter (they have no input). Silhouette Centroids outputs pixel coordinates only (normalise after the operator).
- Hit Cell Detector and Rarity: the stream output is always one sample, the newest (a live source gives 1 or 2 samples in a frame).
- Binary Pulses Regularity: no `is_regularity_detected` (the rising edge of `is_regular`).
- Sample Entropy: one value, SampEn(m, r), `Embedding Dimension` is the template length m (default 2).
- Rarity is the novelty of patterns (Memory and Pattern in seconds, Neighbours, Compare values / shape), for any signal; the two EyesWeb
  methods stay in PyEyesWeb.
