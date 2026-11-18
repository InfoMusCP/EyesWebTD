# EyesWebTD: TouchDesigner C++ CHOP Plugins

Native C++ Custom Channel Operator (CHOP) plugins for TouchDesigner, wrapping the feature blocks of EyesWebCore.
The operators are grouped by the layers of the conceptual model that PyEyesWeb follows (`PyEyesWeb/docs/theory/framework.md`),
not by the EyesWeb block library.

## Layout

```
chops/<layer>/      one .cpp per operator (one DLL per operator: TouchDesigner loads one operator per DLL)
common/             code shared by the operators: plugin_info.h (author name and email) and ew_td/ (the base layer, see below)
tests/              base layer (ctest -C Release), mock host (host/), package checks (package/), parity with PyEyesWeb (parity/)
cmake/              templates of the generated version header, DLL version resource and package info
palette/            script that builds the EyesWeb palette in TouchDesigner (see palette/README.md)
third_party/        TouchDesigner plugin headers (unmodified, Derivative licence)
DEVELOPMENT_PLAN.md assessment and plan
```

Layers: `physical_signals`, `low_level`, `mid_level`, `high_level`, `analysis_primitives`. The built DLLs are collected in
`Plugins/EyesWeb/<layer>/` of the build tree.

## Writing an operator

An operator derives from `ew_td::EwChop` and declares its outputs, its parameters and its computation; the base class
does the TouchDesigner contract (channel names from the schema, zeroed outputs, exceptions turned into a status and a
warning). See `chops/low_level/DirectnessCHOP.cpp` (a window to one value) and `MotionNoiseDetectorCHOP.cpp` (a
stream with parameters):

```cpp
#include "ew_td/plugin.h"
class MyCHOP : public ew_td::EwChop {
public:
    explicit MyCHOP(const TD::OP_NodeInfo*) {}
    ew_td::Schema schema(const TD::OP_Inputs*) const override { return {ew_td::Output::scalar("my_feature")}; }
    void declareParameters(ew_td::Params& p) override { p.integer("Window", "Window", 50, ew_td::Range::atLeast(2, 200)); }
    void cook(TD::CHOP_Output* out, const TD::OP_Inputs* in) override {
        const ew_td::InputView input = ew_td::chopInput(in);
        ew_td::require(input.samples() >= 2, "needs at least 2 samples");   // becomes INVALID_INPUT and a warning
        out->channels[0][0] = 0.f;
    }
};
EW_TD_CHOP(MyCHOP, "Ewmyfeature", "EW L2 My Feature", 1, 1)
```

An operator that keeps state between cooks (a feature fed sample after sample) derives from `ew_td::EwStreamChop`
instead, implements `process` and `dropState`, and holds its core feature in an `ew_td::FeatureSlot`. It gets two
parameters on a `Cook` page: **Source** (`stream`: a live timeslice, the state stays and the output is a timeslice;
`clip`: a recording, the state starts afresh at every cook) and **Reset** (pulse). See `KinematicsCHOP.cpp`.
Every operator has an Info CHOP / DAT with its status, the reason, the shape of the output and, for a stream
operator, the samples processed and the resets.

An operator whose core object keeps state across cooks while the output is not one sample per input sample (a buffer of
events, a window, a grid of cells) derives from `ew_td::EwBufferChop` and gets the **Reset** pulse. An operator that
keeps nothing derives from `ew_td::EwChop`. `Params` covers numeric parameters (`Range` with limits, clamping and a
separate slider range), toggles, pulses, menus and strings.

Parameter names are the public names of PyEyesWeb without underscores, first letter capital as TouchDesigner requires
(`max_lag` is `Maxlag`, `filter_window_length` is `Filterwindowlength`), and menu entries are the PyEyesWeb choices.
Parameters that exist only in TouchDesigner (the layout of the input channels, the binarisation threshold of a TOP)
keep names of their own.

Output names follow the PyEyesWeb ones (`feature.outputs.flat_names`) where the feature has fixed outputs; where its
size depends on the data (matrices, lists of cells) the operators keep the channel-per-row layout they always had.

## Parameters of PyEyesWeb that the operators do not expose (first release)

The operators take the parameters of their PyEyesWeb feature. Two are left out, and the operator does the default of
PyEyesWeb:

- Kinematics: `input_mode` (the operator takes a point trajectory, not a whole time series) and `output_type` (one toggle
  for each output instead, with the same names);
- Rarity: `number_of_inputs` is not a parameter: it is the number of input channels. Memory and Pattern are in seconds (PyEyesWeb: samples).

