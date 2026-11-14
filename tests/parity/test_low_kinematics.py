"""Parity of the low-level kinematics / shape CHOPs with their PyEyesWeb features, on the same float32 data.

Kinematics, KineticEnergy are stream operators (Source = stream | clip, Reset); the others are
frame operators (the whole input is one window or one cloud per sample).
"""
import numpy as np
import pytest

from conftest import Signal, assert_close
from data import skeleton, smooth_walk
from pyeyesweb.low_level import (BoundingBoxFilledArea, DirectionChange, Directness,
                                 EllipsoidSphericity, Equilibrium, Kinematics, KineticEnergy, PointsDensity,
                                 TrajectoryNonPlanarity)


# ---- helpers --------------------------------------------------------------------------------------------------------
def f32(x):
    """The data as TouchDesigner holds it: float32, handed back as float64 so both sides see identical values."""
    return np.asarray(x, dtype=np.float32).astype(np.float64)


def cook(node, data, rate=60.0, **kw):
    return node.cook(Signal(np.asarray(data, dtype=np.float32), sample_rate=rate), sample_rate=rate, **kw)


def table(feature, rec):
    """Recorder -> (rows, flat outputs) in the order of feature.outputs.flat_names."""
    return np.column_stack([np.asarray(rec[name], dtype=float) for name in feature.outputs.flat_names])


def process_rows(feature, rows):
    """feature.process on every row, the flat outputs stacked: (rows, channels); also the statuses."""
    results = [feature.process(row) for row in rows]
    values = [np.atleast_1d(np.concatenate([np.atleast_1d(np.asarray(r.to_flat_dict()[n], dtype=float)) for n in feature.outputs.flat_names]))
              for r in results]
    return np.array(values), np.array([int(r.status) for r in results])


def stream(node, data, chunk, rate=60.0):
    return np.vstack([cook(node, data[i:i + chunk], rate).data for i in range(0, len(data), chunk)])


def stream_status(node, data, chunk, rate=60.0):
    """(output, status of every chunk): the status the Info CHOP shows after each cook."""
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
        assert not out.data.any()


# ---- Kinematics -----------------------------------------------------------------------------------------------------
KIN_TYPES = [("Vel", "velocity"), ("Acc", "acceleration"), ("Jerk", "jerk"), ("Curv", "curvature"), ("Dir", "direction"),
             ("Smooth", "smoothed")]


def kin_setup(node, chop, rate):
    """Set the CHOP parameters of a case and return the matching PyEyesWeb feature."""
    chop = dict(chop)
    types = chop.pop("types", ["velocity", "acceleration"])
    for par, name in KIN_TYPES:
        node.set(par, int(name in types))
    kw = {"output_dims": chop.get("Outputdims", "tangential"), "output_type": [t for _, t in KIN_TYPES if t in types]}
    for par, key in (("Outputdims", None), ("Filterwindowlength", "filter_window_length"), ("Filterpolyorder", "filter_polyorder"),
                     ("Movementthreshold", "movement_threshold")):
        if par in chop:
            node.set(par, chop[par])
            if key:
                kw[key] = chop[par] + (chop[par] % 2 == 0 if par == "Filterwindowlength" else 0)  # the CHOP makes the window odd
    return kw


KIN_CASES = {
    "default": (dict(), 3, 97, 60.0),
    "components_all_types": (dict(Outputdims="components", types=[t for _, t in KIN_TYPES], Filterwindowlength=9, Filterpolyorder=3,
                                  Movementthreshold=0.3), 2, 83, 100.0),
    "tangential_all_types": (dict(types=[t for _, t in KIN_TYPES], Filterwindowlength=21, Filterpolyorder=4), 3, 71, 30.0),
    "even_window": (dict(Filterwindowlength=10, types=["velocity", "curvature"]), 3, 64, 60.0),  # 10 -> 11 in the CHOP
}


def kin_feature(kw, d, rate):
    return Kinematics(dims=d, sampling_rate=rate, **kw)


def test_kinematics_declaration(plugin):
    node = plugin("Kinematics")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewkinematics", "EW L2 Kinematics", 1)
    data = smooth_walk(20, 3)
    for dims in (3, 2):
        for outputdim in ("tangential", "components"):
            node.set("Outputdims", outputdim)
            for par, _ in KIN_TYPES:
                node.set(par, 1)
            out = cook(node, data[:, :dims])
            feature = Kinematics(dims=dims, output_dims=outputdim, output_type=[t for _, t in KIN_TYPES])
            assert out.names == list(feature.outputs.flat_names)
    node.set("Outputdims", "tangential")
    for p, n in KIN_TYPES:  # no type selected: velocity, as the CHOP documents
        node.set(p, 0)
    assert cook(node, data).names == ["velocity"]


