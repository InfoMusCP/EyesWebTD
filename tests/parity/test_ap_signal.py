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
# The input is the window (a Trail CHOP of the pulses): one result per cook, nothing kept. PyEyesWeb gives the same number
# for a window of the same samples (window = the length of the input, the result at its last sample).
BPR_SIGNALS = {
    "jitter": lambda: data.pulse_train(137, period=7, jitter=1, seed=3),
    "density": lambda: data.pulse_train(151, density=0.15, seed=9),
    "regular": lambda: data.pulse_train(113, period=6),
}


def bpr_expected(x, threshold):
    f = BinaryPulsesRegularity(window=len(x), threshold=threshold)
    for v in f32(x):
        r = f.process(float(v))
    return np.array([r.is_regular, r.pulse_count], dtype=float)


def test_bpr_declaration(plugin):
    node = plugin("BinaryPulsesRegularity")
    declared(node, "Ewbinarypulsesregularity", "EW AP Binary Pulses Regularity")
    out = node.cook(np.zeros(40))
    assert out.names == list(BinaryPulsesRegularity(window=10).outputs.flat_names)[:2]   # the onset is left to the user
    assert out.data.shape == (1, 2)
    assert "Window" not in [p.name for p in node.params] and "Reset" not in [p.name for p in node.params]


@pytest.mark.parametrize("threshold", [1, 2, 3])
@pytest.mark.parametrize("signal", BPR_SIGNALS)
@pytest.mark.parametrize("length", [25, 30, 40, 100])
def test_bpr_parity(plugin, signal, threshold, length):
    x = BPR_SIGNALS[signal]()
    node = plugin("BinaryPulsesRegularity")
    node.set("Threshold", threshold)
    for end in range(length, len(x) + 1, 9):                    # a sliding window, as a Trail CHOP gives it
        window = x[end - length:end].astype(np.float32)
        out = node.cook(window)
        assert out.status_name == "OK"
        assert_close(out.data[0], bpr_expected(window, threshold), what=f"{signal} {threshold} window ending at {end}")


def test_bpr_nothing_is_kept_between_cooks(plugin):
    x = BPR_SIGNALS["jitter"]().astype(np.float32)
    node = plugin("BinaryPulsesRegularity")
    first = node.cook(x[:60]).data.copy()
    node.cook(x[60:])
    assert_close(node.cook(x[:60]).data, first)


def test_bpr_status_and_edges(plugin):
    node = plugin("BinaryPulsesRegularity")
    out = node.cook(np.ones(2))                                  # too short to be a window
    assert out.status_name == "WARMING_UP" and "Trail CHOP" in out.reason
    assert not out.data.any()
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
# The input is the window (a Trail CHOP): one result per cook, nothing kept. PyEyesWeb gives the same result for a window of
# the same samples (window = the length of the input, the result at its last sample).
PER_PARAMS = [
    dict(),
    dict(Method="small2large", Threshold=0.3),
    dict(Method="mbest", Bestperiods=4),
    dict(Method="mbest", Bestperiods=5, Sortbypower=1),
]
PER_SIGNALS = {
    "pulses": lambda: np.column_stack([np.tile([1.0, 0, 0, 0, 0, 0, 0], 40)[:277], np.tile([2.0, 0, 1.0], 100)[:277]]),
    "noisy": lambda: np.column_stack([data.noisy_sine(251, freq=3.0, noise=0.3, seed=1), data.noisy_sine(251, freq=1.0, noise=0.5, seed=2)]),
}


def per_args(p, window):
    return dict(window=window, method=p.get("Method", "small2large"), threshold=p.get("Threshold", 0.1),
                best_periods=p.get("Bestperiods", 3), sort_by_power=bool(p.get("Sortbypower", 0)))


def per_expected(window_x, p):
    """(periods, powers) of the window, interleaved period<c>, power<c> like the CHOP channels."""
    f = Periodicity(**per_args(p, len(window_x)))
    for row in window_x:
        r = f.process(row)
    assert r.status == Status.OK
    return np.stack([np.stack([r.periods[c], r.powers[c]]) for c in range(window_x.shape[1])]).reshape(-1, r.periods.shape[1])


