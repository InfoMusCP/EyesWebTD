"""Parity of the analysis-primitive signal operators with PyEyesWeb.

BinaryPulsesRegularity, MultiScaleEntropy, Periodicity, Rarity, SampleEntropy, ScalarPeakDetector. Every
comparison feeds PyEyesWeb the float32 values the CHOP receives. PyEyesWeb defaults differ from the CHOP defaults in
several places (Periodicity threshold / best_periods, MSE minimum_points): the tests always pass both sides
explicitly.
"""
import numpy as np
import pytest

import data
from conftest import assert_close

from pyeyesweb.analysis_primitives import (
    BinaryPulsesRegularity, MultiScaleEntropy, Periodicity, Rarity, SampleEntropy,
    ScalarPeakDetector,
)
from pyeyesweb.data_models import Status

OK, WARMING_UP, NO_OUTPUT, INVALID_INPUT = (int(s) for s in (Status.OK, Status.WARMING_UP, Status.NO_OUTPUT, Status.INVALID_INPUT))


# ---- helpers -------------------------------------------------------------------------------------------------------
def f32(x):
    """What the CHOP sees: float32 values, handed to PyEyesWeb as float64."""
    return np.asarray(x, dtype=np.float32).astype(np.float64)


def slices(n, size):
    return [slice(i, min(i + size, n)) for i in range(0, n, size)]


def sample_rows(x):
    return x[:, None] if x.ndim == 1 else x


def drive(feature, x, extract, width, fill=0.0):
    """PyEyesWeb process() sequence of a windowed feature. Returns (held values, statuses): a CHOP keeps its last result
    between two windows, so row i holds the newest OK result up to sample i (`fill` before the first)."""
    feature.reset()
    held, status, cur = [], [], np.full(width, fill, dtype=float)
    for row in x:
        result = feature.process(row)
        status.append(int(result.status))
        if result.status == Status.OK:
            cur = np.asarray(extract(result), dtype=float).reshape(width)
        held.append(cur)
    return np.array(held), np.array(status)


def cook_chunks(node, x, size, **kw):
    """Cook x in timeslices of `size`; returns the list of cooks."""
    return [node.cook(x[s], **kw) for s in slices(len(x), size)]


def declared(node, op_type, label):
    assert (node.op_type, node.op_label) == (op_type, label)
    assert (node.num_inputs, node.min_inputs, node.max_inputs) == (1, 1, 1)
    assert not [i for i in node.setup_issues if i.startswith("error")]


# ==== BinaryPulsesRegularity =========================================================================================
BPR_SIGNALS = {
    "jitter": lambda: data.pulse_train(137, period=7, jitter=1, seed=3),
    "density": lambda: data.pulse_train(151, density=0.15, seed=9),
    "regular": lambda: data.pulse_train(113, period=6),
}
BPR_PARAMS = [dict(Window=30, Hop=1, Threshold=1), dict(Window=40, Hop=5, Threshold=2), dict(Window=25, Hop=7, Threshold=3)]


def bpr_expected(x, p):
    f = BinaryPulsesRegularity(window=p["Window"], hop=p["Hop"], threshold=p["Threshold"])
    return drive(f, f32(x), lambda r: [r.is_regular, r.pulse_count, r.is_regularity_detected], 3)


def test_bpr_declaration(plugin):
    node = plugin("BinaryPulsesRegularity")
    declared(node, "Ewbinarypulsesregularity", "EW AP Binary Pulses Regularity")
    out = node.cook(np.zeros(40))
    assert out.names == list(BinaryPulsesRegularity(window=10).outputs.flat_names)
    assert out.data.shape == (1, 3)


@pytest.mark.parametrize("params", BPR_PARAMS)
@pytest.mark.parametrize("signal", BPR_SIGNALS)
@pytest.mark.parametrize("size", [1, 3, 7, 1000])
def test_bpr_parity(plugin, signal, params, size):
    # One CHOP value per cook (held between windows) against the held PyEyesWeb result at the same sample; chunk
    # lengths 1/3/7 also prove the state is independent of how the input is cut.
    x = BPR_SIGNALS[signal]()
    node = plugin("BinaryPulsesRegularity")
    for k, v in params.items():
        node.set(k, v)
    expected, status = bpr_expected(x, params)
    for s, out in zip(slices(len(x), size), cook_chunks(node, x.astype(np.float32), size)):
        assert_close(out.data[0], expected[s.stop - 1], what=f"{signal} {params} chunk end {s.stop}")
        if size == 1:
            assert out.status == status[s.stop - 1], f"status at sample {s.stop}"


