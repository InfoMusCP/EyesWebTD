"""Parity of the Phase 4 operators MotionNoiseDetector, SuddennessImpulsivity, CrossRecurrencePlot and
TimeWindowSynchronizer with their PyEyesWeb features, on the same float32 data.

MotionNoiseDetector is a stream operator (Source = stream | clip, Reset); SuddennessImpulsivity and
CrossRecurrencePlot are frame operators (the whole input is one window); TimeWindowSynchronizer is a buffer operator
(PyEyesWeb has it as a plain utility class: the CHOP is its form for sampled streams, same maths).

Deliberate differences from PyEyesWeb (tested below):
  * MotionNoiseDetector: the `units` scaling of the threshold is not exposed; the labels are "0", "1", ... (their text
    order decides which joint counts: "9" sorts after "10").
  * TimeWindowSynchronizer: no presentation times, no frame streams; one window per cook (the newest complete one).
"""
import numpy as np
import pytest

from conftest import Signal, assert_close
from data import skeleton, smooth_walk
from pyeyesweb.analysis_primitives.synchronization import CrossRecurrencePlot, RecurrencePlot
from pyeyesweb.low_level.motion_noise import MotionNoiseDetector  # held back
from pyeyesweb.mid_level.impulsivity import SuddennessImpulsivity  # held back
from pyeyesweb.physical_signals import TimeWindowSynchronizer


# ---- helpers --------------------------------------------------------------------------------------------------------
def f32(x):
    """The data as TouchDesigner holds it: float32, handed back as float64 so both sides see identical values."""
    return np.asarray(x, dtype=np.float32).astype(np.float64)


def cook(node, data, rate=60.0, **kw):
    return node.cook(Signal(np.asarray(data, dtype=np.float32), sample_rate=rate), sample_rate=rate, **kw)


def stream(node, data, chunk, rate=60.0):
    return np.vstack([cook(node, data[i:i + chunk], rate).data for i in range(0, len(data), chunk)])


def stream_status(node, data, chunk, rate=60.0):
    outs = [cook(node, data[i:i + chunk], rate) for i in range(0, len(data), chunk)]
    return np.vstack([o.data for o in outs]), [o.status for o in outs]


def clip(node, data, rate=60.0):
    node.set("Source", "clip")
    out = cook(node, data, rate)
    node.set("Source", "stream")
    return out


def assert_invalid(out, zero=True):
    assert out.status_name == "INVALID_INPUT" and out.status == 3
    assert out.warning
    if zero:
        assert not np.nan_to_num(out.data).any()


def declared(node, op_type, label, inputs, max_inputs=None):
    assert (node.op_type, node.op_label, node.min_inputs, node.max_inputs) == (op_type, label, inputs, max_inputs or inputs)
    assert not [i for i in node.setup_issues if i.startswith("error")]


# ---- MotionNoiseDetector --------------------------------------------------------------------------------------------
def noise_data(n=90, joints=2, rate=60.0, seed=11):
    """A skeleton that moves smoothly, then jumps about (frames 30..59), then moves smoothly again."""
    data = skeleton(n, joints, 3, rate, seed=seed)
    rng = np.random.default_rng(seed)
    data[30:60] += rng.normal(scale=0.3, size=(30, joints * 3))
    return f32(data)


def mnd_feature(joints, rate, threshold=0.5):
    return MotionNoiseDetector(labels=[str(j) for j in range(joints)], noise_threshold=threshold, sampling_rate=rate)


def mnd_expected(data, joints, rate, threshold=0.5):
    feature = mnd_feature(joints, rate, threshold)
    return np.array([feature.process(f).is_noisy for f in data.reshape(len(data), joints, 3)], dtype=float)


def test_motion_noise_declaration(plugin):
    node = plugin("MotionNoiseDetector")
    declared(node, "Ewmotionnoisedetector", "EW L2 Motion Noise Detector", 1)
    assert cook(node, np.ones((4, 6))).names == list(mnd_feature(2, 60.0).outputs.flat_names)
    assert [p.name for p in node.params if p.page != "Cook"] == ["Dims", "Threshold"]
    assert (node.get("Dims"), node.get("Threshold")) == (3, 0.5)