@pytest.mark.parametrize("seed", [1, 7])
@pytest.mark.parametrize("case", list(KIN_CASES))
def test_kinematics_parity(plugin, case, seed):
    chop, d, n, rate = KIN_CASES[case]
    node = plugin("Kinematics")
    kw = kin_setup(node, chop, rate)
    data = f32(smooth_walk(n, d, rate=rate, seed=seed))
    expected = table(kin_feature(kw, d, rate), kin_feature(kw, d, rate).run(data))
    out = clip(node, data, rate)
    assert out.status_name == "OK"
    assert out.names == list(kin_feature(kw, d, rate).outputs.flat_names)
    assert_close(out.data, expected, what=case)


def test_kinematics_one_dimension(plugin):
    node = plugin("Kinematics")
    kw = kin_setup(node, dict(types=["velocity", "acceleration", "curvature", "smoothed"]), 60.0)
    data = f32(smooth_walk(50, 1, seed=3))
    feature = Kinematics(dims=1, sampling_rate=60.0, **kw)
    assert_close(clip(node, data).data, table(feature, feature.run(data)))


@pytest.mark.parametrize("chunk", [1, 3, 7])
def test_kinematics_state(plugin, chunk):
    node = plugin("Kinematics")
    kw = kin_setup(node, dict(types=["velocity", "acceleration", "curvature"]), 60.0)
    data = f32(smooth_walk(47, 3, seed=2))
    feature = Kinematics(dims=3, sampling_rate=60.0, **kw)
    expected, _ = process_rows(feature, data)
    assert_close(expected, table(feature, feature.run(data)))  # process sequence == run
    streamed = stream(node, data, chunk)
    assert_close(streamed, expected, what="stream chunks vs process")
    assert_close(clip(node, data).data, expected, what="clip vs process")


def test_kinematics_reset_and_parameters(plugin):
    node = plugin("Kinematics")
    kin_setup(node, dict(types=["velocity", "curvature"]), 60.0)
    data = f32(smooth_walk(40, 3, seed=4))
    first = stream(node, data, 40)
    second = stream(node, data, 40)
    assert not np.allclose(first, second)  # the state continues: the second pass is not a fresh one
    node.pulse("Reset")
    assert_close(stream(node, data, 40), first, what="Reset forgets")
    # LIVE: Threshold keeps the window. Reference: one feature, threshold changed between the halves.
    node.pulse("Reset")
    feature = Kinematics(dims=3, sampling_rate=60.0, output_type=["velocity", "curvature"])
    head = table(feature, feature.run(data[:20]))
    feature.movement_threshold = 0.8
    tail, _ = process_rows(feature, data[20:])
    node.set("Movementthreshold", 0.005)
    a = cook(node, data[:20]).data
    node.set("Movementthreshold", 0.8)
    b = cook(node, data[20:]).data
    assert_close(np.vstack([a, b]), np.vstack([head, tail]), what="live threshold keeps the state")
    # STRUCTURAL: Filterwindow starts the filters afresh: the second half equals a fresh feature on its own.
    node.pulse("Reset")
    cook(node, data[:20])
    node.set("Filterwindowlength", 9)
    b = cook(node, data[20:]).data
    fresh = Kinematics(dims=3, sampling_rate=60.0, output_type=["velocity", "curvature"], filter_window_length=9)
    assert_close(b, table(fresh, fresh.run(data[20:])), what="structural parameter resets")


def test_kinematics_polynomial_too_low_for_jerk(plugin):
    with pytest.raises(ValueError):
        Kinematics(dims=3, output_type="jerk", filter_polyorder=2)
    node = plugin("Kinematics")
    node.set("Jerk", 1)
    node.set("Filterpolyorder", 2)
    assert_invalid(cook(node, smooth_walk(10, 3)))


