"""Parity of the analysis-primitive synchronization CHOPs with pyeyesweb.analysis_primitives.synchronization.

CHOP input: (samples, channels). PyEyesWeb windowed features get the same samples one per call with window = number of
samples and the result of the last call is compared. Inputs are cast to float32 first so both sides see the same values.
Matrix outputs: the CHOP writes channel i, sample j = matrix(i, j), so `out.data.T` is the matrix.
"""
import numpy as np
import pytest

from conftest import assert_close
from data import noisy_sine, pulse_train, smooth_walk
from pyeyesweb.analysis_primitives.synchronization import (
    EventSynchronization, EventSynchronizationMECS, GeneralisedAutoCorrelation,
    PartialRecurrenceSynchronization, PhaseLockingValue, RecurrencePlot)
from pyeyesweb.analysis_primitives.synchronization.events import NonlinearInterdependence, SpikeSynchronization  # held back
from pyeyesweb.data_models.results import Status


def f32(x):
    return np.asarray(x, dtype=np.float32).astype(float)


def last(feature, rows):
    """Feed rows (one call each) to a windowed feature; the last Result."""
    result = None
    for row in rows:
        result = feature.process(*row) if isinstance(row, tuple) else feature.process(row)
    return result


def window(feature, *arrays):
    """One full window through the feature's own window entry (what a NaN does to a whole window: a NaN sample given to
    `process` is refused and not buffered, so the window would only warm up)."""
    return feature._process_window(*[np.asarray(a, dtype=float) for a in arrays])


def pairs(x):
    return [tuple(row) for row in x]


def flat(result, names):
    return np.array([np.ravel(getattr(result, n))[0] for n in names], dtype=float)


def declared(node, op_type, label, inputs=1):
    assert (node.op_type, node.op_label, node.num_inputs) == (op_type, label, inputs)
    assert not [i for i in node.setup_issues if i.startswith("error")]


# ---- signals ----------------------------------------------------------------------------------------------------
def series(n, channels, seed):
    return f32(smooth_walk(n, channels, seed=seed))


def trains(n, k, seed, density=0.3):
    return np.stack([pulse_train(n, density=density, seed=seed + i) for i in range(k)], axis=1)


# ---- PartialRecurrenceSynchronization -------------------------------------------------------------------------------
@pytest.mark.parametrize("n,seed", [(4, 1), (6, 2)])
def test_pars(plugin, n, seed):
    node = plugin("PartialRecurrenceSynchronization")
    declared(node, "Ewpartialrecurrencesynchronization", "EW AP Partial Recurrence Synchronization")
    cpr_m = np.corrcoef(f32(series(40, n, seed)), rowvar=False)
    out = node.cook(f32(cpr_m).T)  # channel i = row i of the matrix
    assert out.names == [f"synchronization_matrix_{i}" for i in range(n)]
    expected = PartialRecurrenceSynchronization().process(f32(cpr_m)).synchronization_matrix
    assert_close(out.data.T, expected, rtol=1e-3, atol=1e-4)  # a matrix inverse in float32 input: looser


def test_pars_edges(plugin):
    node = plugin("PartialRecurrenceSynchronization")
    out = node.cook(np.ones((2, 3)))  # 2 samples for 3 channels: not square
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ---- GeneralisedAutoCorrelation ---------------------------------------------------------------------------------
GAC = [
    ({}, dict(), 90, 3, 1),
    ({"Epsilon": 0.5, "Maxlag": 7}, dict(epsilon=0.5, max_lag=7), 71, 2, 2),
]


@pytest.mark.parametrize("pars,kw,n,k,seed", GAC)
def test_generalised_auto_correlation_function(plugin, pars, kw, n, k, seed):
    node = plugin("GeneralisedAutoCorrelation")
    declared(node, "Ewgeneralisedautocorrelation", "EW AP Generalised Auto Correlation")
    for key, value in pars.items():
        node.set(key, value)
    x = series(n, k, seed)
    out = node.cook(x)
    py = last(GeneralisedAutoCorrelation(window=n, **kw), x)
    assert out.names == ["recurrence_rate"]
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data[:, 0], py.recurrence_rate)