def test_per_declaration(plugin):
    node = plugin("Periodicity")
    declared(node, "Ewperiodicity", "EW AP Periodicity")
    out = node.cook(np.tile(np.eye(7)[:, :2], (20, 1)))      # 140 samples
    # Layout: period<c>, power<c> per channel; columns are samples: N / 2 + 1 for small2large, M for mbest.
    assert out.names == ["period0", "power0", "period1", "power1"]
    assert out.data.shape == (71, 4)
    names = [p.name for p in node.params]
    assert "Window" not in names and "Hop" not in names and "Reset" not in names
    node.set("Method", "mbest")
    assert node.cook(np.tile(np.eye(7)[:, :1], (2, 1))).data.shape == (3, 2)


@pytest.mark.parametrize("params", PER_PARAMS)
@pytest.mark.parametrize("signal", PER_SIGNALS)
@pytest.mark.parametrize("length", [48, 64, 128])
def test_per_parity(plugin, signal, params, length):
    x = f32(PER_SIGNALS[signal]())
    node = plugin("Periodicity")
    for k, v in params.items():
        node.set(k, v)
    for end in range(length, len(x) + 1, 37):                 # a sliding window, as a Trail CHOP gives it
        window = x[end - length:end]
        out = node.cook(window)
        assert out.status_name == "OK"
        assert_close(out.data, per_expected(window, params).T, what=f"{signal} {params} window ending at {end}")


def test_per_nothing_is_kept_between_cooks(plugin):
    x = f32(PER_SIGNALS["noisy"]())
    node = plugin("Periodicity")
    first = node.cook(x[:64]).data.copy()
    node.cook(x[64:200])
    assert_close(node.cook(x[:64]).data, first)


def test_per_status_and_edges(plugin):
    node = plugin("Periodicity")
    out = node.cook(np.ones((5, 1)))                          # too short to be a window
    assert out.status == WARMING_UP and "Trail CHOP" in out.reason and (out.data == -1).all()
    out = node.cook(np.ones((50, 1)))                         # constant: no period
    assert out.status == INVALID_INPUT and (out.data == -1).all()
    out = node.cook()                                         # no input: -1 everywhere, NO_OUTPUT
    assert out.status == NO_OUTPUT and (out.data == -1).all()


# ==== Rarity (novelty) ===============================================================================================
# The CHOP is PyEyesWeb's Rarity(method="novelty"); the two EyesWeb / PyEyesWeb methods stay in PyEyesWeb. Parameters are in
# seconds in the CHOP and in samples in Python: the host cooks at 60 Hz.
RATE = 60.0