def test_kinematics_edges(plugin):
    node = plugin("Kinematics")
    kin_setup(node, dict(), 60.0)
    one = cook(node, smooth_walk(1, 3))  # PyEyesWeb: OK from the first sample
    assert one.status_name == "OK" and one.data.shape == (1, 2)
    for channels in (0, 4):  # wrong channel count: INVALID_INPUT, zeros, warning
        node.pulse("Reset")
        if channels:
            assert_invalid(cook(node, smooth_walk(10, 3).repeat(2, axis=1)[:, :channels]))
    node.pulse("Reset")
    assert_invalid(cook(node, smooth_walk(5, 2), timeslice=3))  # not a timeslice: use Clip


@pytest.mark.parametrize("check", ["status", "recovers"])
def test_kinematics_nan(plugin, check):
    node = plugin("Kinematics")
    kw = kin_setup(node, dict(), 60.0)
    data = f32(smooth_walk(30, 3, seed=2))
    bad = data.copy()
    bad[12, 1] = np.nan
    expected, status = process_rows(Kinematics(dims=3, sampling_rate=60.0, **kw), bad)
    assert status[12] == 3
    out, chop_status = stream_status(node, bad, 1)
    if check == "status":
        assert chop_status[12] == 3
    else:
        assert_close(np.delete(out, 12, axis=0), np.delete(expected, 12, axis=0), what="outputs of the valid samples")


# ---- KineticEnergy --------------------------------------------------------------------------------------------------
KE_CASES = {
    "velocity": (dict(Inputmode="velocity"), 3, 4, 59, 60.0),
    "velocity_weight_2d": (dict(Inputmode="velocity", Weight=2.5, Dims=2), 2, 3, 41, 60.0),
    "position": (dict(Inputmode="position", Weight=0.7), 3, 4, 53, 50.0),
}


def ke_feature(chop, joints, rate):
    labels = [str(j) for j in range(joints)]
    weight = chop.get("Weight", 1.0)
    mode = "position" if chop["Inputmode"] == "position" else "velocity"
    return KineticEnergy(labels=labels, weights={l: weight for l in labels}, input_mode=mode, sampling_rate=rate)


def ke_data(d, joints, n, rate, chop):
    """Channel layout j * d + axis; the PyEyesWeb frames (n, joints, 3) with z = 0 for d = 2."""
    data = f32(skeleton(n, joints, d, rate, seed=6))
    frames = np.zeros((n, joints, 3))
    frames[:, :, :d] = data.reshape(n, joints, d)
    return data, frames


def test_kinetic_energy_declaration(plugin):
    node = plugin("KineticEnergy")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewkineticenergy", "EW L2 Kinetic Energy", 1)
    assert cook(node, np.ones((4, 6))).names == list(ke_feature(dict(Inputmode="velocity"), 2, 60.0).outputs.flat_names)


@pytest.mark.parametrize("case", list(KE_CASES))
def test_kinetic_energy_parity(plugin, case):
    chop, d, joints, n, rate = KE_CASES[case]
    node = plugin("KineticEnergy")
    for key, value in chop.items():
        node.set(key, value)
    data, frames = ke_data(d, joints, n, rate, chop)
    feature = ke_feature(chop, joints, rate)
    expected = feature.run(frames).kinetic_energy
    out = clip(node, data, rate)
    assert out.status_name == "OK"
    assert_close(out.data[:, 0], expected, what=case)
    if chop["Inputmode"] == "position":
        assert out.data[0, 0] == 0 and out.data[1:, 0].any()  # the first frame has no previous one


@pytest.mark.parametrize("mode", ["velocity", "position"])
@pytest.mark.parametrize("chunk", [1, 3, 7])
def test_kinetic_energy_state(plugin, mode, chunk):
    chop = dict(Inputmode=mode, Weight=1.3)
    node = plugin("KineticEnergy")
    for key, value in chop.items():
        node.set(key, value)
    data, frames = ke_data(3, 3, 44, 60.0, chop)
    feature = ke_feature(chop, 3, 60.0)
    sequence = np.array([feature.process(frame).kinetic_energy for frame in frames])
    assert_close(stream(node, data, chunk)[:, 0], sequence, what="stream chunks vs process")
    assert_close(clip(node, data).data[:, 0], sequence, what="clip vs process")


