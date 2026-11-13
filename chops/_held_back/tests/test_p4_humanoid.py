"""Parity of the humanoid CHOPs (Humanoid Simulator, Humanoid Orientations) with their PyEyesWeb features, on the same
float32 data.

Both are stream operators (Source = stream | clip, Reset) fed one 21-joint skeleton per sample: 63 channels, joint-major,
in the order of HUMANOID_JOINTS (alphabetical). Differences from PyEyesWeb, all documented in the operators:
  * the time step of the simulator is 1 / (sample rate of the input) (PyEyesWeb: sampling_rate, same number here);
  * labels / joint_map are not exposed: the channel order is the mapping;
  * Integrationstep is limited to 1e-5 s or more (PyEyesWeb: any positive number).
MassSpringModel is exported by PyEyesWeb but is a data type of the GenericModel* features (not a catalog feature): no CHOP.
"""
import numpy as np
import pytest

from conftest import Signal, assert_close
from data import smooth_walk
from pyeyesweb.physical_signals import HUMANOID_BONES, HUMANOID_JOINTS, HumanoidOrientations, HumanoidSimulator

NJ, NB = len(HUMANOID_JOINTS), len(HUMANOID_BONES)
TPOSE = HumanoidSimulator().process({"head": (0.0, 0.0, 0.0)}).joints  # (21, 3) in metres


# ---- helpers --------------------------------------------------------------------------------------------------------
def f32(x):
    return np.asarray(x, dtype=np.float32).astype(np.float64)


def body(n, seed=1, rate=60.0, amplitude=0.05, scale=1.0):
    """(n, 63) a skeleton that sways around the T-pose, joint-major in the order of HUMANOID_JOINTS (float32 values)."""
    out = np.empty((n, NJ, 3))
    for j in range(NJ):
        out[:, j] = TPOSE[j] + amplitude * smooth_walk(n, 3, rate=rate, seed=seed + 7 * j)
    return f32(scale * out.reshape(n, NJ * 3))


def cook(node, *data, rate=60.0, **kw):
    inputs = [None if d is None else Signal(np.asarray(d, dtype=np.float32), sample_rate=rate) for d in data]
    return node.cook(*inputs, sample_rate=rate, **kw)


def stream(node, data, chunk, rate=60.0):
    return np.vstack([cook(node, data[i:i + chunk], rate=rate).data for i in range(0, len(data), chunk)])


def clip(node, *data, rate=60.0):
    node.set("Source", "clip")
    out = cook(node, *data, rate=rate)
    node.set("Source", "stream")
    return out


def run(feature, rows, field, **kw):
    """feature.process on every row (63 values -> (21, 3)); the flat output (rows, channels) and the statuses."""
    results = [feature.process(np.asarray(row).reshape(NJ, 3), **kw) for row in rows]
    return (np.array([np.asarray(getattr(r, field), dtype=float).reshape(-1) for r in results]),
            np.array([int(r.status) for r in results]))


def assert_invalid(out, zero=True):
    assert out.status_name == "INVALID_INPUT" and out.status == 3
    assert out.warning
    if zero:
        assert not out.data.any()


# ---- Humanoid Orientations ------------------------------------------------------------------------------------------
def test_orientations_declaration(plugin):
    node = plugin("HumanoidOrientations")
    assert (node.op_type, node.op_label, node.num_inputs) == ("Ewhumanoidorientations", "EW L1 Humanoid Orientations", 1)
    assert node.max_inputs == 1
    out = cook(node, body(3))
    assert out.names == list(HumanoidOrientations().outputs.flat_names)
    assert out.data.shape == (3, 3 * NB)
    assert [p.name for p in node.params if p.page == "Humanoid Orientations"] == ["Refdir"]