@pytest.mark.parametrize("pars,joints,rate", [({}, 2, 60.0), ({"Threshold": 0.05}, 3, 50.0), ({"Threshold": 3.0}, 1, 60.0)])
def test_motion_noise_parity(plugin, pars, joints, rate):
    node = plugin("MotionNoiseDetector")
    for key, value in pars.items():
        node.set(key, value)
    data = noise_data(90, joints, rate)
    expected = mnd_expected(data, joints, rate, pars.get("Threshold", 0.5))
    out = clip(node, data, rate)
    assert out.status_name == "OK"
    assert_close(out.data[:, 0], expected)
    if not pars:
        assert 0 < expected.sum() < len(expected)  # both flags occur
        assert not expected[:14].any()  # false until 14 speeds have been seen


def test_motion_noise_last_name_decides(plugin):
    """PyEyesWeb quirk kept: only the joint whose name sorts last counts. With 11 joints ("0".."10") that is "9"."""
    node = plugin("MotionNoiseDetector")
    data = np.zeros((60, 33))
    rng = np.random.default_rng(3)
    data[:, 30:33] = rng.normal(scale=0.4, size=(60, 3))  # joint 10 jumps about, joint 9 is still
    data = f32(data)
    expected = mnd_expected(data, 11, 60.0)
    assert not expected.any()
    assert_close(clip(node, data).data[:, 0], expected)
    data[:, 27:30] = rng.normal(scale=0.4, size=(60, 3))  # now joint 9 jumps
    assert_close(clip(node, data).data[:, 0], mnd_expected(data, 11, 60.0))
    assert mnd_expected(data, 11, 60.0).any()


@pytest.mark.parametrize("chunk", [1, 3, 7])
def test_motion_noise_state(plugin, chunk):
    node = plugin("MotionNoiseDetector")
    data = noise_data(63, 2)
    expected = mnd_expected(data, 2, 60.0)
    assert_close(stream(node, data, chunk)[:, 0], expected, what="stream chunks vs process")
    assert_close(clip(node, data).data[:, 0], expected, what="clip vs process")


def test_motion_noise_reset_and_parameters(plugin):
    node = plugin("MotionNoiseDetector")
    data = noise_data(90, 2)
    first = stream(node, data, 90)
    assert first[:, 0].any()
    again = stream(node, data[40:], 50)
    assert again[:12, 0].any()  # continues from the state of the first pass: no warm-up
    node.pulse("Reset")
    assert not stream(node, data[40:], 50)[:14, 0].any()  # Reset forgets: false again during the first 14 frames
    # LIVE: the threshold keeps the windows. Reference: one feature whose threshold changes between the halves.
    node.pulse("Reset")
    feature = mnd_feature(2, 60.0, 0.5)
    head = [feature.process(f).is_noisy for f in data[:45].reshape(45, 2, 3)]
    feature.noise_threshold = 5.0
    tail = [feature.process(f).is_noisy for f in data[45:].reshape(45, 2, 3)]
    node.set("Threshold", 0.5)
    a = cook(node, data[:45]).data[:, 0]
    node.set("Threshold", 5.0)
    b = cook(node, data[45:]).data[:, 0]
    assert_close(np.concatenate([a, b]), np.array(head + tail, dtype=float), what="live threshold keeps the state")
    # STRUCTURAL: the set of joints (here through Dims) forgets the windows: the next 14 frames are false again.
    node.pulse("Reset")
    cook(node, data[:45])
    node.set("Dims", 1)  # 6 joints of 1 axis
    assert not cook(node, data[45:55]).data[:, 0].any()
    # the same data without the change still sees the jumps
    node.set("Dims", 3)
    node.pulse("Reset")
    cook(node, data[:45])
    assert cook(node, data[45:60]).data[:, 0].any()


def test_motion_noise_edges(plugin):
    node = plugin("MotionNoiseDetector")
    assert_invalid(cook(node, np.ones((4, 7))))  # 7 channels, Dims = 3
    assert_invalid(cook(node, np.ones((5, 6)), timeslice=3))  # not a timeslice
    assert node.cook().status_name == "NO_OUTPUT"  # no input


def test_motion_noise_nan_recovers(plugin):
    node = plugin("MotionNoiseDetector")
    data = noise_data(80, 2)
    bad = data.copy()
    bad[40, 2] = np.nan
    bad[41, 0] = np.inf
    out, statuses = stream_status(node, bad, 1)
    assert statuses[40] == statuses[41] == 3 and statuses.count(3) == 2
    valid = np.delete(data, [40, 41], axis=0)
    assert_close(np.delete(out[:, 0], [40, 41]), mnd_expected(valid, 2, 60.0), what="outputs of the valid frames")
    assert out[40, 0] == out[41, 0] == 0


