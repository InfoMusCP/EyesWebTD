"""Parity of GestureSegmenter, Suddenness, ContractionImpulsivity, PositionDependingPotentials,
RegionDependingPotentials, EnsembleDominance and HitCellDetector (CHOP operators) with their PyEyesWeb features.

Both sides see the same float32 values (inputs are cast to float32 and back before either is fed). A PyEyesWeb output that
was not produced is NaN in a Recorder; the CHOPs write 0 there, so the comparison maps NaN to 0 where that is meant.
Differences that are on purpose are tested as the CHOP documents them (class B); defects are strict xfails (class A).
"""
import inspect

import numpy as np
import pytest

from conftest import Signal, assert_close  # noqa: F401
from data import skeleton
from pyeyesweb.data_models.recorder import Recorder
from pyeyesweb.data_models.results import Status
from pyeyesweb.high_level import EnsembleDominance
from pyeyesweb.mid_level.segmentation import GestureSegmenter
from pyeyesweb.mid_level.impulsivity import ContractionImpulsivity  # held back
from pyeyesweb.mid_level.space_occupation import PositionDependingPotentials, RegionDependingPotentials  # held back
from pyeyesweb.mid_level.suddenness import Suddenness  # held back
from pyeyesweb.physical_signals import HitCellDetector


# ----------------------------------------------------------------------------------------------------- helpers
def f32(a):
    """Round to float32 and back: the values both the CHOP and PyEyesWeb are fed."""
    return np.asarray(a, dtype=np.float32).astype(float)


def clip_cook(node, *inputs, **kw):
    node.set("Source", "clip")
    return node.cook(*inputs, **kw)


def stream_cook(node, data, sizes, **kw):
    """Feed `data` (samples, channels) as consecutive timeslices of the given lengths (cycled); the concatenated output."""
    out, i, k = [], 0, 0
    while i < len(data):
        n = min(sizes[k % len(sizes)], len(data) - i)
        out.append(node.cook(data[i:i + n], **kw).data)
        i += n
        k += 1
    return np.vstack(out)


def sequence(feature, *cols):
    """The PyEyesWeb `process` sequence of a stateful feature, one call per row, as a Recorder."""
    rec = Recorder(feature)
    for row in zip(*cols):
        rec.append(feature.process(*row))
    return rec


def columns(rec, *names):
    """Recorder columns as float (n, len(names)); an output not produced (NaN) is 0, as the CHOP writes it."""
    return np.nan_to_num(np.column_stack([np.asarray(rec[n], dtype=float) for n in names]))


def hold(col):
    """Forward fill NaN (an output not updated keeps its previous value), 0 before the first value."""
    out, last = np.empty(len(col)), 0.0
    for i, v in enumerate(col):
        last = last if np.isnan(v) else v
        out[i] = last
    return out