def test_generalised_auto_correlation_scalar(plugin):
    from pyeyesweb._core import core
    node = plugin("GeneralisedAutoCorrelation")
    node.set("Outputtype", "scalar")
    node.set("Lag", 3)
    node.set("Epsilon", 0.3)
    x = series(50, 2, 3)
    out = node.cook(x)
    scalar = core.sync.GeneralisedAutoCorrelationOutputType.SCALAR
    py = last(GeneralisedAutoCorrelation(window=50, epsilon=0.3, lag=3, output_type=scalar), x)
    assert out.data.shape == (1, 1)
    assert_close(out.data[:, 0], py.recurrence_rate)


def test_generalised_auto_correlation_short_window(plugin):
    # No clamping (algorithm review): Max Lag must be smaller than the number of samples, in the CHOP and in PyEyesWeb.
    node = plugin("GeneralisedAutoCorrelation")
    x = series(11, 2, 1)
    py = np.ravel(last(GeneralisedAutoCorrelation(window=11), x).recurrence_rate)
    out = node.cook(x)
    assert len(py) == 10 and out.data.shape == (10, 1) and out.status_name == "OK"
    assert_close(out.data[:, 0], py)
    with pytest.raises(ValueError, match="window"):
        GeneralisedAutoCorrelation(window=10)  # max_lag 10 is not smaller than 10 samples
    out = node.cook(series(10, 2, 1))
    assert out.status_name == "INVALID_INPUT" and "maxLag" in out.warning and not out.data.any()


# ---- RecurrencePlot ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pars,kw,n,k,seed", [
    ({}, dict(), 33, 3, 1),
    ({"Epsilon": 1.2, "Order": 1.0}, dict(epsilon=1.2, order=1.0), 27, 2, 2),
])
def test_recurrence_plot(plugin, pars, kw, n, k, seed):
    node = plugin("RecurrencePlot")
    declared(node, "Ewrecurrenceplot", "EW AP Recurrence Plot")
    for key, value in pars.items():
        node.set(key, value)
    x = series(n, k, seed)
    out = node.cook(x)
    py = last(RecurrencePlot(window=n, **kw), x)
    assert out.names == [f"recurrence_matrix_{i}" for i in range(n)]
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data.T, py.recurrence_matrix)


# ---- PhaseLockingValue ------------------------------------------------------------------------------------------
def plv_pair(n, seed):
    a = noisy_sine(n, 60.0, 2.0, 0.3, seed)
    b = noisy_sine(n, 60.0, 2.0, 0.3, seed + 1)
    return f32(np.stack([a, np.roll(b, 3)], axis=1))


@pytest.mark.parametrize("n,seed", [(101, 1), (150, 5)])
def test_plv(plugin, n, seed):
    node = plugin("PhaseLockingValue")
    declared(node, "Ewphaselockingvalue", "EW AP Phase Locking Value")
    x = plv_pair(n, seed)
    out = node.cook(x, sample_rate=60.0)
    py = last(PhaseLockingValue(window=n), [tuple(r) for r in x])
    assert out.names == list(PhaseLockingValue(window=n).outputs.flat_names)
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data[0, 0], py.phase_locking_value)


@pytest.mark.parametrize("low,high,rate", [(0.5, 4.0, 60.0), (1.0, 6.0, 100.0)])
def test_plv_filter(plugin, low, high, rate):
    node = plugin("PhaseLockingValue")
    node.set("Usefilter", 1)
    node.set("Lowfrequency", low)
    node.set("Highfrequency", high)
    n = 181
    x = plv_pair(n, 7)
    out = node.cook(x, sample_rate=rate)
    py = last(PhaseLockingValue(window=n, low_frequency=low, high_frequency=high, sampling_rate=rate), [tuple(r) for r in x])
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data[0, 0], py.phase_locking_value)