# ---- SuddennessImpulsivity ------------------------------------------------------------------------------------------
def walk(n, dims, seed):
    return f32(np.cumsum(np.random.default_rng(seed).normal(size=(n, dims)), axis=0))


def si_expected(x, **kw):
    n = len(x)
    record = SuddennessImpulsivity(window=n, **kw).run(x)
    return record.impulsivity_index[-1], int(record.status[-1])


SI_CASES = {
    "default_3d": ({}, {}, 3, 20, 1),
    "default_3d_long": ({}, {}, 3, 41, 2),
    "dims2": ({"Dims": 2}, {"dims": 2}, 2, 25, 3),
    "epsilon": ({"Epsilon": 0.2}, {"direction_change_epsilon": 0.2}, 3, 30, 4),
    "quantile": ({"Algorithm": "quantile"}, {"method": "quantile"}, 3, 60, 4),
    "quantile_dims2_epsilon": ({"Algorithm": "quantile", "Dims": 2, "Epsilon": 0.3},
                               {"method": "quantile", "dims": 2, "direction_change_epsilon": 0.3}, 2, 36, 5),
    "not_sudden_zero": ({}, {}, 3, 30, 24),
}


def test_suddenness_impulsivity_declaration(plugin):
    node = plugin("SuddennessImpulsivity")
    declared(node, "Ewsuddennessimpulsivity", "EW L3 Suddenness Impulsivity", 1)
    out = cook(node, walk(10, 3, 1))
    assert out.names == list(SuddennessImpulsivity(window=6).outputs.flat_names) == ["impulsivity_index"]
    assert (out.num_channels, out.num_samples) == (1, 1)


@pytest.mark.parametrize("case", list(SI_CASES))
def test_suddenness_impulsivity_parity(plugin, case):
    pars, kw, dims, n, seed = SI_CASES[case]
    node = plugin("SuddennessImpulsivity")
    for key, value in pars.items():
        node.set(key, value)
    x = walk(n, dims, seed)
    value, status = si_expected(x, **kw)
    out = cook(node, x)
    assert out.status_name == "OK" and status == 0
    assert_close(out.data[0, 0], value, what=case)


def test_suddenness_impulsivity_is_not_always_zero(plugin):
    """The parity cases must exercise a non-zero index and a sudden/not sudden window each."""
    node = plugin("SuddennessImpulsivity")
    values = [cook(node, walk(n, 3, seed)).data[0, 0] for n, seed in ((20, 1), (41, 2), (30, 24))]
    assert any(v > 0 for v in values) and any(v == 0 for v in values)


def test_suddenness_impulsivity_takes_one_trajectory(plugin):
    """PyEyesWeb takes one trajectory: several joints are refused, not averaged."""
    node = plugin("SuddennessImpulsivity")
    out = cook(node, np.hstack([walk(30, 3, 21), walk(30, 3, 22)]))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


def test_suddenness_impulsivity_statuses(plugin):
    node = plugin("SuddennessImpulsivity")
    for n in (1, 2, 5):  # PyEyesWeb: WARMING_UP below 6 frames
        out = cook(node, walk(n, 3, 1))
        assert out.status_name == "WARMING_UP" and out.status == 1 and not out.data.any()
    assert SuddennessImpulsivity(window=6).process(walk(1, 3, 1)[0]).status.name == "WARMING_UP"
    bad = walk(12, 3, 1)
    bad[4, 1] = np.nan
    assert_invalid(cook(node, bad))
    bad[4, 1] = np.inf
    assert_invalid(cook(node, bad))
    assert_invalid(cook(node, np.ones((10, 7))))  # 7 channels, Dims = 3
    node.set("Dims", 2)
    assert_invalid(cook(node, np.ones((10, 3))))
    node.set("Dims", 3)
    # a window that the Quantile fit cannot handle: PyEyesWeb INVALID_INPUT, no number
    node.set("Algorithm", "quantile")
    x = f32(np.linspace(0, 1, 30)[:, None] * np.array([1.0, 0.5, 0.2]) + np.random.default_rng(5).normal(scale=1e-3, size=(30, 3)))
    value, status = si_expected(x, method="quantile")
    assert status == 3
    assert_invalid(cook(node, x))
    node.set("Algorithm", "constrained")
    assert cook(node, x).status_name == "OK"