@pytest.mark.parametrize("seed", [1, 5])
@pytest.mark.parametrize("refdir", [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.3, -0.5, 0.8)])
def test_orientations_parity(plugin, refdir, seed):
    node = plugin("HumanoidOrientations")
    for par, value in zip(("Refdirx", "Refdiry", "Refdirz"), refdir):
        node.set(par, value)
    data = body(40, seed=seed, amplitude=0.15)
    expected, _ = run(HumanoidOrientations(reference_direction=refdir), data, "directions")
    out = clip(node, data)
    assert out.status_name == "OK"
    assert_close(out.data, expected, what="orientations")


@pytest.mark.parametrize("chunk", [1, 3, 7])
def test_orientations_state(plugin, chunk):
    """Dropouts make the state matter: a joint that is missing keeps its previous position."""
    node = plugin("HumanoidOrientations")
    data = body(31, seed=2, amplitude=0.15)
    data[10:14, 3 * 4:3 * 4 + 3] = np.nan  # left_hand missing
    data[20, 3 * 9 + 1] = np.nan           # one component of neck: the joint is missing
    feature = HumanoidOrientations()
    expected, status = run(feature, data, "directions")
    assert (status == 0).all()
    assert_close(stream(node, data, chunk), expected, what="stream chunks vs process")
    assert_close(clip(node, data).data, expected, what="clip vs process")


def test_orientations_reset_and_structural_parameter(plugin):
    node = plugin("HumanoidOrientations")
    data = body(20, seed=3, amplitude=0.15)
    data[:, 3 * 4:3 * 4 + 3] = np.where(np.arange(20)[:, None] < 10, np.nan, data[:, 3 * 4:3 * 4 + 3])  # missing, then seen
    first = stream(node, data[:12], 12)
    cook(node, data[12:])
    node.pulse("Reset")
    assert_close(stream(node, data[:12], 12), first, what="Reset forgets")
    # STRUCTURAL: Refdir starts the state afresh; the second half equals a fresh feature on its own.
    node.pulse("Reset")
    cook(node, data[:10])
    node.set("Refdiry", 1.0)
    node.set("Refdirx", 0.0)
    tail = cook(node, data[10:]).data
    fresh, _ = run(HumanoidOrientations(reference_direction=(0.0, 1.0, 0.0)), data[10:], "directions")
    assert_close(tail, fresh, what="structural parameter resets")


def test_orientations_edges(plugin):
    node = plugin("HumanoidOrientations")
    one = cook(node, body(1))
    assert one.status_name == "OK" and one.data.shape == (1, 3 * NB)  # no warm-up
    for channels in (0, 1, 62, 64, 66):
        node.pulse("Reset")
        data = np.zeros((4, max(channels, 1)))
        if channels:
            assert_invalid(cook(node, data))
    node.pulse("Reset")
    good = body(5)
    inf = good.copy()
    inf[2, 7] = np.inf
    out = cook(node, inf)
    assert out.status_name == "INVALID_INPUT" and out.warning
    assert not out.data[2].any() and out.data[[0, 1, 3, 4]].any(axis=1).all()  # only the bad sample is zero
    allnan = good.copy()
    allnan[3] = np.nan
    node.pulse("Reset")
    out = cook(node, allnan)
    assert out.status_name == "INVALID_INPUT" and not out.data[3].any()
    # the invalid sample is not fed: the state goes on as if it had not been there (PyEyesWeb returns no output for it)
    feature = HumanoidOrientations()
    kept = np.delete(allnan, 3, axis=0)
    expected, _ = run(feature, kept, "directions")
    assert_close(np.delete(out.data, 3, axis=0), expected)
    assert HumanoidOrientations().process(np.full((NJ, 3), np.nan)).status.name == "INVALID_INPUT"
    assert HumanoidOrientations().process(inf[2].reshape(NJ, 3)).status.name == "INVALID_INPUT"
    node.pulse("Reset")
    assert_invalid(cook(node, body(5), timeslice=3))  # not a timeslice: use Clip
    node.pulse("Reset")
    zero_ref = plugin("HumanoidOrientations")
    for par in ("Refdirx", "Refdiry", "Refdirz"):
        zero_ref.set(par, 0.0)
    zero_data = body(3, amplitude=0.15)  # PyEyesWeb accepts a zero reference direction (the core does not throw): same numbers
    expected, _ = run(HumanoidOrientations(reference_direction=(0.0, 0.0, 0.0)), zero_data, "directions")
    assert_close(cook(zero_ref, zero_data).data, expected)
    degenerate = cook(plugin("HumanoidOrientations"), np.zeros((3, 63)))  # all joints on one point: zero-length bones
    assert degenerate.status_name == "OK" and not degenerate.data.any()