Exposed since the review of the library: Symmetry's ratio method (`Method`, `Indextype`, `Components`, `Aggregation`,
`Normalizeskeleton`), DirectionChange's metrics (the `Cosine` and `Polygon` toggles).

## Catalog of Operators (30 CHOPs)

The operators of the first release: 29 features of the PyEyesWeb catalog and `TimeWindowSynchronizer`. The
operators of the features held back from the release are kept in `chops/_held_back` and are not built. So are six operators
that stay in PyEyesWeb but have no use as TouchDesigner nodes: Videogram, Contour Curvature and Body Parts From Curvature
(a contour has no practical source in TouchDesigner), Recurrence Plot, Cross Recurrence Plot and Partial Recurrence
Synchronization (N x N matrices that can only become an image).

### 1. Physical signals (layer 1)
| CHOP File | Operator Type | Op Label | Description |
|---|---|---|---|
| `HitCellDetectorCHOP.cpp` | `Ewhitcelldetector` | EW L1 Hit Cell Detector | Uniform 2D grid cell quantizer for points |
| `SilhouetteBodyPartsCHOP.cpp` | `Ewsilhouettebodyparts` | EW L1 Silhouette Body Parts | Bounding regions of head, torso, arms and legs of a silhouette mask (TOP input) |
| `SilhouetteCentroidsCHOP.cpp` | `Ewsilhouettecentroids` | EW L1 Silhouette Centroids | Centroids of the body parts of a silhouette mask in pixels, with optional filtering (the TOP is the `Top` parameter) |
| `TimeWindowSynchronizerCHOP.cpp` | `Ewtimewindowsynchronizer` | EW L1 Time Window Synchronizer | Re-cuts one or two sampled streams into fixed time windows aligned on a common clock |

### 2. Low-level features (layer 2)
| CHOP File | Operator Type | Op Label | Description |
|---|---|---|---|
| `BoundingBoxFilledAreaCHOP.cpp` | `Ewboundingboxfilledarea` | EW L2 Bounding Box Filled Area | Ratio of the 3D convex hull area to the bounding box area (contraction index) |
| `CurvatureVelocityCorrelationCHOP.cpp` | `Ewcurvaturevelocitycorrelation` | EW L2 Curvature Velocity Correlation | Savitzky-Golay curvature-velocity (power law) smoothness index |
| `DirectionChangeCHOP.cpp` | `Ewdirectionchange` | EW L2 Direction Change | Trajectory cosine sharp change and polygon area |
| `DirectnessCHOP.cpp` | `Ewdirectness` | EW L2 Directness | Path directness index: `\|oldest - newest\| / length` |
| `EllipsoidSphericityCHOP.cpp` | `Ewellipsoidsphericity` | EW L2 Ellipsoid Sphericity | Wadell sphericity (Thomsen surface) via direct sizes or PCA fit |
| `EquilibriumCHOP.cpp` | `Ewequilibrium` | EW L2 Equilibrium | Barycenter offset within feet support ellipse |
| `KinematicsCHOP.cpp` | `Ewkinematics` | EW L2 Kinematics | SG-filtered derivatives: Velocity, Acceleration, Jerk, Curvature, Direction |
| `KineticEnergyCHOP.cpp` | `Ewkineticenergy` | EW L2 Kinetic Energy | Total and per-axis kinetic energy (velocity or position mode) |
| `LogDimensionlessJerkCHOP.cpp` | `Ewlogdimensionlessjerk` | EW L2 Log Dimensionless Jerk | Log dimensionless jerk of a speed profile |
| `PointsDensityCHOP.cpp` | `Ewpointsdensity` | EW L2 Points Density | Centroid and spatial dispersion (module or 3D component) |
| `SpectralArcLengthCHOP.cpp` | `Ewspectralarclength` | EW L2 Spectral Arc Length | Spectral arc length (SPARC) of a speed profile |
| `SubmovementCountCHOP.cpp` | `Ewsubmovementcount` | EW L2 Submovement Count | Number of sub-movements of a speed profile |
| `SymmetryCHOP.cpp` | `Ewsymmetry` | EW L2 Symmetry | Geometric reflection symmetry of joint pairs |
| `TrajectoryNonPlanarityCHOP.cpp` | `Ewtrajectorynonplanarity` | EW L2 Trajectory Non-Planarity | Distance of 3D trajectory neighbourhood from local best-fit plane |
| `TriangleSymmetryCHOP.cpp` | `Ewtrianglesymmetry` | EW L2 Triangle Symmetry | 2D upper/left/right vertex asymmetry index |

### 3. Mid-level features (layer 3)
None in the first release: the Gesture Segmenter is held back (`chops/_held_back/mid_level`) until the noise test that belongs to it is finished.