def test_kinetic_energy_reset_and_parameters(plugin):
    node = plugin("KineticEnergy")
    node.set("Inputmode", "position")
    data, frames = ke_data(3, 3, 30, 60.0, dict(Inputmode="position"))
    first = stream(node, data, 30)
    assert first[0, 0] == 0
    cont = stream(node, data, 30)
    assert cont[0, 0] > 0  # continues from the last frame of the first pass
    node.pulse("Reset")
    assert_close(stream(node, data, 30), first, what="Reset forgets")
    # LIVE: Weight keeps the previous frame; reference: one feature whose weights change between the halves.
    node.pulse("Reset")
    feature = ke_feature(dict(Inputmode="position"), 3, 60.0)
    head = feature.run(frames[:15]).kinetic_energy
    feature.weights = {str(j): 4.0 for j in range(3)}
    tail = np.array([feature.process(f).kinetic_energy for f in frames[15:]])
    node.set("Weight", 1.0)
    a = cook(node, data[:15]).data[:, 0]
    node.set("Weight", 4.0)
    b = cook(node, data[15:]).data[:, 0]
    assert_close(np.concatenate([a, b]), np.concatenate([head, tail]), what="live weight keeps the state")
    # STRUCTURAL: the Input mode drops the previous frame (the first frame of the second half is 0 again).
    cook(node, data[:3])
    node.set("Inputmode", "velocity")
    cook(node, data[:3])
    node.set("Inputmode", "position")
    assert cook(node, data[15:20]).data[0, 0] == 0


def test_kinetic_energy_weight_is_used_in_positions_mode(plugin):
    """The old CHOP built the positions feature without weights (always 0): Weight must scale the energy."""
    data, _ = ke_data(3, 3, 20, 60.0, {})
    node = plugin("KineticEnergy")
    node.set("Inputmode", "position")
    one = clip(node, data).data
    node.set("Weight", 3.0)
    assert_close(clip(node, data).data, 3.0 * one)
    assert one.any()


def test_kinetic_energy_edges(plugin):
    node = plugin("KineticEnergy")
    assert_invalid(cook(node, np.ones((4, 7))))  # 7 channels, Dims = 3
    assert_invalid(cook(node, np.ones((5, 6)), timeslice=3))
    node.set("Inputmode", "position")
    node.set("Dims", 2)
    assert_invalid(cook(node, np.ones((4, 6))))  # positions need Dims = 3


def test_kinetic_energy_nan_status(plugin):
    node = plugin("KineticEnergy")
    data, _ = ke_data(3, 2, 10, 60.0, {})
    data[4, 2] = np.nan
    assert stream_status(node, data, 1)[1][4] == 3


@pytest.mark.parametrize("mode", [
    "velocity",  # stateless: the valid frames are right
    "position",
])
def test_kinetic_energy_nan_recovers(plugin, mode):
    node = plugin("KineticEnergy")
    node.set("Inputmode", mode)
    data, frames = ke_data(3, 2, 12, 60.0, {})
    bad = data.copy()
    bad[5, 1] = np.nan
    feature = ke_feature(dict(Inputmode=mode), 2, 60.0)
    valid = [feature.process(f).kinetic_energy for i, f in enumerate(frames) if i != 5]
    out = stream(node, bad, 1)[:, 0]
    assert_close(np.delete(out, 5), valid, what="outputs of the valid frames")


# ---- Directness -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n,d,seed", [(37, 3, 1), (101, 2, 9), (2, 3, 4)])
def test_directness_parity(plugin, n, d, seed):
    node = plugin("Directness")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewdirectness", "EW L2 Directness", 1)
    data = f32(smooth_walk(n, d, seed=seed))
    result = Directness().process(data[::-1])  # PyEyesWeb: row 0 is the newest point, the CHOP's newest is the last sample
    out = cook(node, data)
    assert out.names == list(Directness().outputs.flat_names)
    assert out.status_name == "OK"
    assert_close(out.data, [[result.directness_index]])


def test_directness_no_state_and_extra_channels(plugin):
    node = plugin("Directness")
    data = f32(smooth_walk(30, 3, seed=2))
    assert_close(cook(node, data).data, cook(node, data).data)
    wide = np.hstack([data, data])  # channels beyond the third are ignored (x, y, z are the first three)
    assert_close(cook(node, wide).data, cook(node, data).data)


def _nan(a, *index):
    a = np.array(a, dtype=float)
    a[index] = np.nan
    return a


def check_status(node, data, expected):
    """The status name the CHOP shows against the PyEyesWeb status name; INVALID_INPUT comes with a warning."""
    out = cook(node, data)
    assert out.status_name == expected
    assert bool(out.warning) == (expected == "INVALID_INPUT")


def py_status(feature, *args):
    return feature.process(*args).status.name


def test_directness_wrong_channels(plugin):
    assert_invalid(cook(plugin("Directness"), np.ones((5, 1))))