def test_bpr_reset_and_live_threshold(plugin):
    x = BPR_SIGNALS["jitter"]().astype(np.float32)
    node = plugin("BinaryPulsesRegularity")
    first = node.cook(x).data.copy()
    node.pulse("Reset")
    again = node.cook(x).data
    assert_close(again, first, what="after Reset the first answer comes back")
    # Threshold is live: changing it keeps the window.
    node.pulse("Reset")
    node.set("Window", 30)
    node.cook(x[:60])
    node.set("Threshold", 2)
    got = node.cook(x[60:]).data[0]
    f = BinaryPulsesRegularity(window=30, threshold=1)
    held, _ = drive(f, f32(x[:60]), lambda r: [r.is_regular, r.pulse_count, r.is_regularity_detected], 3)
    f.threshold = 2
    cur = held[-1]
    for v in f32(x[60:]):
        r = f.process(v)
        if r.status == Status.OK:
            cur = np.array([r.is_regular, r.pulse_count, r.is_regularity_detected], dtype=float)
    assert_close(got, cur, what="live threshold keeps the window")


@pytest.mark.xfail(strict=True, reason="C: Window change drops the ring buffer (and warms up again); PyEyesWeb keeps the newest samples")
def test_bpr_window_change_keeps_newest_samples(plugin):
    x = BPR_SIGNALS["regular"]().astype(np.float32)
    node = plugin("BinaryPulsesRegularity")
    node.cook(x[:60])
    node.set("Window", 20)
    got = node.cook(x[60:61]).data[0]
    f = BinaryPulsesRegularity(window=30)
    for v in f32(x[:60]):
        f.process(v)
    f.window = 20
    r = f.process(float(x[60]))
    assert r.status == Status.OK
    assert_close(got, [r.is_regular, r.pulse_count, r.is_regularity_detected])


def test_bpr_status_and_edges(plugin):
    node = plugin("BinaryPulsesRegularity")
    out = node.cook(np.ones(10))                   # shorter than Window=30
    assert (out.status, out.status_name) == (WARMING_UP, "WARMING_UP")
    assert not out.data.any()
    # Hop larger than 1: a cook that completes no new window says NO_OUTPUT and keeps the last numbers.
    node = plugin("BinaryPulsesRegularity")
    node.set("Window", 10)
    node.set("Hop", 5)
    node.cook(data.pulse_train(10, period=3))
    held = node.cook(np.zeros(2))
    assert held.status == NO_OUTPUT
    assert node.cook().status == NO_OUTPUT and node.cook().warning == ""


def test_bpr_wrong_channel_count(plugin):
    node = plugin("BinaryPulsesRegularity")
    out = node.cook(np.zeros((40, 2)))
    assert out.status == INVALID_INPUT and out.warning and not out.data.any()


# ==== MultiScaleEntropy ===============================================================================================
MSE_PARAMS = [
    dict(),
    dict(Embeddingdimension=3, Tolerance=0.3, Maxscale=4, Minimumpoints=40),
    dict(Embeddingdimension=1, Tolerance=0.5, Maxscale=3, Minimumpoints=60),
]


def mse_expected(x, p):
    f = MultiScaleEntropy(window=len(x), embedding_dimension=p.get("Embeddingdimension", 2), tolerance=p.get("Tolerance", 0.15),
                          max_scale=p.get("Maxscale", 6), minimum_points=p.get("Minimumpoints", 30))
    r = f.run(f32(x))[-1]
    return r.complexity_index, r.scale_entropies, r.status


def test_mse_declaration(plugin):
    node = plugin("MultiScaleEntropy")
    declared(node, "Ewmultiscaleentropy", "EW AP Multi Scale Entropy")
    out = node.cook(data.noisy_sine(300, noise=0.5).repeat(2).reshape(300, 2))
    # Layout (PyEyesWeb has complexity_index (signals,) and scale_entropies (signals, max_scale)): complexity per
    # channel, then entropy<c>_scale<k>.
    assert out.names == ["complexity0", "complexity1"] + [f"entropy{c}_scale{k}" for c in range(2) for k in range(1, 7)]
    assert out.data.shape == (1, 14)


