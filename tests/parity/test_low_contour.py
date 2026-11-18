"""Parity of the low-level CHOPs on contours, symmetry and smoothness against PyEyesWeb.

Operators: Symmetry, TriangleSymmetry,
CurvatureVelocityCorrelation, SpectralArcLength, LogDimensionlessJerk, Harmonicity, SubmovementCount.
Both sides see the same float32 values (the input is cast to float32 and back before PyEyesWeb gets it).
"""
import numpy as np
import pytest

import data
from conftest import Signal, assert_close
from pyeyesweb.data_models import Status
from pyeyesweb.low_level import (CurvatureVelocityCorrelation,
                                 LogDimensionlessJerk, SpectralArcLength, SubmovementCount, Symmetry, TriangleSymmetry)
from pyeyesweb.low_level.smoothness import Harmonicity  # held back


def f32(a):
    return np.asarray(a, dtype=np.float32).astype(np.float64)


def blob(n, phase=0.0, seed=0, noise=0.0):
    """A closed star-like contour of n points (x, y), float32 values."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = 10 + 3 * np.cos(5 * t + phase) + 0.3 * np.cos(2 * t) + noise * np.random.default_rng(seed).standard_normal(n)
    return f32(np.column_stack([r * np.cos(t), r * np.sin(t)]))

CONTOURS = [pytest.param(blob(57), id="star57"), pytest.param(blob(83, 0.7, seed=3, noise=0.15), id="noisy83")]


def speed_profile(kind, n):
    """A non-negative speed profile of n samples (float32 values)."""
    if kind == "sine":
        return f32(np.abs(data.noisy_sine(n, freq=1.5, noise=0.05)))
    t = np.arange(n) / 60.0
    rng = np.random.default_rng(8)
    bumps = sum(a * np.exp(-((t - c) ** 2) / (2 * 0.12 ** 2)) for a, c in ((1.0, 0.3), (0.6, 0.7), (0.8, 1.1), (0.3, 1.5)))
    return f32(bumps[:n] + 0.01 * rng.random(n))


def cook(node, x, rate=60.0, **kw):
    return node.cook(Signal(f32(x), sample_rate=rate), **kw)


def declared(node, op_type, label, inputs=1):
    assert (node.op_type, node.op_label) == (op_type, label)
    assert node.min_inputs == node.max_inputs == inputs
    return node


# --- declaration ---------------------------------------------------------------------------------------------------

DECLARATIONS = [
    ("Symmetry", "Ewsymmetry", "EW L2 Symmetry", ["pair_symmetry_0_1"]),
    ("TriangleSymmetry", "Ewtrianglesymmetry", "EW L2 Triangle Symmetry", ["symmetry"]),
    ("CurvatureVelocityCorrelation", "Ewcurvaturevelocitycorrelation", "EW L2 Curvature Velocity Correlation",
     ["smoothness", "curvature", "velocity", "log_curvature_std", "log_speed_std"]),
    ("SpectralArcLength", "Ewspectralarclength", "EW L2 Spectral Arc Length", ["spectral_arc_length"]),
    ("LogDimensionlessJerk", "Ewlogdimensionlessjerk", "EW L2 Log Dimensionless Jerk", ["log_dimensionless_jerk"]),
    ("Harmonicity", "Ewharmonicity", "EW L2 Harmonicity", ["harmonicity"]),
    ("SubmovementCount", "Ewsubmovementcount", "EW L2 Submovement Count", ["submovement_count"]),
]


@pytest.mark.parametrize("name, op_type, label, names", DECLARATIONS, ids=[d[0] for d in DECLARATIONS])
def test_declaration(plugin, name, op_type, label, names):
    node = declared(plugin(name), op_type, label)
    assert not [i for i in node.setup_issues if i.startswith("error")]
    width = {"TriangleSymmetry": 6, "Symmetry": 6, "CurvatureVelocityCorrelation": 3}.get(name, 1)
    rows = 4 if name == "Symmetry" else 40
    out = node.cook(f32(np.random.default_rng(1).random((rows, width))) + 1)
    assert out.names == names


@pytest.mark.parametrize("name, feature, names", [
    ("SpectralArcLength", SpectralArcLength(window=10, sampling_rate=60.0), None),
    ("LogDimensionlessJerk", LogDimensionlessJerk(window=10, sampling_rate=60.0), None),
    ("Harmonicity", Harmonicity(window=10, sampling_rate=60.0), None),
    ("SubmovementCount", SubmovementCount(window=10, sampling_rate=60.0), None),
    ("TriangleSymmetry", TriangleSymmetry(), None),
    ("CurvatureVelocityCorrelation", CurvatureVelocityCorrelation(window=12, sampling_rate=60.0), ["smoothness", "log_curvature_std", "log_speed_std"]),
])
def test_channel_names_are_pyeyesweb_outputs(plugin, name, feature, names):
    """Every output of the fixed-size PyEyesWeb schema is a channel of the CHOP with that name."""
    node = plugin(name)
    width = {"TriangleSymmetry": 6, "CurvatureVelocityCorrelation": 3}.get(name, 1)
    out = cook(node, np.random.default_rng(2).random((20, width)) + 1)
    expected = names if names is not None else list(feature.outputs.flat_names)
    assert set(expected) <= set(out.names)
    if names is None:
        assert out.names == expected


# --- Symmetry ------------------------------------------------------------------------------------------------------

SKELETON = f32(data.skeleton(23, joints=5, dims=3, seed=7))


def skeleton_for(dims):
    return np.hstack([SKELETON[:, j * 3:j * 3 + dims] for j in range(5)])


def symmetry_reference(frames, dims, pairs, center):
    feature = Symmetry(labels=[str(i) for i in range(5)], pairs=pairs, method="reflection",
                       reference_point=None if center < 0 else str(center))
    results = [feature.process(f.reshape(5, dims)) for f in frames]
    return feature, results

SYMMETRY_SETS = [pytest.param(3, "0,1", -1, id="default"),
                 pytest.param(3, "0,1 2,3", -1, id="two-pairs"),
                 pytest.param(2, "0,1 1,4 2,3", 2, id="dims2-center2")]


@pytest.mark.parametrize("dims, pairs, center", SYMMETRY_SETS)
def test_symmetry_parity(plugin, dims, pairs, center):
    node = plugin("Symmetry")
    node.set("Dims", dims)
    node.set("Pairs", pairs)
    node.set("Referencepoint", center)
    frames = skeleton_for(dims)
    out = node.cook(frames)
    pair_list = [tuple(p.split(",")) for p in pairs.split()]
    feature, results = symmetry_reference(frames, dims, pair_list, center)
    names = list(feature.outputs.flat_names)
    assert out.status_name == "OK" and out.data.shape == (len(frames), len(pair_list))
    assert sorted(out.names) == sorted(names)
    for name, column in zip(out.names, out.data.T):  # compared by channel name
        assert_close(column, [r.pair_symmetry[names.index(name)] for r in results], what=name)


@pytest.mark.parametrize("pairs", ["2,3 0,1", "0,1 0,1"])
def test_symmetry_pair_order_and_duplicates(plugin, pairs):
    node = plugin("Symmetry")
    node.set("Pairs", pairs)
    out = node.cook(SKELETON)
    pair_list = sorted({tuple(p.split(",")) for p in pairs.split()})
    feature, results = symmetry_reference(SKELETON, 3, pair_list, -1)
    names = list(feature.outputs.flat_names)
    assert sorted(out.names) == sorted(names) and len(out.names) == len(names)
    for name, column in zip(out.names, out.data.T):
        assert_close(column, [r.pair_symmetry[names.index(name)] for r in results], what=name)


def test_symmetry_edges(plugin):
    node = plugin("Symmetry")
    node.set("Pairs", "0,9")
    out = node.cook(SKELETON)  # joint 9 does not exist
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()
    node.set("Pairs", "0,1")
    node.set("Dims", 2)
    out = node.cook(SKELETON[:, :5])  # 5 channels are not joints of 2 axes
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()
    node.set("Dims", 3)
    node.set("Pairs", "garbage")  # no valid token: the documented fallback is the pair (0, 1)
    out = node.cook(SKELETON)
    assert out.names == ["pair_symmetry_0_1"] and out.status_name == "OK"


def test_symmetry_nan(plugin):
    frames = SKELETON.copy()
    frames[3, 0] = np.nan
    _, results = symmetry_reference(frames[3:4], 3, [("0", "1")], -1)
    assert results[0].status == Status.INVALID_INPUT
    assert plugin("Symmetry").cook(frames).status_name == "INVALID_INPUT"


# --- TriangleSymmetry ----------------------------------------------------------------------------------------------


def triangles(n=20):
    t = f32(data.smooth_walk(n, 6, seed=9))
    t[:, 1] -= 3
    return t


def triangle_reference(t):
    feature = TriangleSymmetry()
    return [feature.process(r[0:2], r[2:4], r[4:6]) for r in t]


def test_triangle_symmetry_parity(plugin):
    t = triangles()
    out = cook(plugin("TriangleSymmetry"), t)
    assert out.status_name == "OK" and out.data.shape == (20, 1)
    assert_close(out.data[:, 0], [r.symmetry for r in triangle_reference(t)])


def test_triangle_symmetry_symmetric_triangle_is_one(plugin):
    t = f32([[0, 0, -2, 3, 2, 3], [1, 1, -1, 4, 3, 4]])
    assert_close(cook(plugin("TriangleSymmetry"), t).data[:, 0], [1.0, 1.0])
    assert_close([r.symmetry for r in triangle_reference(t)], [1.0, 1.0])


def test_triangle_symmetry_wrong_channels(plugin):
    out = cook(plugin("TriangleSymmetry"), triangles()[:, :5])
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


def test_triangle_symmetry_collinear(plugin):
    t = f32([[0, 0, 1, 1, 2, 2.0]] * 3)
    assert triangle_reference(t)[0].status == Status.INVALID_INPUT
    assert cook(plugin("TriangleSymmetry"), t).status_name == "INVALID_INPUT"


def test_triangle_symmetry_nan(plugin):
    t = triangles()
    t[2, 0] = np.nan
    assert triangle_reference(t)[2].status == Status.INVALID_INPUT
    assert cook(plugin("TriangleSymmetry"), t).status_name == "INVALID_INPUT"


# --- speed-profile metrics -----------------------------------------------------------------------------------------


def speed_reference(feature, x):
    """The last window of `run` over the whole profile: PyEyesWeb with window = len(x), hop 1."""
    rec = feature.run(x)
    return rec[feature.outputs.names[0]][-1], rec.status[-1]

SPEED_SIGNALS = [pytest.param("sine", 47, 60.0, id="sine47@60"), pytest.param("bumps", 95, 100.0, id="bumps95@100"),
                 pytest.param("sine", 130, 30.0, id="sine130@30")]

SPEED_METRICS = {
    "SpectralArcLength": [({}, {}), ({"Amplitudethreshold": 0.1, "Minimumcutofffrequency": 3.0, "Maximumcutofffrequency": 10.0},
                                     {"amplitude_threshold": 0.1, "minimum_cutoff_frequency": 3.0, "maximum_cutoff_frequency": 10.0})],
    "LogDimensionlessJerk": [({}, {}), ({"Inputmode": "acceleration"}, {"input_mode": "acceleration"})],
    "Harmonicity": [({}, {})],
    "SubmovementCount": [({}, {}), ({"Prominencefactor": 0.3}, {"prominence_factor": 0.3}), ({"Prominencefactor": 0.0}, {"prominence_factor": 0.0})],
}
FEATURES = {"SpectralArcLength": SpectralArcLength, "LogDimensionlessJerk": LogDimensionlessJerk, "Harmonicity": Harmonicity,
            "SubmovementCount": SubmovementCount}
SPEED_CASES = [pytest.param(name, pars, kwargs, id=f"{name}-{'-'.join(map(str, pars.values())) or 'default'}")
               for name, sets in SPEED_METRICS.items() for pars, kwargs in sets]


@pytest.mark.parametrize("kind, n, rate", SPEED_SIGNALS)
@pytest.mark.parametrize("name, pars, kwargs", SPEED_CASES)
def test_speed_metric_parity(plugin, name, pars, kwargs, kind, n, rate):
    """The CHOP input is one window (the sample rate comes from the input); PyEyesWeb gets window = n, last window."""
    node = plugin(name)
    for k, v in pars.items():
        node.set(k, v)
    x = speed_profile(kind, n)
    out = cook(node, x, rate)
    value, status = speed_reference(FEATURES[name](window=n, sampling_rate=rate, **kwargs), x)
    assert out.data.shape == (1, 1) and out.status_name == Status(status).name
    assert_close(out.data[0, 0], value, what=name)


@pytest.mark.parametrize("name", FEATURES)
def test_speed_metric_short_window_is_warming_up(plugin, name):
    node = plugin(name)
    x = speed_profile("sine", 10)
    for n in (1, 9):
        out = cook(node, x[:n])
        feature = FEATURES[name](window=10, sampling_rate=60.0)
        last = None
        for v in x[:n]:
            last = feature.process(v)
        assert last.status == Status.WARMING_UP and out.status_name == "WARMING_UP"
        assert out.data.shape == (1, 1) and out.data[0, 0] == 0 and f"{n} of 10" in out.reason
    assert cook(node, x).status_name == "OK"  # 10 samples is the smallest window, as in PyEyesWeb


@pytest.mark.parametrize("name", FEATURES)
def test_speed_metric_nan(plugin, name):
    x = speed_profile("sine", 40)
    x[7] = np.nan
    feature = FEATURES[name](window=40, sampling_rate=60.0)  # PyEyesWeb rejects the sample that is NaN, when it arrives
    assert [feature.process(v).status for v in x][7] == Status.INVALID_INPUT
    assert cook(plugin(name), x).status_name == "INVALID_INPUT"


def test_speed_metric_non_finite_result(plugin):
    x = np.zeros(30)
    feature = SpectralArcLength(window=30, sampling_rate=60.0)
    assert [feature.process(v) for v in x][-1].status == Status.INVALID_INPUT
    assert cook(plugin("SpectralArcLength"), x).status_name == "INVALID_INPUT"


def test_speed_metric_extra_channels_ignored(plugin):
    x = speed_profile("sine", 40)
    out = cook(plugin("Harmonicity"), np.column_stack([x, 5 * x]))
    assert_close(out.data, cook(plugin("Harmonicity"), x).data)


# --- CurvatureVelocityCorrelation ----------------------------------------------------------------------------------

CVC_NAMES = ["smoothness", "curvature", "velocity", "log_curvature_std", "log_speed_std"]
# CHOP parameter set -> PyEyesWeb constructor arguments. The defaults are the same except the input kind (CHOP: stream,
# PyEyesWeb: static); every value is passed explicitly on both sides.
CVC_BASE = {"Filterwindowlength": 9, "Filterpolyorder": 3, "Differentiate": 0, "Standarddeviationthreshold": 0.0001, "Upperlimit": 100.0,
            "Correlationtype": "pearson", "Inputkind": "static"}
CVC_SETS = [
    pytest.param(CVC_BASE, id="pearson"),
    pytest.param({**CVC_BASE, "Correlationtype": "simplified"}, id="simplified"),
    pytest.param({**CVC_BASE, "Correlationtype": "simplified", "Upperlimit": 2.0, "Standarddeviationthreshold": 0.5}, id="simplified-capped"),
    pytest.param({**CVC_BASE, "Filterwindowlength": 7, "Filterpolyorder": 4, "Inputkind": "stream"}, id="w7-p4-stream"),
    pytest.param({**CVC_BASE, "Differentiate": 1}, id="differentiate"),
]
CVC_PY = {"pearson": "pearson", "simplified": "simplified"}


def cvc_feature(pars, window, rate):
    return CurvatureVelocityCorrelation(
        window=window, hop=window, sampling_rate=rate, filter_window_length=pars["Filterwindowlength"], filter_polyorder=pars["Filterpolyorder"],
        differentiate=bool(pars["Differentiate"]),
        standard_deviation_threshold=pars["Standarddeviationthreshold"], upper_limit=pars["Upperlimit"],
        correlation_type=CVC_PY[pars["Correlationtype"]], input_kind="dynamic" if pars["Inputkind"] == "stream" else "static")


def cvc_windows(feature, x, size):
    """The Result at the end of each window of `size` samples (hop = window = size: no overlap, filters keep their history)."""
    out = []
    for start in range(0, len(x) - size + 1, size):
        out.append([feature.process(row) for row in x[start:start + size]][-1])
    return out


def cvc_expected(result, size):
    """CHOP layout: five channels, the scalars repeated in every sample; zeros when PyEyesWeb gives no output."""
    out = np.zeros((size, 5))
    if result.status != Status.OK:
        return out
    out[:, 0], out[:, 3], out[:, 4] = result.smoothness, result.log_curvature_std, result.log_speed_std
    out[:, 1], out[:, 2] = result.curvature, result.velocity
    return out


def cvc_node(plugin, pars):
    node = plugin("CurvatureVelocityCorrelation")
    for k, v in pars.items():
        node.set(k, v)
    return node

CVC_SIGNALS = [pytest.param(3, 60.0, 20, id="3d@60-w20"), pytest.param(2, 100.0, 17, id="2d@100-w17"), pytest.param(1, 30.0, 25, id="1d@30-w25")]
@pytest.mark.parametrize("dims, rate, size", CVC_SIGNALS)
@pytest.mark.parametrize("pars", CVC_SETS)
def test_cvc_parity_over_windows(plugin, pars, dims, rate, size):
    """Consecutive windows: the filters keep their history between cooks, as in PyEyesWeb with hop = window."""
    node = cvc_node(plugin, pars)
    x = f32(data.smooth_walk(size * 3 + 4, dims, rate, seed=5 + dims))
    feature = cvc_feature(pars, size, rate)
    for i, result in enumerate(cvc_windows(feature, x, size)):
        out = node.cook(Signal(x[i * size:(i + 1) * size], sample_rate=rate))
        assert out.names == CVC_NAMES and out.data.shape == (size, 5)
        assert out.status_name == Status(result.status).name, f"window {i}"
        assert_close(out.data, cvc_expected(result, size), what=f"window {i}")


def test_cvc_first_window_is_warming_up(plugin):
    """The filters have no history at the first window: no output (zeros), PyEyesWeb says WARMING_UP."""
    node = cvc_node(plugin, CVC_BASE)
    x = f32(data.smooth_walk(20, 3, seed=5))
    out = cook(node, x)
    assert out.status_name == "WARMING_UP" and not out.data.any() and "previous window" in out.reason
    assert cvc_windows(cvc_feature(CVC_BASE, 20, 60.0), x, 20)[0].status == Status.WARMING_UP


@pytest.mark.parametrize("size, status", [(1, "WARMING_UP"), (9, "WARMING_UP"), (10, "WARMING_UP")])
def test_cvc_window_shorter_than_filter_window_plus_one(plugin, size, status):
    """Filterwindow 9 needs 10 samples; below it the output is 0 and the status WarmingUp ("k of N samples")."""
    node = cvc_node(plugin, CVC_BASE)
    x = f32(data.smooth_walk(10, 3, seed=5))[:size]
    out = cook(node, x)
    assert out.status_name == status and out.data.shape == (size, 5)
    if size < 10:
        assert not out.data.any() and f"{size} of 10" in out.reason
    feature = CurvatureVelocityCorrelation(window=10, sampling_rate=60.0, filter_window_length=9)
    assert [feature.process(r) for r in x][-1].status == Status.WARMING_UP


def test_cvc_reset_forgets_the_filter_history(plugin):
    node = cvc_node(plugin, CVC_BASE)
    x = f32(data.smooth_walk(40, 3, seed=5))
    first = cook(node, x[:20])
    second = cook(node, x[20:])
    assert second.status_name == "OK" and first.status_name == "WARMING_UP"
    node.pulse("Reset")
    after = cook(node, x[20:])
    assert after.status_name == "WARMING_UP"
    fresh = cvc_node(plugin, CVC_BASE)
    assert_close(after.data, cook(fresh, x[20:]).data)


def test_cvc_live_parameters_keep_the_history(plugin):
    """Correlationtype, Upperlimit and Stddevthreshold are live in the core: the next window still has its filter history."""
    pars = {**CVC_BASE, "Correlationtype": "simplified"}
    node = cvc_node(plugin, pars)
    x = f32(data.smooth_walk(60, 3, seed=5))
    cook(node, x[:20])
    node.set("Upperlimit", 3.0)
    node.set("Correlationtype", "pearson")
    out = cook(node, x[20:40])
    feature = cvc_feature(pars, 20, 60.0)
    cvc_windows(feature, x[:20], 20)
    feature.upper_limit, feature.correlation_type = 3.0, "pearson"
    expected = cvc_windows(feature, x[20:40], 20)[0]
    assert out.status_name == "OK"
    assert_close(out.data, cvc_expected(expected, 20))


@pytest.mark.parametrize("change", [("Filterpolyorder", 4), ("Filterwindowlength", 7), ("Differentiate", 1)], ids=lambda c: c[0])
def test_cvc_structural_parameter_restarts_the_filters(plugin, change):
    node = cvc_node(plugin, CVC_BASE)
    x = f32(data.smooth_walk(60, 3, seed=5))
    cook(node, x[:20])
    assert cook(node, x[20:40]).status_name == "OK"
    node.set(*change)
    out = cook(node, x[40:])
    assert out.status_name == "WARMING_UP", out.reason


def test_cvc_sample_rate_change_restarts_the_filters(plugin):
    node = cvc_node(plugin, CVC_BASE)
    x = f32(data.smooth_walk(60, 3, seed=5))
    cook(node, x[:20], 60.0)
    assert cook(node, x[20:40], 60.0).status_name == "OK"
    out = cook(node, x[40:], 100.0)
    expected = cvc_windows(cvc_feature(CVC_BASE, 20, 100.0), x[40:], 20)[0]
    assert expected.status == Status.WARMING_UP and out.status_name == "WARMING_UP"
    assert_close(out.data[:, 1:3], cvc_expected(expected, 20)[:, 1:3])


def test_cvc_channel_count_change_restarts(plugin):
    """A new number of channels is a new shape: the first window of it is WarmingUp (Inputkind stream = PyEyesWeb dynamic)."""
    pars = {**CVC_BASE, "Inputkind": "stream"}
    node = cvc_node(plugin, pars)
    x = f32(data.smooth_walk(60, 3, seed=5))
    cook(node, x[:20])
    assert cook(node, x[20:40]).status_name == "OK"
    out = cook(node, x[40:, :2])
    assert out.status_name == "WARMING_UP"
    assert cvc_windows(cvc_feature(pars, 20, 60.0), x[40:, :2], 20)[0].status == Status.WARMING_UP  # a fresh feature: no history


def test_cvc_wrong_channel_count(plugin):
    node = cvc_node(plugin, CVC_BASE)
    out = cook(node, np.random.default_rng(1).random((30, 4)))
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()


def test_cvc_nan(plugin):
    x = f32(data.smooth_walk(20, 3, seed=5))
    x[4, 1] = np.nan
    feature = cvc_feature(CVC_BASE, 20, 60.0)  # PyEyesWeb rejects the sample that is NaN, when it arrives
    assert [feature.process(row).status for row in x][4] == Status.INVALID_INPUT
    assert cook(cvc_node(plugin, CVC_BASE), x).status_name == "INVALID_INPUT"


TRIANGLE_METHODS = [("area", "symmetry"), ("horizontal", "horizontal_asymmetry"), ("vertical", "vertical_asymmetry"),
                    ("spatial", "spatial_asymmetry")]


@pytest.mark.parametrize("method, name", TRIANGLE_METHODS, ids=[m for m, _ in TRIANGLE_METHODS])
def test_triangle_symmetry_method_parity(plugin, method, name):
    t = triangles()
    node = plugin("TriangleSymmetry")
    node.set("Method", method)
    out = cook(node, t)
    feature = TriangleSymmetry(method=method)
    reference = [feature.process(r[0:2], r[2:4], r[4:6]) for r in t]
    assert out.names == [name] == list(feature.outputs.flat_names)
    assert out.status_name == "OK" and all(r.ok for r in reference)
    assert_close(out.data[:, 0], [getattr(r, name) for r in reference])


@pytest.mark.parametrize("method, row, reason", [
    ("horizontal", [2, 0, 2, 1, 2, 3], "all vertices on one vertical line"),
    ("spatial", [2, 0, 2, 1, 2, 3], "all vertices on one vertical line"),
    ("spatial", [0, 0, -1, 1, 3, 1], "the two lower vertices at the same height")])
def test_triangle_symmetry_method_undefined(plugin, method, row, reason):
    t = f32([row] * 3)
    result = TriangleSymmetry(method=method).process(t[0, 0:2], t[0, 2:4], t[0, 4:6])
    assert result.status == Status.INVALID_INPUT and result.reason == reason
    node = plugin("TriangleSymmetry")
    node.set("Method", method)
    out = cook(node, t)
    assert out.status_name == "INVALID_INPUT" and reason in out.reason and not out.data.any()


@pytest.mark.parametrize("aggregation", ["mean", "min", "max", "weighted_mean"])
@pytest.mark.parametrize("index_type", ["symmetry", "symmetry_asymmetry"])
@pytest.mark.parametrize("components", [False, True])
@pytest.mark.parametrize("normalize", [True, False])
def test_symmetry_ratio_method_parity(plugin, aggregation, index_type, components, normalize):
    node = plugin("Symmetry")
    node.set("Method", "ratio")
    node.set("Pairs", "0,1 2,3")
    node.set("Referencepoint", 4)
    node.set("Aggregation", aggregation)
    node.set("Indextype", index_type)
    node.set("Components", int(components))
    node.set("Normalizeskeleton", int(normalize))
    feature = Symmetry(labels=[str(i) for i in range(5)], pairs=[("0", "1"), ("2", "3")], method="ratio", reference_point="4",
                       aggregation=aggregation, index_type=index_type, output_dims="components" if components else "global",
                       normalize_skeleton=normalize)
    out = node.cook(SKELETON)
    assert out.names == list(feature.outputs.flat_names) and out.status_name == "OK"
    expected = np.array([feature.process(frame.reshape(5, 3)).to_array() for frame in SKELETON])
    assert_close(out.data, expected.reshape(len(SKELETON), -1), what="ratio")