@pytest.mark.parametrize("path", [
    pytest.param(smooth_walk(1, 3), id="one_point"),
    pytest.param(np.ones((6, 3)), id="zero_length"),
    pytest.param(_nan(smooth_walk(10, 3), 4, 0), id="nan"),
])
def test_directness_status(plugin, path):
    path = f32(path)
    check_status(plugin("Directness"), path, py_status(Directness(), path[::-1]))


# ---- DirectionChange ------------------------------------------------------------------------------------------------
DC_CASES = {
    "default": (dict(), 45, 2, 1),
    "epsilon_subsamples": (dict(Epsilon=0.2, Numberofsubsamples=7), 101, 3, 2),
    "short_window": (dict(Epsilon=0.9, Numberofsubsamples=3), 8, 2, 3),
}


def dc_feature(chop, n):
    return DirectionChange(window=n, epsilon=chop.get("Epsilon", 0.5), number_of_subsamples=chop.get("Numberofsubsamples", 20))


@pytest.mark.parametrize("case", list(DC_CASES))
def test_direction_change_parity(plugin, case):
    chop, n, d, seed = DC_CASES[case]
    node = plugin("DirectionChange")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewdirectionchange", "EW L2 Direction Change", 1)
    for key, value in chop.items():
        node.set(key, value)
    data = f32(smooth_walk(n, d, seed=seed))
    feature = dc_feature(chop, n)
    last = feature.run(data)[-1]  # the window holds the whole recording
    assert last.status.name == "OK"
    out = cook(node, data)
    assert out.names == list(feature.outputs.flat_names)
    assert out.status_name == "OK"
    assert_close(out.data, [[last.cosine, last.polygon]], what=case)


def test_direction_change_right_angle(plugin):
    node = plugin("DirectionChange")
    path = np.vstack([np.c_[np.arange(11.0), np.zeros(11)], np.c_[10 * np.ones(10), np.arange(1.0, 11.0)]])
    assert_close(cook(node, path).data, [[1.0, 49.5]], rtol=1e-5)


def test_direction_change_wrong_channels(plugin):
    for channels in (1, 4):
        assert_invalid(cook(plugin("DirectionChange"), np.ones((10, channels))))


@pytest.mark.parametrize("path,expected", [
    pytest.param(smooth_walk(2, 2), "WARMING_UP", id="two_samples"),
    pytest.param(_nan(smooth_walk(10, 2), 3, 1), "INVALID_INPUT", id="nan"),
])
def test_direction_change_status(plugin, path, expected):
    check_status(plugin("DirectionChange"), f32(path), expected)


# ---- TrajectoryNonPlanarity -----------------------------------------------------------------------------------------
NP_CASES = {
    "default": (dict(), dict(), 60, 1),
    "radius": (dict(Radius=0.5), dict(radius=0.5), 83, 2),
    "radius_nan_fraction": (dict(Radius=0.3, Nanfraction=0.2), dict(radius=0.3, nan_fraction=0.2), 45, 3),
}


@pytest.mark.parametrize("order", ["as_given", "reversed"])
@pytest.mark.parametrize("case", list(NP_CASES))
def test_trajectory_non_planarity_parity(plugin, case, order):
    chop, kw, n, seed = NP_CASES[case]
    node = plugin("TrajectoryNonPlanarity")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewtrajectorynonplanarity", "EW L2 Trajectory Non-Planarity", 1)
    for key, value in chop.items():
        node.set(key, value)
    data = f32(smooth_walk(n, 3, seed=seed) * (0.02 if case == "default" else 1.0))  # default radius 0.1: small steps
    feature = TrajectoryNonPlanarity(**kw)
    out = cook(node, data)
    assert out.names == list(feature.outputs.flat_names)
    assert out.status_name == "OK"
    # The CHOP reads the first sample as row 0 (readTrajectory(input, false)); PyEyesWeb documents row 0 as the newest.
    # The feature is compared on the data as given and on the reversed data: the CHOP must agree with one of them
    # and (for a mean distance from local planes) with both.
    given = feature.process(data).to_flat_dict()[feature.outputs.flat_names[0]]
    reverse = feature.process(data[::-1]).to_flat_dict()[feature.outputs.flat_names[0]]
    assert_close(out.data, [[given if order == "as_given" else reverse]], what=case)