# ---- CrossRecurrencePlot --------------------------------------------------------------------------------------------
def series(n, channels, seed):
    return f32(smooth_walk(n, channels, seed=seed))


def cross_py(x, y, **kw):
    n = len(x)
    feature = CrossRecurrencePlot(window=n, **kw)
    result = None
    for a, b in zip(x, y):
        result = feature.process(a, b)
    return result


def test_cross_recurrence_declaration(plugin):
    node = plugin("CrossRecurrencePlot")
    declared(node, "Ewcrossrecurrenceplot", "EW AP Cross Recurrence Plot", 2)
    x = series(9, 2, 1)
    out = node.cook(x, x)
    assert out.names == [f"cross_recurrence_matrix_{i}" for i in range(9)]  # PyEyesWeb: one (window, window) matrix output
    assert (node.get("Epsilon"), node.get("Order")) == (0.5, 2.0)


@pytest.mark.parametrize("pars,kw,n,k,seed", [
    ({}, dict(), 31, 3, 1),
    ({"Epsilon": 1.2, "Order": 1.0}, dict(epsilon=1.2, order=1.0), 27, 2, 2),
    ({"Epsilon": 0.8, "Order": 3.5}, dict(epsilon=0.8, order=3.5), 24, 1, 3),
])
def test_cross_recurrence_parity(plugin, pars, kw, n, k, seed):
    node = plugin("CrossRecurrencePlot")
    for key, value in pars.items():
        node.set(key, value)
    x, y = series(n, k, seed), series(n, k, seed + 10)
    out = node.cook(x, y)
    py = cross_py(x, y, **kw)
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data.T, py.cross_recurrence_matrix)
    assert 0 < out.data.sum() < out.data.size  # recurrences and non-recurrences occur


def test_cross_recurrence_of_a_series_with_itself_is_the_recurrence_plot(plugin):
    """The second-input role of the old Recurrence Plot: CRP(x, x) = RP(x), and RP (one input) is unchanged."""
    rp, crp = plugin("RecurrencePlot"), plugin("CrossRecurrencePlot")
    assert rp.max_inputs == 1 and crp.max_inputs == 2
    x = series(29, 3, 4)
    for pars in ({}, {"Epsilon": 1.1, "Order": 1.0}):
        for key, value in pars.items():
            rp.set(key, value)
            crp.set(key, value)
        single = rp.cook(x)
        assert single.names == [f"recurrence_matrix_{i}" for i in range(29)]
        assert_close(single.data, crp.cook(x, x).data)
        kw = {k.lower(): v for k, v in pars.items()}
        feature = RecurrencePlot(window=29, **kw)
        py = None
        for row in x:
            py = feature.process(row)
        assert_close(single.data.T, py.recurrence_matrix)
        assert single.status_name == "OK"
    assert np.diag(single.data.T).all()  # the diagonal of RP is 1


@pytest.mark.parametrize("order,eps", [(2.0, 0.9), (1.0, 1.3)])
def test_cross_recurrence_different_lengths(plugin, order, eps):
    """N1 != N2: out(i, j) is the pair (x_i, y_j) (PyEyesWeb windows have one length; the core's row-stride bug is fixed)."""
    node = plugin("CrossRecurrencePlot")
    node.set("Epsilon", eps)
    node.set("Order", order)
    x, y = series(14, 2, 5), series(23, 2, 6)
    out = node.cook(x, y)
    assert (out.num_channels, out.num_samples) == (14, 23)
    dist = (np.abs(x[:, None, :] - y[None, :, :]) ** order).sum(axis=2) ** (1 / order)
    expected = (dist < eps).astype(float)
    assert_close(out.data.T, expected)
    out = node.cook(y, x)
    assert_close(out.data.T, expected.T)


def test_cross_recurrence_inclusive_threshold(plugin):
    node = plugin("CrossRecurrencePlot")
    node.set("Epsilon", 1.0)
    x = np.zeros((3, 1))
    y = np.array([[1.0], [0.5], [1.5]])
    assert_close(node.cook(x, y).data.T[0], [1.0, 1.0, 0.0])  # a distance equal to Epsilon is a recurrence (Marwan 2007, eq. 10)