# ---- Humanoid Simulator ---------------------------------------------------------------------------------------------
# CHOP parameter -> PyEyesWeb keyword (values are in the Units of the case)
SIM_CASES = {
    "default": (dict(), dict(), 60.0, 1.0),
    "millimetres_gravity_floor": (dict(Units="mm", Gravityy=-9810.0, Groundinteraction=1, Floory=-5.0, Damping=3.0),
                                  dict(units="mm", gravity=(0.0, -9810.0, 0.0), ground_interaction=True,
                                       floor_position=(0.0, -5.0, 0.0), damping=3.0), 30.0, 1000.0),
    "forces_viscosity_step": (dict(Viscosity=0.5, Rotationforces=0, Integrationstep=0.002, Refdirx=0.0, Refdiry=1.0),
                              dict(viscosity=0.5, rotation_forces=False, integration_step=0.002,
                                   reference_direction=(0.0, 1.0, 0.0)), 100.0, 1.0),
    "no_length_forces": (dict(Lengthforces=0, Damping=15.0, Gravityz=2.0), dict(length_forces=False, damping=15.0,
                                                                              gravity=(0.0, 0.0, 2.0)), 25.0, 1.0),
}


def sim_setup(node, name):
    chop, kw, rate, scale = SIM_CASES[name]
    for par, value in chop.items():
        node.set(par, value)
    return kw, rate, scale


def test_simulator_declaration(plugin):
    node = plugin("HumanoidSimulator")
    assert (node.op_type, node.op_label, node.min_inputs, node.max_inputs) == (
        "Ewhumanoidsimulator", "EW L1 Humanoid Simulator", 1, 2)
    out = cook(node, body(2))
    assert out.names == list(HumanoidSimulator().outputs.flat_names)
    names = {p.name: p for p in node.params}
    defaults = {"Units": "m", "Startfrominput": 0, "Integrationstep": 0.001, "Damping": 10.0, "Viscosity": 0.0,
                "Lengthforces": 1, "Rotationforces": 1, "Groundinteraction": 0}
    vectors = {"Refdir": [1.0, 0.0, 0.0], "Gravity": [0.0, 0.0, 0.0], "Floor": [0.0, 0.0, 0.0]}
    for key, value in vectors.items():
        assert names[key].size == 3 and names[key].default == value, key
    for key, value in defaults.items():
        assert names[key].default == value, key
    assert not node.setup_issues


@pytest.mark.parametrize("seed", [1, 4])
@pytest.mark.parametrize("case", list(SIM_CASES))
def test_simulator_parity(plugin, case, seed):
    node = plugin("HumanoidSimulator")
    kw, rate, scale = sim_setup(node, case)
    data = body(30, seed=seed, rate=rate, scale=scale)
    expected, _ = run(HumanoidSimulator(sampling_rate=rate, **kw), data, "joints")
    out = clip(node, data, rate=rate)
    assert out.status_name == "OK"
    assert out.data.shape == (30, 3 * NJ)
    assert_close(out.data, expected, rtol=2e-4, atol=1e-4 * scale, what=case)