@pytest.mark.parametrize("params", MSE_PARAMS)
@pytest.mark.parametrize("n,channels", [(257, 1), (361, 2), (300, 3)])
def test_mse_parity(plugin, params, n, channels):
    rng = np.random.default_rng(n)
    x = np.column_stack([data.noisy_sine(n, noise=0.5, seed=s) + 0.3 * rng.standard_normal(n) for s in range(channels)]).astype(np.float32)
    p = dict(params)
    need = p.get("Maxscale", 6) * p.get("Minimumpoints", 30)
    if n < need:
        pytest.skip("PyEyesWeb needs window >= max_scale * minimum_points")
    node = plugin("MultiScaleEntropy")
    for k, v in p.items():
        node.set(k, v)
    ci, se, status = mse_expected(x, p)
    out = node.cook(x)
    assert out.status == OK and status == Status.OK
    scales = p.get("Maxscale", 6)
    assert_close(out.data[0, :channels], ci, what="complexity index")
    assert_close(out.data[0, channels:].reshape(channels, scales), se, what="scale entropies")


def test_mse_unused_scales_are_nan(plugin):
    # 100 samples, Minpoints 30, Maxscale 6: scales 1..3 have >= 30 points, scales 4..6 are NaN (PyEyesWeb cannot
    # build this window/min_points combination, so the used scales are compared with Maxscale 3).
    x = data.noisy_sine(100, noise=0.2).astype(np.float32)  # every used scale has matching templates (fixed tolerance)
    node = plugin("MultiScaleEntropy")
    out = node.cook(x)
    assert out.status == OK
    entropies = out.data[0, 1:]
    assert np.isnan(entropies[3:]).all() and np.isfinite(entropies[:3]).all()
    _, se, _ = mse_expected(x, dict(Maxscale=3))
    assert_close(entropies[:3], se[0])


def test_mse_edges(plugin):
    node = plugin("MultiScaleEntropy")
    out = node.cook(data.noisy_sine(20))           # fewer than Minpoints
    assert out.status == WARMING_UP and not out.data.any()


# ==== Periodicity =====================================================================================================
PER_PARAMS = [
    dict(),
    dict(Method="small2large", Window=48, Hop=7, Threshold=0.3),
    dict(Method="mbest", Window=64, Hop=9, Bestperiods=4),
    dict(Method="mbest", Window=60, Hop=11, Bestperiods=5, Sortbypower=1),
]
PER_SIGNALS = {
    "pulses": lambda: np.column_stack([np.tile([1.0, 0, 0, 0, 0, 0, 0], 40)[:277], np.tile([2.0, 0, 1.0], 100)[:277]]),
    "noisy": lambda: np.column_stack([data.noisy_sine(251, freq=3.0, noise=0.3, seed=1), data.noisy_sine(251, freq=1.0, noise=0.5, seed=2)]),
}


def per_args(p):
    return dict(window=p.get("Window", 128), hop=p.get("Hop", 32), method=p.get("Method", "small2large"),
                threshold=p.get("Threshold", 0.1), best_periods=p.get("Bestperiods", 3), sort_by_power=bool(p.get("Sortbypower", 0)))


def per_expected(x, p):
    """Held (periods, powers) per sample, interleaved period<c>, power<c> like the CHOP channels; cols columns."""
    f = Periodicity(**per_args(p))
    f.reset()
    held, status, cur = [], [], None
    for row in x:
        r = f.process(row)
        status.append(int(r.status))
        if r.status == Status.OK:
            cur = np.stack([np.stack([r.periods[c], r.powers[c]]) for c in range(x.shape[1])]).reshape(-1, r.periods.shape[1])
        held.append(cur)
    return held, np.array(status)


def test_per_declaration(plugin):
    node = plugin("Periodicity")
    declared(node, "Ewperiodicity", "EW AP Periodicity")
    out = node.cook(np.tile(np.eye(7)[:, :2], (20, 1)))
    # Layout: period<c>, power<c> per channel; columns are samples: Window / 2 + 1 for small2large, M for mbest.
    assert out.names == ["period0", "power0", "period1", "power1"]
    assert out.data.shape == (65, 4)
    node.set("Method", "mbest")
    assert node.cook(np.zeros((10, 1))).data.shape == (3, 2)