def test_cross_recurrence_edges(plugin):
    node = plugin("CrossRecurrencePlot")
    x = series(10, 2, 1)
    assert_invalid(node.cook(x, series(10, 3, 1)))  # different channel counts
    assert_invalid(node.cook(x))  # second input missing
    for bad in (np.nan, np.inf):
        for which in (0, 1):
            data = [x.copy(), x.copy()]
            data[which][3, 1] = bad
            assert_invalid(node.cook(*data))
    assert node.cook(x, x).status_name == "OK"  # recovers
    assert node.cook(x[:1], x[:1]).data.shape == (1, 1)  # one sample each
    assert node.cook().status_name == "NO_OUTPUT"


# ---- TimeWindowSynchronizer -----------------------------------------------------------------------------------------
def sync_run(chop, py, streams, chunks, rates, names=None):
    """Feed chunk k of every stream to the CHOP and to the PyEyesWeb synchronizer; compare after each cook.
    Returns the list of (CHOP output, number of windows ready)."""
    results = []
    for k in range(len(chunks[0])):
        inputs = [Signal(np.asarray(chunks[i][k], dtype=np.float32), sample_rate=rates[i],
                         names=None if names is None else names[i]) for i in range(len(streams))]
        out = chop.cook(*inputs, sample_rate=rates[0])
        for i in range(len(streams)):
            py.push(i, chunks[i][k])
        window, popped = None, 0
        while py.ready():
            window, popped = py.pop(), popped + 1
        results.append((out, window, popped))
    return results


def split(x, sizes):
    out, i = [], 0
    for size in sizes:
        out.append(x[i:i + size])
        i += size
    return out


def test_time_window_sync_declaration(plugin):
    node = plugin("TimeWindowSynchronizer")
    declared(node, "Ewtimewindowsynchronizer", "EW L1 Time Window Synchronizer", 1, 2)
    out = node.cook(Signal(np.zeros((3, 2)), names=["a", "b"], sample_rate=100.0), Signal(np.zeros((2, 1)), names=["c"], sample_rate=50.0))
    assert out.names == ["in0_a", "in0_b", "in1_c"]
    assert (node.get("Window"), node.get("Starttime")) == (0.04, 0.0)
    assert out.num_samples == 4 and out.sample_rate == 100.0


@pytest.mark.parametrize("sizes", [[3] * 10, [1, 2, 5, 3, 7, 4, 1, 3, 4], [4] * 7])
def test_time_window_sync_one_stream(plugin, sizes):
    node = plugin("TimeWindowSynchronizer")
    x = f32(smooth_walk(sum(sizes), 2, seed=5))
    py = TimeWindowSynchronizer(0.04, [(2, 100.0)])
    ready = 0
    for out, window, popped in sync_run(node, py, [x], [split(x, sizes)], [100.0]):
        if popped == 0:
            assert out.status_name == "NO_OUTPUT" and not out.data.any()
            continue
        ready += 1
        assert out.status_name == "OK" and out.info["windows_popped"] == popped
        assert out.info["window_start"] == pytest.approx(window.start_time)
        assert_close(out.data, window.samples[0])
    assert ready >= 3


def test_time_window_sync_two_streams_different_rates(plugin):
    """100 Hz x 2 channels and 50 Hz x 1 channel, windows of 40 ms: 4 and 2 samples; the short one is zero padded."""
    node = plugin("TimeWindowSynchronizer")
    a = f32(smooth_walk(40, 2, seed=1))
    b = f32(smooth_walk(20, 1, seed=2))
    py = TimeWindowSynchronizer(0.04, [(2, 100.0), (1, 50.0)])
    sizes_a, sizes_b = [3, 5, 2, 6, 4, 8, 3, 9], [1, 3, 1, 3, 2, 4, 1, 5]
    results = sync_run(node, py, [a, b], [split(a, sizes_a), split(b, sizes_b)], [100.0, 50.0])
    seen = 0
    for out, window, popped in results:
        if not popped:
            assert out.status_name == "NO_OUTPUT"
            continue
        seen += 1
        assert out.data.shape == (4, 3)
        assert_close(out.data[:, :2], window.samples[0])
        assert_close(out.data[:2, 2], window.samples[1][:, 0])
        assert not out.data[2:, 2].any()
    assert seen >= 3