def test_plv_edges(plugin):
    node = plugin("PhaseLockingValue")
    out = node.cook(plv_pair(50, 1)[:, :1])
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ---- NonlinearInterdependence ---------------------------------------------------------------------------------
# CHOP defaults (embedding 2, neighbours 5) differ from the PyEyesWeb ones (1, 2): chosen on purpose (B), so the
# parameters are always passed explicitly.
@pytest.mark.parametrize("pars,kw,n,seed", [
    ({}, dict(embedding_dimension=2, neighbours=5), 80, 1),
    ({"Embeddingdim": 3, "Neighbours": 3}, dict(embedding_dimension=3, neighbours=3), 61, 2),
])
def test_interdependence(plugin, pars, kw, n, seed):
    node = plugin("NonlinearInterdependence")
    declared(node, "Ewnonlinearinterdependence", "EW AP Nonlinear Interdependence")
    for key, value in pars.items():
        node.set(key, value)
    x = series(n, 2, seed)
    out = node.cook(x)
    py = last(NonlinearInterdependence(window=n, **kw), [tuple(r) for r in x])
    names = ["first_to_second_interdependence", "second_to_first_interdependence", "threshold"]
    assert out.names == names == list(NonlinearInterdependence(window=n).outputs.flat_names)
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data[0], flat(py, names))


def test_interdependence_edges(plugin):
    node = plugin("NonlinearInterdependence")
    out = node.cook(series(30, 1, 1))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


def test_interdependence_too_short(plugin):
    node = plugin("NonlinearInterdependence")
    x = series(4, 2, 1)  # fewer samples than neighbours + 1
    out = node.cook(x)
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ---- SpikeSynchronization ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("k,n,seed", [(2, 43, 1), (4, 61, 2)])
def test_spike_binary(plugin, k, n, seed):
    node = plugin("SpikeSynchronization")
    declared(node, "Ewspikesynchronization", "EW AP Spike Synchronization")
    ev = trains(n, k, seed, 0.25)
    signed = np.where(ev > 0, 1.0, -1.0)  # the CHOP documents -1 / +1 samples
    out = node.cook(f32(signed))
    py = last(SpikeSynchronization(window=n, number_of_inputs=k), [r for r in ev])
    names = ["degree", "distance"]
    assert out.names == names
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data[0], flat(py, names))


def test_spike_binary_zero_one(plugin):
    node = plugin("SpikeSynchronization")
    ev = trains(50, 3, 4, 0.25)
    py = last(SpikeSynchronization(window=50, number_of_inputs=3), [r for r in ev])
    out = node.cook(f32(ev))
    assert_close(out.data[0], [py.degree, py.distance])


@pytest.mark.parametrize("k", [2, 3])
def test_spike_timings(plugin, k):
    node = plugin("SpikeSynchronization")
    node.set("Mode", "timings")
    rng = np.random.default_rng(k)
    times = f32(np.cumsum(rng.uniform(1, 5, (k, 12)), axis=1))
    out = node.cook(times.T)
    py = SpikeSynchronization(window=12, number_of_inputs=k, mode="timings").process(times)
    assert out.status_name == py.status.name == "OK"
    assert_close(out.data[0], [py.degree, py.distance])