def test_trajectory_non_planarity_planar(plugin):
    node = plugin("TrajectoryNonPlanarity")
    t = np.linspace(0, 2 * np.pi, 50)
    circle = f32(np.c_[np.cos(t), np.sin(t), np.zeros(50)])
    node.set("Radius", 2.0)
    assert_close(cook(node, circle).data, [[TrajectoryNonPlanarity(radius=2.0).process(circle).curvature_radius]])


def test_trajectory_non_planarity_wrong_channels(plugin):
    assert_invalid(cook(plugin("TrajectoryNonPlanarity"), np.ones((10, 2))))


@pytest.mark.parametrize("path,expected", [
    pytest.param(smooth_walk(1, 3), "INVALID_INPUT", id="one_point"),
    pytest.param(_nan(smooth_walk(20, 3), 5, 2), "INVALID_INPUT", id="nan"),
    pytest.param(np.c_[np.arange(5.0), np.zeros(5), np.zeros(5)], "INVALID_INPUT", id="no_neighbour"),
])
def test_trajectory_non_planarity_status(plugin, path, expected):
    path = f32(path)
    assert py_status(TrajectoryNonPlanarity(), path) == expected
    check_status(plugin("TrajectoryNonPlanarity"), path, expected)


# ---- Equilibrium ----------------------------------------------------------------------------------------------------
def eq_data(n, seed):
    rng = np.random.default_rng(seed)
    feet = np.tile([-0.15, 0.0, 0.15, 0.02], (n, 1)) + 0.01 * rng.standard_normal((n, 4))
    bary = 0.1 * smooth_walk(n, 2, seed=seed) + [0.0, 0.01]
    return f32(np.hstack([feet, bary]))


EQ_CASES = {"default": (dict(), 33, 1), "margin_yweight": (dict(Margin=0.02, Yweight=2.0), 58, 5)}


@pytest.mark.parametrize("case", list(EQ_CASES))
def test_equilibrium_parity(plugin, case):
    chop, n, seed = EQ_CASES[case]
    node = plugin("Equilibrium")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewequilibrium", "EW L2 Equilibrium", 1)
    for key, value in chop.items():
        node.set(key, value)
    data = eq_data(n, seed)
    feature = Equilibrium(margin=chop.get("Margin", 0.1), y_weight=chop.get("Yweight", 0.5))
    results = [feature.process(r[0:2], r[2:4], r[4:6]) for r in data]
    expected = np.array([[r.equilibrium, r.angle] for r in results])
    out = cook(node, data)
    assert out.names == list(feature.outputs.flat_names)
    assert out.status_name == "OK"
    assert_close(out.data, expected, what=case)
    assert 0 < expected[:, 0].max() <= 1


def test_equilibrium_wrong_channels_and_extras(plugin):
    node = plugin("Equilibrium")
    assert_invalid(cook(node, np.ones((4, 5))))
    extra = np.hstack([eq_data(10, 2), np.ones((10, 2))])  # channels beyond the sixth are ignored
    assert_close(cook(node, extra).data, cook(node, eq_data(10, 2)).data)


def _coincident():
    data = eq_data(6, 3)
    data[:, 2:4] = data[:, 0:2]
    return data


@pytest.mark.parametrize("data", [
    pytest.param(_coincident(), id="feet_coincide"),
    pytest.param(_nan(eq_data(6, 3), 2, 4), id="nan"),
])
def test_equilibrium_status(plugin, data):
    row = next(r for r in data if (r[0:2] == r[2:4]).all() or not np.isfinite(r).all())
    expected = py_status(Equilibrium(), row[0:2], row[2:4], row[4:6])
    assert expected == "INVALID_INPUT"
    check_status(plugin("Equilibrium"), data, expected)


# ---- BoundingBoxFilledArea ------------------------------------------------------------------------------------------
def cloud_data(n, points, seed, scale=1.0):
    rng = np.random.default_rng(seed)
    return f32(scale * rng.standard_normal((n, points * 3)))


@pytest.mark.parametrize("n,points,seed", [(23, 6, 1), (17, 9, 2), (5, 4, 3)])
def test_bounding_box_filled_area_parity(plugin, n, points, seed):
    node = plugin("BoundingBoxFilledArea")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewboundingboxfilledarea", "EW L2 Bounding Box Filled Area", 1)
    data = cloud_data(n, points, seed)
    feature = BoundingBoxFilledArea()
    expected = np.array([feature.process(row.reshape(points, 3)).contraction_index for row in data])
    out = cook(node, data)
    assert out.names == list(feature.outputs.flat_names)
    assert out.status_name == "OK"
    assert_close(out.data[:, 0], expected)