def test_simulator_start_from_input_and_metres_vs_millimetres(plugin):
    node = plugin("HumanoidSimulator")
    node.set("Startfrominput", 1)
    data = body(15, seed=2)
    expected, _ = run(HumanoidSimulator(sampling_rate=60.0, start_from_input=True), data, "joints")
    out = clip(node, data)
    assert_close(out.data, expected)
    assert_close(out.data[0], data[0], what="the first sample is returned as it is")
    # a body driven in metres reproduces the millimetre run up to rounding (PyEyesWeb note)
    mm = plugin("HumanoidSimulator")
    mm.set("Units", "mm")
    assert_close(clip(mm, data * 1000.0).data / 1000.0, clip(plugin("HumanoidSimulator"), data).data, rtol=1e-3, atol=1e-4)


@pytest.mark.parametrize("chunk", [1, 3, 7])
def test_simulator_state(plugin, chunk):
    node = plugin("HumanoidSimulator")
    data = body(29, seed=3)
    data[8:12, 3 * 4:3 * 4 + 3] = np.nan  # left_hand: a dropout the model handles
    feature = HumanoidSimulator(sampling_rate=60.0)
    expected, status = run(feature, data, "joints")
    assert (status == 0).all()
    assert_close(stream(node, data, chunk), expected, rtol=2e-4, atol=1e-4, what="stream chunks vs process")
    assert_close(clip(node, data).data, expected, rtol=2e-4, atol=1e-4, what="clip vs process")


def test_simulator_reset_and_live_parameters(plugin):
    node = plugin("HumanoidSimulator")
    data = body(24, seed=4)
    first = stream(node, data, 24)
    assert not np.allclose(stream(node, data, 24), first)  # the body goes on from where it was
    node.pulse("Reset")
    assert_close(stream(node, data, 24), first, what="Reset puts the body back in the T-pose")
    # every parameter is live: Damping (and Units-free ones) keep the state; reference = one feature, setter between halves
    node.pulse("Reset")
    feature = HumanoidSimulator(sampling_rate=60.0)
    head, _ = run(feature, data[:12], "joints")
    feature.damping = 4.0
    feature.gravity = (0.0, -9.81, 0.0)
    tail, _ = run(feature, data[12:], "joints")
    a = cook(node, data[:12]).data
    node.set("Damping", 4.0)
    node.set("Gravityy", -9.81)
    b = cook(node, data[12:]).data
    assert_close(np.vstack([a, b]), np.vstack([head, tail]), rtol=2e-4, atol=1e-4, what="live parameters keep the state")
    # Start From Input applies from the next reset
    node.set("Startfrominput", 1)
    c = cook(node, data[:3]).data
    assert not np.allclose(c[0], data[0], atol=1e-6)
    node.pulse("Reset")
    assert_close(cook(node, data[:3]).data[0], data[0], what="start from input after Reset")


def test_simulator_control_input(plugin):
    """The control input is the output of Humanoid Orientations, as in PyEyesWeb (`control` = HumanoidOrientations)."""
    node = plugin("HumanoidSimulator")
    data = body(20, seed=5, amplitude=0.1)
    target = body(20, seed=9, amplitude=0.1)  # another posture gives the directions
    orientations = HumanoidOrientations()
    directions, _ = run(orientations, target, "directions")
    feature = HumanoidSimulator(sampling_rate=60.0)
    expected = np.array([feature.process(row.reshape(NJ, 3), control=d.reshape(NB, 3)).joints.reshape(-1)
                         for row, d in zip(data, directions)])
    out = clip(node, data, f32(directions))
    assert out.status_name == "OK"
    assert_close(out.data, expected, rtol=2e-4, atol=1e-4, what="control")
    without = clip(plugin("HumanoidSimulator"), data).data
    assert not np.allclose(out.data, without, atol=1e-3)  # the control changes the motion
    # a bone with a non-finite component has no control; partial control as in PyEyesWeb (the others keep their rest direction)
    partial = f32(directions).copy()
    partial[:, 3 * 5:3 * 5 + 3] = np.nan
    partial[7, 3 * 6 + 2] = np.inf
    feature = HumanoidSimulator(sampling_rate=60.0)
    expected = np.array([feature.process(row.reshape(NJ, 3), control=d.reshape(NB, 3)).joints.reshape(-1)
                         for row, d in zip(data, partial)])
    assert_close(clip(plugin("HumanoidSimulator"), data, partial).data, expected, rtol=2e-4, atol=1e-4, what="partial control")
    # the same chain, chunked live, equals the clip
    live = plugin("HumanoidSimulator")
    chunks = [cook(live, data[i:i + 5], f32(directions)[i:i + 5]).data for i in range(0, 20, 5)]
    assert_close(np.vstack(chunks), clip(plugin("HumanoidSimulator"), data, f32(directions)).data)