@pytest.mark.parametrize("params", PER_PARAMS)
@pytest.mark.parametrize("signal", PER_SIGNALS)
@pytest.mark.parametrize("size", [1, 13, 1000])
def test_per_parity(plugin, signal, params, size):
    x = PER_SIGNALS[signal]().astype(np.float32)
    node = plugin("Periodicity")
    for k, v in params.items():
        node.set(k, v)
    expected, status = per_expected(f32(x), params)
    for s, out in zip(slices(len(x), size), cook_chunks(node, x, size)):
        want = expected[s.stop - 1]
        if want is None:                           # before the first window the CHOP holds -1
            assert (out.data == -1).all() and out.status == WARMING_UP
            continue
        assert_close(out.data, want.T, what=f"{signal} {params} chunk end {s.stop}")
        if size == 1:
            assert out.status == status[s.stop - 1]


def test_per_reset(plugin):
    x = PER_SIGNALS["noisy"]().astype(np.float32)
    node = plugin("Periodicity")
    node.set("Window", 64)
    first = node.cook(x).data.copy()
    node.cook(x[:20])
    node.pulse("Reset")
    assert_close(node.cook(x).data, first, what="after Reset the first answer comes back")


def test_per_live_threshold_keeps_window(plugin):
    x = PER_SIGNALS["pulses"]().astype(np.float32)
    node = plugin("Periodicity")
    node.set("Window", 48)
    node.set("Hop", 1)
    node.set("Threshold", 0.1)
    node.cook(x[:100])
    node.set("Threshold", 0.3)
    got = node.cook(x[100:101]).data
    f = Periodicity(**per_args(dict(Window=48, Hop=1, Threshold=0.1)))
    for row in f32(x[:100]):
        f.process(row)
    f.threshold = 0.3
    r = f.process(f32(x[100]))
    assert r.status == Status.OK
    want = np.stack([np.stack([r.periods[c], r.powers[c]]) for c in range(2)]).reshape(-1, r.periods.shape[1])
    assert_close(got, want.T)


@pytest.mark.xfail(strict=True, reason="C: a Window change drops the ring buffer; PyEyesWeb keeps the newest samples")
def test_per_window_change_keeps_newest_samples(plugin):
    x = PER_SIGNALS["pulses"]().astype(np.float32)
    node = plugin("Periodicity")
    node.set("Window", 48)
    node.set("Hop", 1)
    node.cook(x[:100])
    node.set("Window", 32)
    out = node.cook(x[100:101])
    assert out.status == OK


def test_per_status_and_edges(plugin):
    node = plugin("Periodicity")
    out = node.cook(np.ones((50, 1)))              # fewer than Window = 128
    assert out.status == WARMING_UP and (out.data == -1).all()
    # no input: -1 everywhere, NO_OUTPUT
    out = node.cook()
    assert out.status == NO_OUTPUT and (out.data == -1).all()
# ==== Rarity ==========================================================================================================
def rarity_x(n, channels, seed):
    return np.random.default_rng(seed).uniform(0, 0.999, (n, channels)).astype(np.float32)


RARITY_INFO = [
    dict(Measure="rarity", Window=50, channels=2),
    dict(Measure="rarity", Window=12, channels=3),
    dict(Measure="contrast", Window=50, channels=3),
]


def test_rarity_declaration(plugin):
    node = plugin("Rarity")
    declared(node, "Ewrarity", "EW AP Rarity")
    out = node.cook(rarity_x(20, 3, 1))
    assert out.names == list(Rarity(number_of_inputs=3).outputs.flat_names)
    assert out.data.shape == (20, 3)
    node.set("Method", "mode_distance")
    out = node.cook(rarity_x(20, 3, 1))
    assert out.names == ["rarity_0", "rarity_1", "rarity_2"] and out.data.shape == (1, 3)


@pytest.mark.parametrize("params", RARITY_INFO)
@pytest.mark.parametrize("size", [1, 3, 7, 1000])
def test_rarity_information_parity(plugin, params, size):
    x = rarity_x(83, params["channels"], 5)
    node = plugin("Rarity")
    node.set("Measure", params["Measure"])
    node.set("Window", params["Window"])
    f = Rarity(number_of_inputs=params["channels"], measure=params["Measure"], window=params["Window"])
    expected = np.array([f.process(r).rarity for r in f32(x)])
    got = np.vstack([o.data for o in cook_chunks(node, x, size)])
    assert_close(got, expected, what=str(params))