### 4. High-level features (layer 4)
| CHOP File | Operator Type | Op Label | Description |
|---|---|---|---|
| `EnsembleDominanceCHOP.cpp` | `Ewensembledominance` | EW L4 Ensemble Dominance | Dominance scores and leader from the complexity indices |

### Analysis primitives (any layer)
| CHOP File | Operator Type | Op Label | Description |
|---|---|---|---|
| `BinaryPulsesRegularityCHOP.cpp` | `Ewbinarypulsesregularity` | EW AP Binary Pulses Regularity | Whether the intervals between the pulses of a window are equal within a threshold; pulse count (the onset is the rising edge of `is_regular`: a Logic CHOP) |
| `EventSynchronizationCHOP.cpp` | `Eweventsynchronization` | EW AP Event Synchronization | Quian Quiroga event synchrony (Q) and delay/leadership (q) |
| `EventSynchronizationMECSCHOP.cpp` | `Eweventsynchronizationmecs` | EW AP Event Synchronization MECS | Multi Event Class Synchronization across multiple trains |
| `GeneralisedAutoCorrelationCHOP.cpp` | `Ewgeneralisedautocorrelation` | EW AP Generalised Auto Correlation | Recurrence rate as a function of the lag, or at one lag |
| `MultiScaleEntropyCHOP.cpp` | `Ewmultiscaleentropy` | EW AP Multi Scale Entropy | Multi-scale sample entropy curve and complexity index per channel |
| `PeriodicityCHOP.cpp` | `Ewperiodicity` | EW AP Periodicity | Sethares periodicity transform (Small2Large / M-Best) |
| `PhaseLockingValueCHOP.cpp` | `Ewphaselockingvalue` | EW AP Phase Locking Value | Hilbert analytic signal phase synchrony with optional bandpass |
| `RarityCHOP.cpp` | `Ewrarity` | EW AP Rarity | How unusual the movement of the last moments is compared with the recent past (novelty of patterns; any signal; one value per cook) |
| `SampleEntropyCHOP.cpp` | `Ewsampleentropy` | EW AP Sample Entropy | Chebyshev distance template-matching sample entropy, one value SampEn(m, r) |
| `ScalarPeakDetectorCHOP.cpp` | `Ewscalarpeakdetector` | EW AP Scalar Peak Detector | Windowed threshold peak detector |

## Building, testing, packaging

```bash
cmake -S EyesWebTD -B build -G "Visual Studio 17 2022" -A x64     # EyesWebCore is expected next to EyesWebTD (EW_CORE_DIR)
cmake --build build --config Release --parallel
```

The `.dll` files are in `build/Plugins/EyesWeb/<layer>/`. The TouchDesigner headers come from `third_party/touchdesigner_sdk`
(TouchDesigner 2025.32280); pass `-DTD_CHOP_SDK=<install>/Samples/CPlusPlus/CHOP` to build against another install.

Tests (`set EW_TD_PLUGINS=<build>/Plugins/EyesWeb`):

```bash
build/Release/ew_td_tests.exe          # base layer, no TouchDesigner
python -m pytest EyesWebTD/tests       # mock host, package checks (names, layers, version, PyEyesWeb catalog), parity with PyEyesWeb
```

The parity tests need PyEyesWeb and the compiled core module next to the repository (see `tests/host/README.md`); without
them only the host and package tests run.

Package: `cmake --install build --config Release --prefix <dir>` or `cd build && cpack -C Release` gives
`EyesWebTD-<version>-win64.zip` with the DLLs flat in `Plugins/` (TouchDesigner does not load subfolders; the build tree keeps
the layer folders), the palette builder, the changelog and the notices
(`THIRD_PARTY_NOTICES.md`). Copy the DLLs into the `Plugins` folder of the project or into `Documents/Derivative/Plugins`.

## Versions and releases

The version is in `VERSION` (MAJOR.MINOR.PATCH). It goes to every DLL (file properties, and the operator's major / minor
version that TouchDesigner checks against the operators saved in a .toe). Raise MAJOR when a saved project would break (a
parameter or channel renamed or removed), MINOR when operators or parameters are added, PATCH for fixes, and write the
change in `CHANGELOG.md`. To release: set `VERSION`, commit, tag `v<VERSION>` and push the tag: the CI workflow
(`.github/workflows/ci.yml`) builds, tests, packages and attaches the zip to the release.

3D vector parameters (`Refdir`, `Gravity`, `Floor`) are one parameter with three fields: in Python `op.par.Gravityx`,
`Gravityy`, `Gravityz`.