def rarity_x(n, channels, seed):
    """A movement that repeats (a few oscillations of different frequencies) with a little noise, and a change halfway."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / RATE
    cols = [np.sin(2 * np.pi * (1.0 + 0.3 * c) * t) * (1.0 + 0.5 * c) + 0.05 * rng.standard_normal(n) for c in range(channels)]
    x = np.column_stack(cols)
    x[n * 2 // 3:, 0] *= 0.3                                     # a smaller amplitude: new
    return x.astype(np.float32)


def novelty_python(channels, memory_s=5.0, pattern_s=0.5, neighbours=5, shape=False):
    pattern = max(2, round(pattern_s * RATE))
    memory = max(3 * pattern, round(memory_s * RATE))
    return Rarity(method="novelty", number_of_inputs=channels, memory=memory, pattern=pattern, step=max(1, round(pattern / 15.0)),
                  neighbours=neighbours, shape=shape)


def novelty_expected(x, **kw):
    """The rarity of every sample (0 while warming up, as the CHOP gives it)."""
    record = novelty_python(x.shape[1], **kw).run(f32(x))
    return np.nan_to_num(np.asarray(record.rarity, dtype=float))


RARITY_SETS = [
    pytest.param(dict(channels=1), dict(), id="scalar"),
    pytest.param(dict(channels=2), dict(), id="two-channels"),
    pytest.param(dict(channels=2), dict(Compare="shape"), id="shape"),
    pytest.param(dict(channels=1), dict(Neighbours=3, Memory=3.0, Pattern=0.3), id="neighbours3-short"),
]


def configure(node, pars):
    for key, value in pars.items():
        node.set(key, value)


def python_kwargs(pars):
    kw = {}
    if "Compare" in pars:
        kw["shape"] = pars["Compare"] == "shape"
    if "Neighbours" in pars:
        kw["neighbours"] = pars["Neighbours"]
    if "Memory" in pars:
        kw["memory_s"] = pars["Memory"]
    if "Pattern" in pars:
        kw["pattern_s"] = pars["Pattern"]
    return kw


def test_rarity_declaration(plugin):
    node = plugin("Rarity")
    declared(node, "Ewrarity", "EW AP Rarity")
    out = node.cook(rarity_x(20, 3, 1))
    assert out.names == ["rarity"] and out.data.shape == (1, 1)         # one sample per cook, whatever the channels
    names = [p.name for p in node.params]
    assert {"Memory", "Pattern", "Neighbours", "Compare", "Source", "Reset"} <= set(names)
    assert node.param("Memory").default == 5.0 and node.param("Pattern").default == 0.5
    assert node.param("Compare").menu_names == ["values", "shape"]


@pytest.mark.parametrize("size", [1, 2, 7, 1000])
@pytest.mark.parametrize("info, pars", RARITY_SETS)
def test_rarity_parity(plugin, info, pars, size):
    x = rarity_x(900, info["channels"], 3)
    node = plugin("Rarity")
    configure(node, pars)
    expected = novelty_expected(x, **python_kwargs(pars))
    # every sample feeds the memory; the output of a cook is the rarity of its newest sample
    for s, out in zip(slices(len(x), size), cook_chunks(node, x, size)):
        assert out.data.shape == (1, 1)
        assert_close(out.data[0], expected[s.stop - 1:s.stop], what=f"{info} {pars} chunk end {s.stop}")


@pytest.mark.parametrize("info, pars", RARITY_SETS)
def test_rarity_clip_gives_one_value_per_sample(plugin, info, pars):
    x = rarity_x(900, info["channels"], 4)
    node = plugin("Rarity")
    configure(node, pars)
    node.set("Source", "clip")
    out = node.cook(x)
    assert out.data.shape == (900, 1)
    assert_close(out.data[:, 0], novelty_expected(x, **python_kwargs(pars)), what="clip")


def test_rarity_stream_does_not_need_a_timeslice(plugin):
    node = plugin("Rarity")
    x = rarity_x(600, 1, 5)
    out = node.cook(x, timeslice=1)                                  # 600 samples for a slice of 1: fine for this operator
    assert out.status_name == "OK" and out.data.shape == (1, 1)
    assert_close(out.data[0], novelty_expected(x)[-1:])


def test_rarity_warming_up_then_ok(plugin):
    node = plugin("Rarity")
    out = node.cook(rarity_x(20, 1, 6))
    assert out.status == WARMING_UP and not out.data.any()
    out = node.cook(rarity_x(700, 1, 6))                          # 3.5 x Pattern = 105 samples of warm-up are over
    assert out.status_name == "OK" and out.data.any()


def test_rarity_reset_and_structural_parameters_restart_the_memory(plugin):
    x = rarity_x(700, 1, 7)
    node = plugin("Rarity")
    assert node.cook(x).status_name == "OK"
    node.pulse("Reset")
    assert node.cook(x[:20]).status == WARMING_UP
    assert node.cook(x[20:]).status_name == "OK"
    node.set("Compare", "shape")                                      # structural: the memory restarts
    assert node.cook(x[:20]).status == WARMING_UP
    node.cook(x[20:])
    node.set("Neighbours", 3)                                         # live: the memory stays
    assert node.cook(x[:20]).status_name == "OK"


def test_rarity_finds_a_pause_a_new_amplitude_and_a_new_frequency(plugin):
    t = np.arange(20 * 60) / RATE
    steady = (0.5 + 0.5 * np.sin(2 * np.pi * t)).astype(np.float32)
    paused = steady.copy()
    paused[12 * 60:12 * 60 + 30] = 0.5
    faster = steady.copy()
    faster[12 * 60:] = (0.5 + 0.5 * np.sin(2 * np.pi * (12.0 + 2.0 * (t[12 * 60:] - 12.0)))).astype(np.float32)

    def peak(x, start, stop):
        node = plugin("Rarity")
        node.set("Source", "clip")
        return float(node.cook(x[:, None]).data[start * 60:stop * 60, 0].max())

    assert peak(steady, 12, 20) < 1.5
    assert peak(paused, 12, 13) > 3.0 and peak(faster, 12, 13) > 3.0


def test_rarity_wrong_input_is_reported(plugin):
    node = plugin("Rarity")
    out = node.cook()
    assert out.status_name == "NO_OUTPUT"


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
    out = node.cook(data.noisy_sine(60))
    assert out.names == ["sample_entropy"] and out.data.shape == (1, 1)      # one value: SampEn(m, r), m = Embeddingdimension
    node.set("Embeddingdimension", 4)
    assert node.cook(data.noisy_sine(60)).data.shape == (1, 1)


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
    # one value, SampEn(m, r), on both sides (m = Embeddingdimension = embedding_dimension)
    f = SampleEntropy(window=len(x), embedding_dimension=params["Embeddingdimension"], tolerance=params["Tolerance"])
    assert out.status == OK
    assert_close(out.data[0], [f.run(f32(x))[-1].sample_entropy])
    relative = plugin("SampleEntropy")
    relative.set("Embeddingdimension", params["Embeddingdimension"])
    relative.set("Relativetolerance", params["Tolerance"])
    g = SampleEntropy(window=len(x), embedding_dimension=params["Embeddingdimension"], relative_tolerance=params["Tolerance"])
    assert_close(relative.cook(x).data[0], [g.run(f32(x))[-1].sample_entropy])


def test_se_edges(plugin):
    node = plugin("SampleEntropy")
    out = node.cook(np.ones(3))                    # not more than m + 1 = 3 samples
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
    "BinaryPulsesRegularity": (dict(), lambda: _nan(data.pulse_train(40, period=5), 12),
                               lambda: BinaryPulsesRegularity(window=30)),
    "MultiScaleEntropy": (dict(), lambda: _nan(data.noisy_sine(200, noise=0.5), 50), lambda: MultiScaleEntropy(window=200, minimum_points=30)),
    "Periodicity": (dict(), lambda: _nan(data.noisy_sine(60), 50), lambda: Periodicity(window=40, threshold=0.1, best_periods=3)),
    "Rarity": (dict(Memory=0.5, Pattern=0.1), lambda: _nan(rarity_x(30, 2, 1), (5, 0)),
               lambda: Rarity(method="novelty", number_of_inputs=2, memory=30, pattern=6)),
    "SampleEntropy": (dict(), lambda: _nan(data.noisy_sine(60), 20), lambda: SampleEntropy(window=60, embedding_dimension=2, tolerance=0.2)),
    "ScalarPeakDetector": (dict(), lambda: _nan(data.noisy_sine(30), 10), lambda: ScalarPeakDetector()),
}


SAMPLE_WISE = {"Rarity": None, "ScalarPeakDetector": 10}   # Rarity: one sample out


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
    if name == "Periodicity":                                # -1 = no period, its "nothing" value
        assert (out.data == -1).all()
    elif name not in SAMPLE_WISE:
        assert not np.nan_to_num(out.data).any()
    elif SAMPLE_WISE[name] is not None:
        assert not np.nan_to_num(out.data[SAMPLE_WISE[name]]).any()