def test_rarity_information_reset(plugin):
    x = rarity_x(60, 2, 6)
    node = plugin("Rarity")
    node.set("Window", 20)
    first = node.cook(x).data.copy()
    assert not np.allclose(node.cook(x).data, first)   # the memory is now full of x
    node.pulse("Reset")
    assert_close(node.cook(x).data, first, what="Reset forgets the memory")


def test_rarity_information_memory_is_structural(plugin):
    x = rarity_x(60, 2, 7)
    node = plugin("Rarity")
    node.set("Window", 20)
    node.cook(x[:30])
    node.set("Window", 10)                         # structural: the memory restarts
    got = node.cook(x[30:]).data
    f = Rarity(number_of_inputs=2, window=10)
    assert_close(got, np.array([f.process(r).rarity for r in f32(x[30:])]))


def test_rarity_information_warming_up(plugin):
    node = plugin("Rarity")
    node.set("Window", 50)
    out = node.cook(rarity_x(10, 2, 1))
    f = Rarity(number_of_inputs=2, window=50)
    assert f.run(f32(rarity_x(10, 2, 1)))[-1].status == Status.WARMING_UP
    assert out.status == WARMING_UP


def test_rarity_information_value_outside_bins(plugin):
    x = rarity_x(60, 2, 2)
    x[-1, 0] = 5.0
    f = Rarity(number_of_inputs=2, window=20)
    assert f.run(f32(x))[-1].status == Status.INVALID_INPUT
    node = plugin("Rarity")
    node.set("Window", 20)
    assert node.cook(x).status == INVALID_INPUT


RARITY_MODE = [dict(Alpha=0.5), dict(Alpha=1.7)]


@pytest.mark.parametrize("params", RARITY_MODE)
@pytest.mark.parametrize("n,channels", [(37, 1), (50, 3), (101, 2)])
def test_rarity_mode_distance_parity(plugin, params, n, channels):
    x = rarity_x(n, channels, n)
    node = plugin("Rarity")
    node.set("Method", "mode_distance")
    node.set("Alpha", params["Alpha"])
    out = node.cook(x)
    expected = [Rarity(method="mode_distance", window=n, alpha=params["Alpha"]).run(f32(x[:, c]))[-1].rarity for c in range(channels)]
    assert out.data.shape == (1, channels)
    assert_close(out.data[0], expected)


def test_rarity_mode_distance_edges(plugin):
    node = plugin("Rarity")
    node.set("Method", "mode_distance")
    out = node.cook(np.ones((1, 2)))
    assert not out.data.any()                      # the core has no value for fewer than 2 samples: 0
    assert out.status == WARMING_UP


def test_rarity_mode_distance_warming_up(plugin):
    assert Rarity(method="mode_distance", window=2).process(1.0).status == Status.WARMING_UP
    node = plugin("Rarity")
    node.set("Method", "mode_distance")
    assert node.cook(np.ones((1, 2))).status == WARMING_UP


# ==== SampleEntropy ===================================================================================================
SE_SIGNALS = {
    "sine": lambda: data.noisy_sine(97, noise=0.1),
    "noise": lambda: data.noisy_sine(131, noise=1.0, seed=8),
}
SE_PARAMS = [dict(Embeddingdimension=2, Tolerance=0.2), dict(Embeddingdimension=3, Tolerance=0.35), dict(Embeddingdimension=1, Tolerance=0.1)]


def test_se_declaration(plugin):
    node = plugin("SampleEntropy")
    declared(node, "Ewsampleentropy", "EW AP Sample Entropy")
    out = node.cook(data.noisy_sine(60))
    assert out.names == list(SampleEntropy(window=60, embedding_dimension=2).outputs.flat_names)
    node.set("Embeddingdimension", 4)
    out = node.cook(data.noisy_sine(60))
    assert out.names == list(SampleEntropy(window=60, embedding_dimension=4).outputs.flat_names) and out.data.shape == (1, 4)