def test_bounding_box_filled_area_epsilon(plugin):
    """Epsilon is a CHOP parameter, PyEyesWeb fixes it at 1e-6 (documented difference): the default agrees, a larger
    one makes a small cloud degenerate (index 0)."""
    node = plugin("BoundingBoxFilledArea")
    data = cloud_data(8, 6, 4, scale=1e-3)  # bounding box area about 1e-5: above 1e-6, below 1e-3
    feature = BoundingBoxFilledArea()
    expected = np.array([feature.process(row.reshape(6, 3)).contraction_index for row in data])
    assert expected.min() > 0
    assert_close(cook(node, data).data[:, 0], expected)
    node.set("Epsilon", 1e-3)
    assert not cook(node, data).data.any()


def test_bounding_box_filled_area_wrong_channels(plugin):
    assert_invalid(cook(plugin("BoundingBoxFilledArea"), np.ones((4, 7))))  # not a multiple of 3


@pytest.mark.parametrize("data,points", [
    pytest.param(np.zeros((3, 9)), 3, id="no_extent"),
    pytest.param(cloud_data(3, 3, 5), 3, id="three_points"),
    pytest.param(_nan(cloud_data(4, 5, 6), 2, 3), 5, id="nan"),
])
def test_bounding_box_filled_area_status(plugin, data, points):
    data = f32(data)
    bad = next(r for r in data if True) if np.isfinite(data).all() else data[2]
    expected = py_status(BoundingBoxFilledArea(), bad.reshape(points, 3))
    assert expected == "INVALID_INPUT"
    check_status(plugin("BoundingBoxFilledArea"), data, expected)


# ---- PointsDensity --------------------------------------------------------------------------------------------------
PD_CASES = {
    "default": (dict(), dict()),
    "median_max_component": (dict(Centroidtype="median", Distancetype="max", Outputdims="components"),
                             dict(centroid_type="median", distance_type="max", output_dims="components")),
    "sum_module": (dict(Distancetype="sum"), dict(distance_type="sum_of_lengths")),
    "median_median": (dict(Centroidtype="median", Distancetype="median"), dict(centroid_type="median", distance_type="median")),
}


@pytest.mark.parametrize("case", list(PD_CASES))
def test_points_density_parity(plugin, case):
    chop, kw = PD_CASES[case]
    node = plugin("PointsDensity")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewpointsdensity", "EW L2 Points Density", 1)
    for key, value in chop.items():
        node.set(key, value)
    data = cloud_data(19, 7, 3)
    feature = PointsDensity(**kw)
    results = [feature.process(row.reshape(7, 3)) for row in data]
    component = chop.get("Outputdims") == "components"
    # Layout on purpose (documented in the source): centroid first, then density; PyEyesWeb's order is density, centroid.
    expected = np.array([np.concatenate([np.atleast_1d(r.centroid), np.atleast_1d(r.density)]) for r in results])
    names = ["centroid_x", "centroid_y", "centroid_z"] + (["density_x", "density_y", "density_z"] if component else ["density"])
    assert sorted(names) == sorted(feature.outputs.flat_names)
    out = cook(node, data)
    assert out.names == names
    assert out.status_name == "OK"
    assert_close(out.data, expected, what=case)


def test_points_density_wrong_channels_and_single_point(plugin):
    node = plugin("PointsDensity")
    assert_invalid(cook(node, np.ones((4, 7))))
    one = cloud_data(4, 1, 2)  # a single point: the centroid is the point
    feature = PointsDensity()
    expected = [np.concatenate([np.atleast_1d(r.centroid), np.atleast_1d(r.density)]) for r in
                (feature.process(row.reshape(1, 3)) for row in one)]
    assert_close(cook(node, one).data, expected)


def test_points_density_nan_status(plugin):
    bad = f32(_nan(cloud_data(4, 5, 6), 2, 3))
    assert py_status(PointsDensity(), bad[2].reshape(5, 3)) == "INVALID_INPUT"
    check_status(plugin("PointsDensity"), bad, "INVALID_INPUT")