def test_simulator_control_input_errors(plugin):
    node = plugin("HumanoidSimulator")
    data = body(6)
    assert_invalid(cook(node, data, np.zeros((6, 59))))
    assert_invalid(cook(node, data, np.zeros((6, 61))))
    assert_invalid(cook(node, data, np.zeros((5, 60))))  # as many samples as input 0
    assert cook(node, data, None).status_name == "OK"  # an empty second slot is no control


def test_simulator_edges(plugin):
    node = plugin("HumanoidSimulator")
    one = cook(node, body(1))
    assert one.status_name == "OK" and one.data.shape == (1, 3 * NJ)  # no warm-up
    for channels in (0, 1, 62, 64, 66):
        node.pulse("Reset")
        if channels:
            assert_invalid(cook(node, np.zeros((4, channels))))
    node.pulse("Reset")
    inf = body(5)
    inf[2, 7] = np.inf
    out = cook(node, inf)
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data[2].any()
    allnan = body(5)
    allnan[3] = np.nan
    node.pulse("Reset")
    out = cook(node, allnan)
    assert out.status_name == "INVALID_INPUT" and not out.data[3].any()
    # the rejected sample is not fed: the others equal PyEyesWeb on the rows that were accepted
    kept = np.delete(allnan, 3, axis=0)
    expected, _ = run(HumanoidSimulator(sampling_rate=60.0), kept, "joints")
    assert_close(np.delete(out.data, 3, axis=0), expected, rtol=2e-4, atol=1e-4)
    assert HumanoidSimulator().process(np.full((NJ, 3), np.nan)).status.name == "INVALID_INPUT"
    assert HumanoidSimulator().process(inf[2].reshape(NJ, 3)).status.name == "INVALID_INPUT"
    node.pulse("Reset")
    assert_invalid(cook(node, body(5), timeslice=3))  # not a timeslice: use Clip
    # a lone joint: the body hangs from it in its T-pose (PyEyesWeb docstring example); the others are NaN rows = missing
    lone = np.full((2, 3 * NJ), np.nan)
    lone[:, :3] = [0.0, 1.7, 0.0]
    expected, _ = run(HumanoidSimulator(sampling_rate=60.0), lone, "joints")
    assert_close(clip(plugin("HumanoidSimulator"), lone).data, expected)
    # wild but finite input must not crash and must not leave NaN (the model is not a noise filter, it stays finite here)
    rng = np.random.default_rng(3)
    wild = f32(rng.uniform(-2, 2, (10, 63)))
    out = clip(plugin("HumanoidSimulator"), wild)
    assert out.status_name == "OK"
    expected, _ = run(HumanoidSimulator(sampling_rate=60.0), wild, "joints")
    assert_close(out.data, expected, rtol=2e-4, atol=1e-3, what="wild input")
    tiny = plugin("HumanoidSimulator")
    tiny.set("Integrationstep", 1e-9)  # clamped at 1e-5 in the CHOP
    assert tiny.get("Integrationstep") == pytest.approx(1e-5)
    assert cook(tiny, body(2)).status_name == "OK"