def test_time_window_sync_start_time_and_newest_window(plugin):
    node = plugin("TimeWindowSynchronizer")
    node.set("Starttime", 1.5)
    x = f32(smooth_walk(11, 1, seed=3))
    py = TimeWindowSynchronizer(0.04, [(1, 100.0)], start_time=1.5)
    out = node.cook(Signal(x.astype(np.float32), sample_rate=100.0), sample_rate=100.0)
    py.push(0, x)
    first = py.pop()
    second = py.pop()
    assert not py.ready()  # 11 samples: two windows of 4, 3 left
    assert out.info["windows_popped"] == 2  # only the newest is output
    assert_close(out.data, second.samples[0])
    assert out.info["window_start"] == pytest.approx(second.start_time) == pytest.approx(first.start_time + 0.04)
    assert out.info["window_start"] == pytest.approx(1.54)
    # the 3 left open the next window
    out = node.cook(Signal(x[:1].astype(np.float32), sample_rate=100.0), sample_rate=100.0)
    py.push(0, x[:1])
    assert_close(out.data, py.pop().samples[0])


def test_time_window_sync_reset_and_structural_parameters(plugin):
    node = plugin("TimeWindowSynchronizer")
    x = f32(smooth_walk(40, 1, seed=4)).astype(np.float32)
    sig = lambda a: Signal(a, sample_rate=100.0)
    assert node.cook(sig(x[:3])).status_name == "NO_OUTPUT"
    node.pulse("Reset")  # the 3 buffered samples are forgotten
    assert node.cook(sig(x[3:6])).status_name == "NO_OUTPUT"
    assert_close(node.cook(sig(x[6:9])).data[:, 0], x[3:7, 0])
    # structural: a new Window restarts the buffers, a new Start Time too
    node.cook(sig(x[10:13]))
    node.set("Window", 0.05)
    out = node.cook(sig(x[13:17]))
    assert out.status_name == "NO_OUTPUT"  # 4 samples of a window of 5: the 3 of before are gone
    assert_close(node.cook(sig(x[17:18])).data[:, 0], x[13:18, 0])
    node.cook(sig(x[18:21]))
    node.set("Starttime", 2.0)
    assert node.cook(sig(x[21:24])).status_name == "NO_OUTPUT"
    # a change of the input rate or of the channel count is structural too
    node.set("Window", 0.04)
    node.pulse("Reset")
    node.cook(sig(x[:3]))
    out = node.cook(Signal(x[3:7], sample_rate=200.0), sample_rate=100.0)
    assert out.status_name == "NO_OUTPUT"  # 8 samples per window now, the 3 of before are gone
    node.pulse("Reset")
    node.cook(sig(x[:3]))
    out = node.cook(Signal(np.hstack([x[3:5], x[3:5]]), sample_rate=100.0), sample_rate=100.0)
    assert out.status_name == "NO_OUTPUT"  # 2 samples of a window of 4: the 3 of before are gone


def test_time_window_sync_edges(plugin):
    node = plugin("TimeWindowSynchronizer")
    node.set("Window", 0.001)
    assert_invalid(node.cook(Signal(np.ones((4, 1)), sample_rate=100.0)))  # no sample in a window
    node.set("Window", 0.04)
    assert node.cook().status_name == "NO_OUTPUT"
    x = np.arange(4, dtype=np.float32)[:, None]
    x[1, 0] = np.nan  # not data, but the synchronizer does not read the data: copied through
    out = node.cook(Signal(x, sample_rate=100.0))
    assert out.status_name == "OK" and np.isnan(out.data[1, 0]) and out.data[2, 0] == 2
    # a 0 rate input falls back to the default of the base layer (60 Hz): 2 samples per window of 40 ms
    node.pulse("Reset")
    out = node.cook(Signal(np.ones((2, 1)), sample_rate=None), sample_rate=60.0)
    assert out.status_name == "OK" and out.num_samples == 2


def test_recurrence_plot_epsilon_per_sample(plugin):
    node = plugin("RecurrencePlot")
    x = f32(smooth_walk(12, 2, seed=2))
    epsilons = np.linspace(0.2, 1.5, 12)
    node.set("Rowepsilons", " ".join(f"{e:.6f}" for e in epsilons))
    feature = RecurrencePlot(window=12, use_multiple_epsilons=True, multiple_epsilons=[float(f"{e:.6f}") for e in epsilons])
    expected = feature.run(x)[-1].recurrence_matrix
    assert_close(node.cook(x).data.T, expected, what="per-sample epsilons")  # channel i, sample j = entry (i, j)
    node.set("Rowepsilons", "0.5 0.5")  # not one per sample
    assert node.cook(x).status_name == "INVALID_INPUT"