@pytest.mark.parametrize("params", SE_PARAMS)
@pytest.mark.parametrize("signal", SE_SIGNALS)
def test_se_parity(plugin, signal, params):
    # Absolute r (PyEyesWeb `tolerance`) with Useabsolutetolerance, else relative to the standard deviation of the window.
    x = SE_SIGNALS[signal]().astype(np.float32)
    node = plugin("SampleEntropy")
    node.set("Useabsolutetolerance", 1)
    for k, v in params.items():
        node.set(k, v)
    out = node.cook(x)
    f = SampleEntropy(window=len(x), embedding_dimension=params["Embeddingdimension"], tolerance=params["Tolerance"])
    assert out.status == OK
    assert_close(out.data[0], f.run(f32(x))[-1].sample_entropy)
    relative = plugin("SampleEntropy")
    relative.set("Embeddingdimension", params["Embeddingdimension"])
    relative.set("Relativetolerance", params["Tolerance"])
    g = SampleEntropy(window=len(x), embedding_dimension=params["Embeddingdimension"], relative_tolerance=params["Tolerance"])
    assert_close(relative.cook(x).data[0], g.run(f32(x))[-1].sample_entropy)


def test_se_edges(plugin):
    node = plugin("SampleEntropy")
    out = node.cook(np.ones(2))                    # not more than Embeddingdim = 2 samples
    assert out.status == INVALID_INPUT and out.warning and not out.data.any()
    with pytest.raises(ValueError):                # PyEyesWeb refuses the window at construction
        SampleEntropy(window=2, embedding_dimension=2)


def test_se_wrong_channel_count(plugin):
    node = plugin("SampleEntropy")
    out = node.cook(np.random.default_rng(1).standard_normal((50, 2)))
    assert out.status == INVALID_INPUT and not out.data.any()


# ==== ScalarPeakDetector ==============================================================================================
def spd_signal(n=211, seed=4):
    return (data.noisy_sine(n, freq=1.3, noise=0.15, seed=seed) * 0.8).astype(np.float32)


def spd_expected(x, buffer=5, threshold=0.01):
    f = ScalarPeakDetector(window=buffer, threshold=threshold)
    return np.array([float(f.process(v).is_peak) for v in f32(x)])


def test_spd_declaration(plugin):
    node = plugin("ScalarPeakDetector")
    declared(node, "Ewscalarpeakdetector", "EW AP Scalar Peak Detector")
    out = node.cook(spd_signal(20))
    assert out.names == list(ScalarPeakDetector().outputs.flat_names) and out.data.shape == (20, 1)


SPD_PARAMS = [dict(Window=5, Threshold=0.01), dict(Window=9, Threshold=0.3), dict(Window=3, Threshold=0.0)]


@pytest.mark.parametrize("params", SPD_PARAMS)
@pytest.mark.parametrize("seed", [4, 5])
def test_spd_parity_stream_and_clip(plugin, params, seed):
    x = spd_signal(seed=seed)
    expected = spd_expected(x, params["Window"], params["Threshold"])
    assert expected.sum() > 0, "the test signal must contain peaks"
    for size in (1, 3, 7, len(x)):
        node = plugin("ScalarPeakDetector")
        for k, v in params.items():
            node.set(k, v)
        got = np.vstack([o.data for o in cook_chunks(node, x, size)])[:, 0]
        assert_close(got, expected, what=f"stream chunks of {size}")
    node = plugin("ScalarPeakDetector")
    for k, v in params.items():
        node.set(k, v)
    node.set("Source", "clip")
    for _ in range(2):                             # a clip is a fresh state at every cook
        assert_close(node.cook(x).data[:, 0], expected, what="clip")


def test_spd_below_zero_signal(plugin):
    # Peaks of a signal that stays below 0 (the core fix described in PyEyesWeb).
    x = (spd_signal(120) - 3).astype(np.float32)
    node = plugin("ScalarPeakDetector")
    assert_close(node.cook(x).data[:, 0], spd_expected(x))