# ---- EllipsoidSphericity --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n,points,seed", [(21, 8, 1), (13, 15, 2)])
def test_ellipsoid_sphericity_points(plugin, n, points, seed):
    node = plugin("EllipsoidSphericity")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewellipsoidsphericity", "EW L2 Ellipsoid Sphericity", 1)
    rng = np.random.default_rng(seed)
    data = f32(rng.standard_normal((n, points * 3)) * np.tile([3.0, 1.0, 0.4], points))
    feature = EllipsoidSphericity()
    expected = np.array([feature.process(row.reshape(points, 3)).to_flat_dict() for row in data], dtype=object)
    expected = np.array([[d[name] for name in feature.outputs.flat_names] for d in expected], dtype=float)
    out = cook(node, data)  # default Inputmode = points
    assert out.names == list(feature.outputs.flat_names)
    assert out.status_name == "OK"
    assert_close(out.data, expected)


def test_ellipsoid_sphericity_sizes(plugin):
    node = plugin("EllipsoidSphericity")
    node.set("Inputmode", "sizes")
    sizes = f32(np.random.default_rng(3).uniform(0.5, 4.0, (17, 3)))
    feature = EllipsoidSphericity()
    expected = [feature.process_axes(*row).sphericity for row in sizes]
    out = cook(node, sizes)
    assert out.names == ["sphericity"]  # on purpose: the sizes mode has no axis_ratio / radii (PyEyesWeb: point input only)
    assert out.status_name == "OK"
    assert_close(out.data[:, 0], expected)


def test_ellipsoid_sphericity_wrong_channels(plugin):
    node = plugin("EllipsoidSphericity")
    assert_invalid(cook(node, np.ones((4, 7))))
    node.set("Inputmode", "sizes")
    assert_invalid(cook(node, np.ones((4, 2))))


ES_BAD_SIZES = f32([[1.0, 2.0, 3.0], [1.0, -1.0, 3.0]])
ES_POINTS = {
    "one_point": np.zeros((3, 3)),  # 3 channels = one point per sample
    "coincident_points": np.zeros((2, 12)),
    "nan": np.full((2, 12), np.nan),
}


def test_ellipsoid_sphericity_sizes_status(plugin):
    node = plugin("EllipsoidSphericity")
    node.set("Inputmode", "sizes")
    assert EllipsoidSphericity().process_axes(*ES_BAD_SIZES[1]).status.name == "INVALID_INPUT"
    check_status(node, ES_BAD_SIZES, "INVALID_INPUT")


@pytest.mark.parametrize("case", list(ES_POINTS))
def test_ellipsoid_sphericity_points_status(plugin, case):
    data = ES_POINTS[case]
    assert py_status(EllipsoidSphericity(), data[0].reshape(-1, 3)) == "INVALID_INPUT"
    check_status(plugin("EllipsoidSphericity"), data, "INVALID_INPUT")


def test_kinetic_energy_weights_and_reference_joint(plugin):
    # Per-joint weights and a reference joint, as PyEyesWeb `weights` and `reference_point`.
    chop = dict(Inputmode="position", Weight=1.0)
    data, frames = ke_data(3, 4, 40, 50.0, chop)
    labels = [str(j) for j in range(4)]
    node = plugin("KineticEnergy")
    node.set("Inputmode", "position")
    node.set("Weights", "1 2 0.5 3")
    node.set("Referencepoint", 1)
    feature = KineticEnergy(labels=labels, weights={"0": 1.0, "1": 2.0, "2": 0.5, "3": 3.0}, reference_point="1",
                            input_mode="position", sampling_rate=50.0)
    assert_close(clip(node, data, 50.0).data[:, 0], feature.run(frames).kinetic_energy, what="weights and reference")
    bad = plugin("KineticEnergy")                       # a velocity has no origin
    bad.set("Inputmode", "velocity")
    bad.set("Referencepoint", 0)
    assert clip(bad, data, 50.0).status_name == "INVALID_INPUT"


@pytest.mark.parametrize("metrics", [["cosine"], ["polygon"], ["cosine", "polygon"]])
def test_direction_change_metrics_follow_the_toggles(plugin, metrics):
    node = plugin("DirectionChange")
    node.set("Cosine", int("cosine" in metrics))
    node.set("Polygon", int("polygon" in metrics))
    data = f32(smooth_walk(40, 3, seed=3))
    feature = DirectionChange(window=len(data), metrics=metrics)
    last = feature.run(data)[-1]
    out = cook(node, data)
    assert out.names == list(feature.outputs.flat_names) and out.status_name == "OK"
    assert_close(out.data, [[getattr(last, metric) for metric in metrics]], what=str(metrics))