# ---------------------------------------------------------------------------------------------------- signals
def intensity(n, seed):
    """A positive, bursty intensity signal (several gestures)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return f32(np.abs(np.sin(t / 15.0 + seed)) ** 2 * np.abs(1 + 0.3 * rng.standard_normal(n)))


def noise_flags(n):
    return (np.arange(n) % 37 < 5).astype(float)


def phases(n, seed):
    """A 0/1 segmentation signal made of runs of random length 1..6, started by motion or by pause."""
    rng = np.random.default_rng(seed)
    out, value = [], float(seed % 2)
    while len(out) < n:
        out += [value * (0.5 if rng.random() < 0.3 else 1.0)] * int(rng.integers(1, 7))
        value = 1.0 - (value > 0)
    return np.array(out[:n])


def qom_ci(n, seed):
    """Quantity of motion made of bursts (some longer than 25 frames) and a smooth contraction index, both in [0, 1]."""
    rng = np.random.default_rng(seed)
    q, i = np.zeros(n), 0
    while i < n:
        i += int(rng.integers(3, 12))
        length = int(rng.choice([4, 9, 15, 30]))
        q[i:i + length] = rng.uniform(0.05, 0.9) * np.sin(np.linspace(0.2, np.pi - 0.2, length))[:max(0, min(length, n - i))]
        i += length
    ci = 0.5 + 0.4 * np.sin(np.arange(n) / 7.0 + seed) * rng.uniform(0.5, 1.0)
    return f32(q), f32(np.clip(ci, 0, 1))


def walk(n, dims, seed):
    return f32(np.cumsum(np.random.default_rng(seed).standard_normal((n, dims)), axis=0))


def cell_calls(count, rows, cols, seed, max_cells=4):
    rng = np.random.default_rng(seed)
    return [np.column_stack([rng.integers(0, rows, k), rng.integers(0, cols, k)])
            for k in rng.integers(1, max_cells + 1, count)]


# ======================================================================================== GestureSegmenter
GS_NAMES = ("smoothed_intensity", "is_gesturing", "is_gesture_start", "is_gesture_end", "motion_duration", "pause_duration")
RATE = 60.0  # the rate of the mock host's timeline


def gs_oracle(x, threshold, window, continuous=False, feature=None, start=0):
    """PyEyesWeb `process` sequence on timestamps at the input rate (the CHOP counts the time of skipped samples, as
    timestamps do). Events are 0 where the CHOP writes 0 (no output); durations keep their NaN."""
    feature = feature or GestureSegmenter(firing_threshold=threshold, filter_window_length=window, continuous_output=continuous)
    rec = Recorder(feature)
    for index, value in enumerate(np.asarray(x, dtype=float).reshape(-1)):
        rec.append(feature.process(value, timestamp=(start + index) / RATE))
    events = columns(rec, *GS_NAMES[:4])
    durations = np.column_stack([np.asarray(rec[name], dtype=float) for name in GS_NAMES[4:]])
    return np.column_stack([events, durations])


def gs_data(n, seed):
    return intensity(n, seed).reshape(-1, 1)


def test_gesture_segmenter_declaration(plugin):
    node = plugin("GestureSegmenter")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewgesturesegmenter", "EW L3 Gesture Segmenter", 1)
    assert tuple(clip_cook(node, gs_data(30, 1)).names) == GestureSegmenter().outputs.flat_names == GS_NAMES


def test_gesture_segmenter_defaults(plugin):
    node = plugin("GestureSegmenter")
    assert node.get("Filterwindowlength") == 9 and node.get("Firingthreshold") == 0.1 and node.get("Continuousoutput") == 0
    parameters = inspect.signature(GestureSegmenter).parameters
    assert parameters["filter_window_length"].default == 9 and parameters["continuous_output"].default is False
    x = gs_data(203, 1)
    assert_close(clip_cook(node, x).data, gs_oracle(x, 0.1, 9), what="defaults")


@pytest.mark.parametrize("n,seed,threshold,window,continuous",
                         [(203, 1, 0.1, 7, False), (157, 2, 0.3, 5, True), (203, 3, 0.05, 9, False), (157, 4, 0.1, 11, True)])
def test_gesture_segmenter_parity(plugin, n, seed, threshold, window, continuous):
    node = plugin("GestureSegmenter")
    node.set("Firingthreshold", threshold)
    node.set("Filterwindowlength", window)
    node.set("Continuousoutput", int(continuous))
    x = gs_data(n, seed)
    expected = gs_oracle(x, threshold, window, continuous)
    assert expected[:, 2].sum() >= 2 and expected[:, 3].sum() >= 1  # the signal has gestures
    assert np.isfinite(expected[:, 4]).any() and np.isfinite(expected[:, 5]).any()  # and durations
    assert_close(clip_cook(node, x).data, expected)


@pytest.mark.parametrize("sizes", [(1,), (3,), (7,), (1, 3, 7)])
def test_gesture_segmenter_stream_equals_clip_and_process(plugin, sizes):
    x = gs_data(97, 5)
    expected = gs_oracle(x, 0.2, 5)
    node = plugin("GestureSegmenter")
    node.set("Firingthreshold", 0.2)
    node.set("Filterwindowlength", 5)
    assert_close(stream_cook(node, x, sizes), expected, what="stream")
    node.reset_instance()
    node.set("Firingthreshold", 0.2)
    node.set("Filterwindowlength", 5)
    assert_close(clip_cook(node, x).data, expected, what="clip")


def test_gesture_segmenter_reset(plugin):
    node = plugin("GestureSegmenter")
    x = gs_data(60, 6)
    first = node.cook(x).data
    assert_close(node.cook(x).data, gs_oracle(np.vstack([x, x]), 0.1, 9)[60:], what="state continues")
    node.pulse("Reset")
    assert_close(node.cook(x).data, first, what="after Reset")


def test_gesture_segmenter_live_and_structural_parameters(plugin):
    x = gs_data(80, 7)
    a, b = x[:40], x[40:]
    node = plugin("GestureSegmenter")
    node.cook(a)
    node.set("Firingthreshold", 0.4)  # live: the state stays
    live = node.cook(b).data
    oracle = GestureSegmenter(firing_threshold=0.1)
    gs_oracle(a, None, None, feature=oracle)
    oracle.firing_threshold = 0.4
    assert_close(live, gs_oracle(b, None, None, feature=oracle, start=40), what="live")
    node.set("Filterwindowlength", 5)  # structural: the state is forgotten, the window fills again
    structural = node.cook(b).data
    assert_close(structural, gs_oracle(b, 0.4, 5), what="structural")
    assert not structural[:4, :4].any()


def test_gesture_segmenter_even_window_is_invalid(plugin):
    node = plugin("GestureSegmenter")
    node.set("Filterwindowlength", 8)
    out = clip_cook(node, gs_data(30, 1))
    assert out.status_name == "INVALID_INPUT" and "odd" in out.warning


def test_gesture_segmenter_short_input_is_warming_up(plugin):
    x = intensity(5, 1).reshape(-1, 1)
    assert GestureSegmenter(filter_window_length=7).run(x[:, 0]).status[-1] == Status.WARMING_UP
    assert clip_cook(plugin("GestureSegmenter"), x).status_name == "WARMING_UP"


def test_gesture_segmenter_nan_is_invalid_and_its_time_counts(plugin):
    x = intensity(120, 1)
    x[50] = np.nan
    assert GestureSegmenter(filter_window_length=7).run(x).status[50] == Status.INVALID_INPUT
    out = clip_cook(plugin("GestureSegmenter"), x.reshape(-1, 1))
    assert out.status_name == "INVALID_INPUT"
    assert_close(out.data, gs_oracle(x, 0.1, 9), what="skipped sample")


def test_gesture_segmenter_bad_input(plugin):
    node = plugin("GestureSegmenter")
    out = clip_cook(node, np.zeros((5, 0)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not np.nan_to_num(out.data).any()
    out = plugin("GestureSegmenter").cook(f32(intensity(30, 1)).reshape(-1, 1), timeslice=10)  # stream mode, input is not a timeslice
    assert out.status_name == "INVALID_INPUT" and "Clip" in out.warning and not np.nan_to_num(out.data).any()


# ===================================================================================== ContractionImpulsivity
CI_NAMES = ("impulsivity_index", "gesture_duration")


def ci_oracle(data, duration, threshold, rate):
    f = ContractionImpulsivity(gesture_duration=duration, peak_threshold=threshold, sampling_rate=rate)
    return columns(sequence(f, data[:, 0], data[:, 1]), *CI_NAMES)


def ci_node(plugin, duration, threshold, frames):
    node = plugin("ContractionImpulsivity")
    node.set("Gesdur", duration)
    node.set("Threshold", threshold)
    node.set("Frames", frames)
    return node


def test_contraction_impulsivity_declaration(plugin):
    node = plugin("ContractionImpulsivity")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewcontractionimpulsivity", "EW L3 Contraction Impulsivity", 1)
    assert tuple(clip_cook(node, np.zeros((10, 2))).names) == ContractionImpulsivity().outputs.flat_names == CI_NAMES


@pytest.mark.parametrize("n,seed,duration,threshold,frames", [(211, 1, 25.0, 0.02, 60.0), (150, 2, 10.0, 0.2, 30.0), (190, 3, 40.0, 0.05, 25.0)])
def test_contraction_impulsivity_parity(plugin, n, seed, duration, threshold, frames):
    # The defaults are the CHOP's (Frames 60; PyEyesWeb has no rate by default and reports per frame, class B); the motion
    # threshold (0.01) is not a CHOP parameter and equals the PyEyesWeb default.
    q, ci = qom_ci(n, seed)
    data = np.column_stack([q, ci])
    expected = ci_oracle(data, duration, threshold, frames)
    assert (expected[:, 0] > 0).any()
    assert_close(clip_cook(ci_node(plugin, duration, threshold, frames), data).data, expected)


@pytest.mark.parametrize("sizes", [(1,), (3,), (7,), (4, 9)])
def test_contraction_impulsivity_stream_equals_clip_and_process(plugin, sizes):
    q, ci = qom_ci(130, 4)
    data = np.column_stack([q, ci])
    expected = ci_oracle(data, 25.0, 0.02, 60.0)
    assert (expected[:, 0] > 0).any()
    assert_close(stream_cook(plugin("ContractionImpulsivity"), data, sizes), expected, what="stream")
    assert_close(clip_cook(plugin("ContractionImpulsivity"), data).data, expected, what="clip")


def test_contraction_impulsivity_reset(plugin):
    q, ci = qom_ci(40, 5)
    data = np.column_stack([q, ci])
    node = plugin("ContractionImpulsivity")
    node.cook(data[:19])  # cut inside a gesture on purpose
    node.pulse("Reset")
    assert_close(node.cook(data).data, ci_oracle(data, 25.0, 0.02, 60.0))


def test_contraction_impulsivity_parameters_are_live(plugin):
    # All parameters are live in the core: a gesture in progress survives a change of Threshold and of Frames.
    q = f32([0, 0.05, 0.3, 0.4, 0.2, 0.1, 0, 0])
    ci = f32([0.5, 0.5, 0.6, 0.8, 0.7, 0.6, 0.5, 0.5])
    data = np.column_stack([q, ci])
    node = plugin("ContractionImpulsivity")
    node.cook(data[:4])
    node.set("Threshold", 0.1)
    node.set("Frames", 30.0)
    out = node.cook(data[4:]).data
    oracle = ContractionImpulsivity(gesture_duration=25.0, peak_threshold=0.02, sampling_rate=60.0)
    sequence(oracle, q[:4], ci[:4])
    oracle.peak_threshold, oracle.sampling_rate = 0.1, 30.0
    assert_close(out, columns(sequence(oracle, q[4:], ci[4:]), *CI_NAMES))
    assert out[:, 1].max() > 0


def test_contraction_impulsivity_nan_is_invalid(plugin):
    q, ci = qom_ci(40, 5)
    q[10] = np.nan
    assert ContractionImpulsivity().run(q, ci).status[10] == Status.INVALID_INPUT
    assert clip_cook(plugin("ContractionImpulsivity"), np.column_stack([q, ci])).status_name == "INVALID_INPUT"


def test_contraction_impulsivity_bad_input(plugin):
    node = plugin("ContractionImpulsivity")
    for shape in ((5, 1), (5, 0)):
        out = clip_cook(node, np.zeros(shape))
        assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ================================================================================================ Suddenness
# The outputs are in the PyEyesWeb order (is_sudden first); the whole input is one window and one trajectory (Dims channels).
SUD_NAMES = ("is_sudden", "alpha", "beta", "gamma")


def sud_oracle(positions, dims, method):
    n = len(positions)
    r = Suddenness(window=n, dims=dims, method=method).run(positions)[-1]
    assert r.status == Status.OK
    return np.array([float(r.is_sudden), r.alpha, r.beta, r.gamma])


def test_suddenness_declaration(plugin):
    node = plugin("Suddenness")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewsuddenness", "EW L3 Suddenness", 1)
    out = node.cook(walk(30, 3, 1))
    assert tuple(out.names) == SUD_NAMES and out.data.shape == (1, 4)
    assert list(out.names) == list(Suddenness(window=10, dims=3).outputs.flat_names)


@pytest.mark.parametrize("n,seed,dims,method", [(47, 1, 3, "constrained"), (90, 3, 3, "constrained"), (33, 5, 2, "constrained"),
                                                (6, 1, 3, "quantile"), (7, 2, 3, "quantile"), (15, 2, 3, "quantile"),
                                                (20, 1, 3, "quantile"), (200, 1, 3, "quantile")])
def test_suddenness_parity(plugin, n, seed, dims, method):
    node = plugin("Suddenness")
    node.set("Algorithm", method)
    node.set("Dims", dims)
    x = walk(n, dims, seed)
    assert_close(node.cook(x).data[0], sud_oracle(x, dims, method))


@pytest.mark.parametrize("joints,dims", [(2, 3), (4, 3), (3, 2)])
def test_suddenness_takes_one_trajectory(plugin, joints, dims):
    """PyEyesWeb takes one trajectory: several joints are refused, not averaged."""
    node = plugin("Suddenness")
    node.set("Dims", dims)
    out = node.cook(f32(skeleton(40, joints=joints, dims=dims, seed=9)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


def test_suddenness_constant_trajectory_is_the_gaussian_fallback(plugin):
    assert_close(plugin("Suddenness").cook(np.ones((20, 3))).data[0], sud_oracle(np.ones((20, 3)), 3, "constrained"))


def test_suddenness_short_input_is_warming_up(plugin):
    x = walk(5, 3, 1)
    assert Suddenness(window=6, dims=3).run(np.vstack([x, x[:1]])).status[-2] == Status.WARMING_UP
    assert plugin("Suddenness").cook(x).status_name == "WARMING_UP"


def test_suddenness_unfittable_quantile_is_invalid(plugin):
    node = plugin("Suddenness")  # held back: skips; to revise when it returns (PyEyesWeb has no `method` any more)
    x = walk(10, 3, 1)
    assert Suddenness(window=10, dims=3, method="quantile").run(x)[-1].status == Status.INVALID_INPUT
    node.set("Algorithm", "quantile")
    out = node.cook(x)
    assert out.status_name == "INVALID_INPUT" and not out.data.any()


def test_suddenness_nan_is_invalid(plugin):
    x = walk(20, 3, 1)
    x[7, 1] = np.nan
    assert Suddenness(window=20, dims=3).run(x).status[7] == Status.INVALID_INPUT
    assert plugin("Suddenness").cook(x).status_name == "INVALID_INPUT"


def test_suddenness_channel_count_is_not_dims(plugin):
    out = plugin("Suddenness").cook(np.zeros((10, 4)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ======================================================================= Position / Region depending potentials
PP_TYPES = {"incdec": "increment_decrement", "gaussian": "gaussian", "polynomial": "polynomial",
            "occupation": "occupation_rates", "logarithmic": "logarithmic"}


def potentials_node(plugin, name, cx, cy, **params):
    node = plugin(name)
    node.set("Cellsalongx", cx)
    node.set("Cellsalongy", cy)
    for key, value in params.items():
        node.set(key, value)
    return node


def check_cook(node, feature, cells, what=""):
    """One cook against one `process`: the CHOP is (samples = columns, channels = rows) = the transpose of the matrix."""
    out = node.cook(np.asarray(cells, dtype=float))
    result = feature.process(np.asarray(cells, dtype=int))
    assert result.status == Status.OK and out.status_name == "OK", what
    assert_close(out.data.T, result.potential, what=what)
    return out


def test_position_potentials_declaration(plugin):
    node = potentials_node(plugin, "PositionDependingPotentials", 7, 5)
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewpositiondependingpotentials", "EW L3 Position Depending Potentials", 1)
    out = node.cook(np.array([[1.0, 2.0]]))
    # Class B: the matrix is a CHOP of cells_along_y channels row_0.. by cells_along_x samples (PyEyesWeb: potential_<i>_<j>).
    assert list(out.names) == [f"row_{i}" for i in range(5)] and out.data.shape == (7, 5)
    assert len(PositionDependingPotentials(cells_along_x=7, cells_along_y=5).outputs.flat_names) == 35


@pytest.mark.parametrize("kind", list(PP_TYPES))
@pytest.mark.parametrize("cx,cy,seed", [(10, 10, 1), (7, 5, 2)])
def test_position_potentials_parity(plugin, kind, cx, cy, seed):
    # The CHOP default Dec is 0.1 (core and PyEyesWeb: 1.0, plan item 6): Dec is set on both sides. Inc, Dec and the type are
    # the only potential parameters the CHOP exposes; the others (kernels, window) keep the PyEyesWeb defaults.
    node = potentials_node(plugin, "PositionDependingPotentials", cx, cy, Potentialtype=kind, Inc=0.8, Dec=0.15)
    feature = PositionDependingPotentials(cells_along_x=cx, cells_along_y=cy, potential_type=PP_TYPES[kind],
                                          increment_factor=0.8, decrement_factor=0.15)
    for i, cells in enumerate(cell_calls(6, cy, cx, seed)):
        check_cook(node, feature, cells, f"{kind} cook {i}")


def test_position_potentials_default_parameters(plugin):
    node = plugin("PositionDependingPotentials")
    feature = PositionDependingPotentials(decrement_factor=0.1)  # Class B: only Dec differs from PyEyesWeb's default
    assert (node.get("Inc"), node.get("Dec")) == (1.0, 0.1)
    for i, cells in enumerate(cell_calls(5, 10, 10, 3)):
        check_cook(node, feature, cells, f"cook {i}")


def test_position_potentials_reset_and_state(plugin):
    calls = cell_calls(4, 5, 7, 4)
    node = potentials_node(plugin, "PositionDependingPotentials", 7, 5)
    feature = PositionDependingPotentials(cells_along_x=7, cells_along_y=5, decrement_factor=0.1)
    firsts = [check_cook(node, feature, c).data for c in calls]
    node.pulse("Reset")
    feature.reset()
    again = [check_cook(node, feature, c).data for c in calls]
    for a, b in zip(firsts, again):
        assert_close(a, b, what="after Reset")
    assert not np.allclose(firsts[-1], firsts[0])


def test_position_potentials_live_and_structural_parameters(plugin):
    calls = cell_calls(6, 5, 7, 5)
    node = potentials_node(plugin, "PositionDependingPotentials", 7, 5)
    feature = PositionDependingPotentials(cells_along_x=7, cells_along_y=5, decrement_factor=0.1)
    for c in calls[:3]:
        check_cook(node, feature, c)
    node.set("Inc", 0.5)  # live: the potential is kept
    feature.increment_factor = 0.5
    live = check_cook(node, feature, calls[3], "live").data
    assert live.min() < 0 and live.max() > 0.2
    node.set("Cellsalongx", 4)  # structural: the potential restarts on the new grid
    feature.cells_along_x = 4
    fresh = PositionDependingPotentials(cells_along_x=4, cells_along_y=5, increment_factor=0.5, decrement_factor=0.1)
    cells = np.minimum(calls[4], [4, 3])
    assert_close(check_cook(node, feature, cells, "structural").data, check_cook_data(fresh, cells), what="restarted")


def check_cook_data(feature, cells):
    return feature.process(np.asarray(cells, dtype=int)).potential.T


def test_position_potentials_cells_outside_the_grid_are_ignored(plugin):
    # Class B: documented in the CHOP source: cells outside the grid are dropped (PyEyesWeb: INVALID_INPUT, no update).
    node = potentials_node(plugin, "PositionDependingPotentials", 7, 5)
    feature = PositionDependingPotentials(cells_along_x=7, cells_along_y=5, decrement_factor=0.1)
    mixed = np.array([[1, 2], [9, 0], [0, 9], [-1, 3], [4, 6]])
    out = node.cook(mixed.astype(float))
    assert_close(out.data.T, feature.process(mixed[[0, 4]]).potential)
    assert out.status_name == "OK"


def test_position_potentials_no_cell_is_no_output(plugin):
    feature = PositionDependingPotentials(cells_along_x=7, cells_along_y=5)
    assert feature.process(np.zeros((0, 2), dtype=int)).status == Status.NO_OUTPUT
    node = potentials_node(plugin, "PositionDependingPotentials", 7, 5)
    node.cook(np.array([[1.0, 2.0]]))
    assert node.cook(np.array([[99.0, 99.0]])).status_name == "NO_OUTPUT"


def test_position_potentials_nan_is_invalid(plugin):
    assert PositionDependingPotentials(cells_along_x=3, cells_along_y=2).process(np.array([[0.0, np.nan]])).status == Status.INVALID_INPUT
    assert potentials_node(plugin, "PositionDependingPotentials", 3, 2).cook(np.array([[0.0, np.nan]])).status_name == "INVALID_INPUT"


def test_position_potentials_wrong_channel_count(plugin):
    out = plugin("PositionDependingPotentials").cook(np.ones((3, 1)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


RG_TYPES = {"incdec": "increment_decrement", "linear": "occupation_rates_linear", "exponential": "occupation_rates_exponential"}


def region_feature(cx, cy, regions, kind, kind_input, inc, dec):
    return RegionDependingPotentials(cells_along_x=cx, cells_along_y=cy, number_of_regions=regions, potential_type=RG_TYPES[kind],
                                     input_kind=kind_input, increment_factor=inc, decrement_factor=dec)


def test_region_potentials_declaration(plugin):
    node = potentials_node(plugin, "RegionDependingPotentials", 6, 3)
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewregiondependingpotentials", "EW L3 Region Depending Potentials", 1)
    out = node.cook(np.array([[0.0, 1.0]]))
    assert list(out.names) == ["row_0", "row_1", "row_2"] and out.data.shape == (6, 3)  # class B: as the position potentials
    assert len(RegionDependingPotentials(cells_along_x=6, cells_along_y=3).outputs.flat_names) == 18


@pytest.mark.parametrize("kind", list(RG_TYPES))
@pytest.mark.parametrize("cx,cy,regions,seed", [(10, 10, 4, 1), (7, 5, 6, 2)])
def test_region_potentials_cells_parity(plugin, kind, cx, cy, regions, seed):
    # The CHOP has no mask (every cell is one region: the field is uniform), no initial values, MaxValue or TimeConstant:
    # PyEyesWeb's defaults are used for them (class B). Dec is 0.1 in the CHOP by default, set explicitly on both.
    node = potentials_node(plugin, "RegionDependingPotentials", cx, cy, Potentialtype=kind, Numregions=regions, Inc=0.7, Dec=0.2)
    feature = region_feature(cx, cy, regions, kind, "cells", 0.7, 0.2)
    for i, cells in enumerate(cell_calls(6, cy, cx, seed)):
        check_cook(node, feature, cells, f"{kind} cook {i}")


@pytest.mark.parametrize("kind", list(RG_TYPES))
def test_region_potentials_hit_regions_parity(plugin, kind):
    # One channel = the indexes of the regions hit, one per sample.
    node = potentials_node(plugin, "RegionDependingPotentials", 6, 3, Potentialtype=kind, Numregions=5, Inc=0.7, Dec=0.2)
    feature = region_feature(6, 3, 5, kind, "hit_regions", 0.7, 0.2)
    rng = np.random.default_rng(3)
    for i in range(6):
        hits = rng.integers(0, 5, int(rng.integers(1, 5)))
        out = node.cook(hits.astype(float).reshape(-1, 1))
        result = feature.process(hits)
        assert result.status == Status.OK and out.status_name == "OK"
        assert_close(out.data.T, result.potential, what=f"{kind} cook {i}")


def test_region_potentials_reset_and_parameters(plugin):
    calls = cell_calls(5, 3, 6, 6)
    node = potentials_node(plugin, "RegionDependingPotentials", 6, 3, Numregions=5)
    feature = region_feature(6, 3, 5, "incdec", "cells", 1.0, 0.1)
    firsts = [check_cook(node, feature, c).data for c in calls[:3]]
    node.pulse("Reset")
    feature.reset()
    assert_close(check_cook(node, feature, calls[0]).data, firsts[0], what="after Reset")
    node.set("Inc", 0.4)  # live: the region values are kept
    feature.increment_factor = 0.4
    check_cook(node, feature, calls[1], "live")
    node.set("Numregions", 3)  # structural: the values restart
    feature.number_of_regions = 3
    out = check_cook(node, feature, calls[2], "structural")
    fresh = region_feature(6, 3, 3, "incdec", "cells", 0.4, 0.1)
    assert_close(out.data, check_cook_data(fresh, calls[2]), what="restarted")


def test_region_potentials_bad_region_is_invalid(plugin):
    feature = region_feature(4, 3, 4, "incdec", "hit_regions", 1.0, 0.1)
    assert feature.process(np.array([9])).status == Status.INVALID_INPUT
    node = potentials_node(plugin, "RegionDependingPotentials", 4, 3, Numregions=4)
    assert node.cook(np.array([[9.0]])).status_name == "INVALID_INPUT"


def test_region_potentials_zero_channels_is_invalid(plugin):
    node = plugin("RegionDependingPotentials")
    try:
        out = node.cook(np.zeros((2, 0)))
    finally:
        node.reset_instance()
    assert out.status_name == "INVALID_INPUT"


# ========================================================================================== EnsembleDominance
def dominance(plugin, indices):
    return plugin("EnsembleDominance").cook(np.asarray(indices, dtype=float).reshape(1, -1))


def test_ensemble_dominance_declaration(plugin):
    node = plugin("EnsembleDominance")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewensembledominance", "EW L4 Ensemble Dominance", 1)
    out = node.cook(np.array([[2.0, 1.0, 3.0, 4.0]]))
    # Class B: one channel per participant, named dominance<i> (the PyEyesWeb output is variable in size), then the leader.
    assert list(out.names) == ["dominance0", "dominance1", "dominance2", "dominance3", "leader_index", "leader_complexity"]
    assert out.data.shape == (1, 6)
    assert set(EnsembleDominance().outputs.names) == {"dominance_score", "leader_index", "leader_complexity"}


@pytest.mark.parametrize("indices", [[2.0, 1.0, 3.0], [0.31, 1.7, 0.9, 2.2, 0.05, 1.1, 0.4], [3.0, 3.0, 1.0], [5.0], [0.0, 0.0, 0.0],
                                     [np.nan, 1.0, 2.0], [1.0, np.nan, np.nan, 4.0]])
def test_ensemble_dominance_parity(plugin, indices):
    indices = f32(indices)
    r = EnsembleDominance().process(indices)
    assert r.status == Status.OK
    out = dominance(plugin, indices)
    n = len(indices)
    assert out.status_name == "OK"
    assert_close(out.data[0, :n], r.dominance_score, what="dominance_score")
    assert_close(out.data[0, n:], [r.leader_index, r.leader_complexity], what="leader")


def test_ensemble_dominance_negative_index_is_invalid(plugin):
    assert EnsembleDominance().process(f32([-1.0, 2.0, 0.0])).status == Status.INVALID_INPUT
    out = dominance(plugin, f32([-1.0, 2.0, 0.0]))
    assert out.status_name == "INVALID_INPUT" and "negative" in out.warning


def test_ensemble_dominance_uses_the_first_sample(plugin):
    out = plugin("EnsembleDominance").cook(np.array([[2.0, 1.0, 3.0], [1.0, 5.0, 0.5]]))
    assert_close(out.data[0], dominance(plugin, [2.0, 1.0, 3.0]).data[0])


def test_ensemble_dominance_infinite_is_invalid(plugin):
    assert EnsembleDominance().process(np.array([1.0, np.inf])).status == Status.INVALID_INPUT
    assert dominance(plugin, [1.0, 2.0, np.inf]).status_name == "INVALID_INPUT"


def test_ensemble_dominance_no_participant(plugin):
    out = plugin("EnsembleDominance").cook(np.zeros((1, 0)))
    # PyEyesWeb raises for an empty list of participants; the CHOP reports it as INVALID_INPUT
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ========================================================================================== HitCellDetector
def hit_oracle(points, **kw):
    r = HitCellDetector(**kw).process(points)
    assert r.status == Status.OK
    return r.cells.astype(float)


def hit_points(n, seed, lo, hi):
    pts = np.random.default_rng(seed).uniform(lo, hi, (n, 2))
    return f32(pts)


def test_hit_cell_detector_declaration(plugin):
    node = plugin("HitCellDetector")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewhitcelldetector", "EW L1 Hit Cell Detector", 1)
    out = node.cook(np.array([[0.5, 0.5], [0.1, 0.9]]))
    # Class B: PyEyesWeb's output is a (n, 2) list of (i, j); the CHOP has one sample per point, channels cell_row, cell_col.
    assert list(out.names) == ["cell_row", "cell_col"] and out.data.shape == (2, 2)
    assert HitCellDetector().outputs.names == ("cells",)


@pytest.mark.parametrize("kind", ["default", "custom"])
def test_hit_cell_detector_parity(plugin, kind):
    node = plugin("HitCellDetector")
    if kind == "default":
        kw, pts = {}, hit_points(31, 1, -0.3, 1.3)
    else:
        kw = dict(cells_along_x=7, cells_along_y=4, x_min=-1.0, x_max=2.0, y_min=0.5, y_max=3.0)
        for chop_name, name in (("Cellsalongx", "cells_along_x"), ("Cellsalongy", "cells_along_y"), ("Xmin", "x_min"), ("Xmax", "x_max"),
                                ("Ymin", "y_min"), ("Ymax", "y_max")):
            node.set(chop_name, kw[name])
        pts = np.column_stack([hit_points(29, 2, -1.5, 2.5)[:, 0], hit_points(29, 3, 0.0, 3.5)[:, 1]])
    out = node.cook(pts)
    assert out.status_name == "OK"
    assert_close(out.data, hit_oracle(pts, **kw))


def test_hit_cell_detector_edges_of_the_area(plugin):
    pts = f32([[0, 0], [1, 1], [1, 0], [0, 1], [0.5, 0.5], [0.1, 0.2], [0.3, 0.7]])
    assert_close(plugin("HitCellDetector").cook(pts).data, hit_oracle(pts), what="the upper edge belongs to the last cell")


def test_hit_cell_detector_clip_off_inside(plugin):
    node = plugin("HitCellDetector")
    node.set("Clipvalues", 0)
    pts = hit_points(25, 4, 0.0, 1.0)
    assert_close(node.cook(pts).data, hit_oracle(pts, clip_values=False))


def test_hit_cell_detector_clip_off_outside_gives_minus_one(plugin):
    # Class B: the core rejects the whole call (PyEyesWeb: INVALID_INPUT), so every point is -1, the valid ones too; the CHOP
    # source says "-1 for a point outside the area", which understates this.
    node = plugin("HitCellDetector")
    node.set("Clipvalues", 0)
    out = node.cook(f32([[0.5, 0.5], [1.5, 0.5], [0.2, -0.1]]))
    assert_close(out.data, np.full((3, 2), -1.0))


def test_hit_cell_detector_clip_off_outside_is_invalid(plugin):
    pts = f32([[0.5, 0.5], [1.5, 0.5]])
    assert HitCellDetector(clip_values=False).process(pts).status == Status.INVALID_INPUT
    node = plugin("HitCellDetector")
    node.set("Clipvalues", 0)
    assert node.cook(pts).status_name == "INVALID_INPUT"


def test_hit_cell_detector_unreadable_input_gives_minus_one(plugin):
    out = plugin("HitCellDetector").cook(np.full((3, 1), 0.5))
    assert out.status_name == "INVALID_INPUT" and (out.data == -1).all()


def test_hit_cell_detector_nan_is_invalid(plugin):
    pts = np.array([[0.5, np.nan], [0.2, 0.3]])
    assert HitCellDetector().process(pts).status == Status.INVALID_INPUT
    assert plugin("HitCellDetector").cook(pts).status_name == "INVALID_INPUT"