def test_spike_edges(plugin):
    node = plugin("SpikeSynchronization")
    out = node.cook(np.ones((20, 1)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ---- EventSynchronization (the input is the window) --------------------------------------------------------------
# One result per cook for the trains of the input (a Trail CHOP of the events), nothing kept: PyEyesWeb with a window of the
# same samples and reset_every_buffer.
def es_expected(x, **kw):
    feature = EventSynchronization(window=len(x), reset_every_buffer=True, **kw)
    results = [r for r in (feature.process(*row) for row in x) if r.status is Status.OK]
    return [results[-1].synchronization, results[-1].delay]


@pytest.mark.parametrize("pars,kw", [({}, dict()), ({"Maxlag": 3}, dict(max_lag=3)), ({"Maxlag": 8}, dict(max_lag=8))])
@pytest.mark.parametrize("length", [17, 40])
def test_event_sync_window(plugin, pars, kw, length):
    node = plugin("EventSynchronization")
    declared(node, "Eweventsynchronization", "EW AP Event Synchronization")
    for key, value in pars.items():
        node.set(key, value)
    x = trains(160, 2, 3, 0.3)
    for end in range(length, len(x) + 1, 11):                  # a sliding window, as a Trail CHOP gives it
        window = x[end - length:end]
        out = node.cook(f32(window))
        assert out.names == ["synchronization", "delay"] and out.status_name == "OK"
        assert_close(out.data[0], es_expected(window, **kw), what=f"{pars} window ending at {end}")


def test_event_sync_nothing_is_kept_between_cooks(plugin):
    node = plugin("EventSynchronization")
    x = trains(60, 2, 5, 0.3)
    first = node.cook(f32(x[:20])).data.copy()
    node.cook(f32(x[20:40]))
    assert_close(node.cook(f32(x[:20])).data, first)
    names = [p.name for p in node.params]
    assert "Reseteverybuffer" not in names and "Reset" not in names


def test_event_sync_edges(plugin):
    node = plugin("EventSynchronization")
    out = node.cook(np.ones((10, 1)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()
    out = node.cook(np.zeros((10, 2)))
    assert out.status_name == "OK"


# ---- EventSynchronizationMECS ---------------------------------------------------------------------------------------
def mecs_data(n, series_n, classes, seed):
    rng = np.random.default_rng(seed)
    return (rng.random((n, series_n * classes)) > 0.7).astype(float)


@pytest.mark.parametrize("pars,kw,k,c", [
    ({"Numberofinputs": 2, "Numberofeventclasses": 2, "Maxlag": 10}, dict(number_of_inputs=2, number_of_event_classes=2, max_lag=10), 2, 2),
    ({"Numberofinputs": 3, "Numberofeventclasses": 3, "Maxlag": 4, "Kernel": "gaussian"},
     dict(number_of_inputs=3, number_of_event_classes=3, max_lag=4, kernel="gaussian"), 3, 3),
    ({"Numberofinputs": 2, "Numberofeventclasses": 1, "Maxlag": 6, "Kernel": "linear"},
     dict(number_of_inputs=2, number_of_event_classes=1, max_lag=6, kernel="linear"), 2, 1),
])
def test_mecs(plugin, pars, kw, k, c):
    from pyeyesweb._core import core
    node = plugin("EventSynchronizationMECS")
    declared(node, "Eweventsynchronizationmecs", "EW AP Event Synchronization MECS")
    for key, value in pars.items():
        node.set(key, value)
    if "kernel" in kw:
        kw["kernel"] = getattr(core.sync.MECSKernel, kw["kernel"].upper())
    # the input is the window: each one alone, as a fresh PyEyesWeb feature with a window of the same samples
    size = 23
    x = mecs_data(90, k, c, 7)
    for end in range(size, len(x) + 1, 7):                   # a sliding window, as a Trail CHOP gives it
        window = x[end - size:end]
        feature = EventSynchronizationMECS(window=size, **kw)
        res = [feature.process(*[row[s * c:(s + 1) * c] for s in range(k)]) for row in window][-1]
        assert res.status is Status.OK
        out = node.cook(f32(window))
        assert out.names == list(feature.outputs.flat_names)
        assert out.status_name == "OK"
        assert_close(out.data[0], np.concatenate([np.ravel(res.synchronization), np.ravel(res.events)]))


def test_mecs_nothing_is_kept_and_edges(plugin):
    node = plugin("EventSynchronizationMECS")
    node.set("Numberofeventclasses", 2)
    x = f32(mecs_data(60, 2, 2, 9))
    first = node.cook(x[:20]).data.copy()
    node.cook(x[20:40])
    assert_close(node.cook(x[:20]).data, first)
    assert "Reset" not in [p.name for p in node.params]
    out = node.cook(x[:20, :3])  # needs Numseries * Classes = 4 channels
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


# ---- NaN / invalid values in the window ---------------------------------------------------------------------------
# PyEyesWeb: a window with a NaN is INVALID_INPUT with no output (PARS, GeneralisedAutoCorrelation,
# RecurrencePlot, PLV, NonlinearInterdependence); SPIKE timings must be > 0 and strictly
# increasing. The CHOPs check none of this and cook OK.


def _nan(x, r=3, c=0):
    x = x.copy()
    x[r, c] = np.nan
    return x


NAN_CASES = {
    "GeneralisedAutoCorrelation": (lambda x: window(GeneralisedAutoCorrelation(window=20), x.T), 3),
    "RecurrencePlot": (lambda x: window(RecurrencePlot(window=20), x.T), 3),
    "PhaseLockingValue": (lambda x: window(PhaseLockingValue(window=20), x[:, 0], x[:, 1]), 2),
    "NonlinearInterdependence": (lambda x: window(NonlinearInterdependence(window=20, embedding_dimension=2, neighbours=5),
                                                  x[:, 0], x[:, 1]), 2),
}


@pytest.mark.parametrize("name", list(NAN_CASES))
def test_nan_window_is_invalid_input(plugin, name):
    run_py, channels = NAN_CASES[name]
    x = _nan(series(20, channels, 1))
    assert run_py(x).status is Status.INVALID_INPUT
    out = plugin(name).cook(x)
    assert out.status_name == "INVALID_INPUT" and not out.data.any()


def test_nan_pars_is_invalid_input(plugin):
    m = np.eye(3)
    m[0, 1] = np.nan
    assert PartialRecurrenceSynchronization().process(m).status is Status.INVALID_INPUT
    assert plugin("PartialRecurrenceSynchronization").cook(m.astype(np.float32).T).status_name == "INVALID_INPUT"


def test_spike_timings_must_increase(plugin):
    node = plugin("SpikeSynchronization")
    node.set("Mode", "timings")
    bad = np.array([[1.0, 5.0, 9.0], [1.0, 9.0, 5.0]])
    py = SpikeSynchronization(window=3, mode="timings").process(bad)
    assert py.status is Status.INVALID_INPUT
    assert node.cook(bad.T.astype(np.float32)).status_name == "INVALID_INPUT"


def test_event_sync_nan_is_an_event_in_both(plugin):
    # no finite check in either: a NaN sample is a non-zero sample, i.e. an event
    x = _nan(trains(20, 2, 1), 3, 0)
    py = window(EventSynchronization(window=20), x[:, 0], x[:, 1])
    out = plugin("EventSynchronization").cook(x)
    assert py.status is Status.OK and out.status_name == "OK"
    assert_close(out.data[0], [py.synchronization, py.delay])


def test_plv_filter_needs_28_samples(plugin):
    # PyEyesWeb: window >= 28 with a filter (refused at construction); the CHOP reports the core's filtfilt error
    node = plugin("PhaseLockingValue")
    node.set("Usefilter", 1)
    for n in (10, 27):
        out = node.cook(plv_pair(n, 1))
        assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()
        with pytest.raises(ValueError, match="28"):
            PhaseLockingValue(window=n, low_frequency=0.5, high_frequency=4.0, sampling_rate=60.0)
    out = node.cook(plv_pair(28, 1))
    py = last(PhaseLockingValue(window=28, low_frequency=0.5, high_frequency=4.0, sampling_rate=60.0), pairs(plv_pair(28, 1)))
    assert out.status_name == "OK"
    assert_close(out.data[0, 0], py.phase_locking_value)