def test_spd_reset_and_parameters(plugin):
    x = spd_signal(160)
    node = plugin("ScalarPeakDetector")
    first = node.cook(x[:80]).data.copy()
    node.cook(x[80:])
    node.pulse("Reset")
    assert_close(node.cook(x[:80]).data, first, what="Reset forgets the buffer")
    assert node.cook(x[:1]).dat("state_reset") in ("none", "reset pulse")
    # Threshold is live: the buffer is kept.
    node = plugin("ScalarPeakDetector")
    node.cook(x[:80])
    node.set("Threshold", 0.5)
    got = node.cook(x[80:]).data[:, 0]
    f = ScalarPeakDetector(window=5, threshold=0.01)
    for v in f32(x[:80]):
        f.process(v)
    f.threshold = 0.5
    assert_close(got, [float(f.process(v).is_peak) for v in f32(x[80:])], what="live threshold keeps the state")
    # Bufferlen is structural: the state restarts.
    node = plugin("ScalarPeakDetector")
    node.cook(x[:80])
    node.set("Window", 8)
    assert_close(node.cook(x[80:]).data[:, 0], spd_expected(x[80:], 8, 0.01), what="structural change resets")


def test_spd_edges(plugin):
    node = plugin("ScalarPeakDetector")
    out = node.cook(spd_signal(20), timeslice=10)  # not a timeslice
    assert out.status == INVALID_INPUT and "Clip" in out.warning and not out.data.any()


def test_spd_wrong_channel_count(plugin):
    node = plugin("ScalarPeakDetector")
    out = node.cook(np.zeros((20, 2)))
    assert out.status == INVALID_INPUT and out.warning and not out.data.any()


# ==== NaN in the input ================================================================================================
# PyEyesWeb rejects a non-finite sample (INVALID_INPUT, nothing buffered) in every one of these features. A CHOP cook
# must say INVALID_INPUT with a warning and zero output; the operators report OK with numbers instead.
def _nan(x, index):
    x = np.array(x, dtype=np.float32)
    x[index] = np.nan
    return x


NAN_CASES = {
    "BinaryPulsesRegularity": (dict(Window=30), lambda: _nan(data.pulse_train(40, period=5), 12),
                               lambda: BinaryPulsesRegularity(window=30)),
    "MultiScaleEntropy": (dict(), lambda: _nan(data.noisy_sine(200, noise=0.5), 50), lambda: MultiScaleEntropy(window=200, minimum_points=30)),
    "Periodicity": (dict(Window=40, Hop=1), lambda: _nan(data.noisy_sine(60), 50), lambda: Periodicity(window=40, threshold=0.1, best_periods=3)),
    "Rarity": (dict(Window=20), lambda: _nan(rarity_x(30, 2, 1), (5, 0)), lambda: Rarity(number_of_inputs=2, window=20)),
    "SampleEntropy": (dict(), lambda: _nan(data.noisy_sine(60), 20), lambda: SampleEntropy(window=60, embedding_dimension=2, tolerance=0.2)),
    "ScalarPeakDetector": (dict(), lambda: _nan(data.noisy_sine(30), 10), lambda: ScalarPeakDetector()),
}


SAMPLE_WISE = {"BinaryPulsesRegularity": None, "Periodicity": None, "Rarity": 5, "ScalarPeakDetector": 10}


@pytest.mark.parametrize("name", NAN_CASES)
def test_nan_input_is_invalid(plugin, name):
    # Whole-frame operators: INVALID_INPUT and zero output. Sample-wise ones skip the sample (INVALID_INPUT, output 0 at
    # that sample, the sample is not fed) and go on.
    params, make_x, make_feature = NAN_CASES[name]
    x = make_x()
    rec = make_feature().run(f32(x))
    assert (rec.status == INVALID_INPUT).any(), "PyEyesWeb must flag the NaN sample"
    node = plugin(name)
    for k, v in params.items():
        node.set(k, v)
    out = node.cook(x)
    assert out.status == INVALID_INPUT and out.warning
    if name not in SAMPLE_WISE:
        assert not np.nan_to_num(out.data).any()
    elif SAMPLE_WISE[name] is not None:
        assert not np.nan_to_num(out.data[SAMPLE_WISE[name]]).any()


def test_rarity_information_bins(plugin):
    # Bin widths of the `information` method, in the units of the signal (PyEyesWeb `bins`).
    x = 3.0 * rarity_x(83, 2, 5)  # a signal in 0 to 3 needs bins that add up to 3
    node = plugin("Rarity")
    node.set("Window", 20)
    node.set("Bins", "0.5 1 1.5")
    f = Rarity(number_of_inputs=2, window=20, bins=(0.5, 1.0, 1.5))
    expected = np.array([f.process(r).rarity for r in f32(x)])
    got = np.vstack([o.data for o in cook_chunks(node, x, 1000)])
    assert_close(got, expected, what="bins")
