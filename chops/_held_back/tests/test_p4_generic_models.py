"""Parity of GenericModelOrientations and GenericModelSimulator (CHOP operators) with their PyEyesWeb features, on the same float32 data.

The model is given to the CHOPs as EyesWeb XML (parameter Modelxml, or Modelfile with a path) and to PyEyesWeb as the
MassSpringModel loaded from the same text. The masses and springs are sorted by name in the core, so the CHOP channels
follow that order (documented in generic_model_common.h); the model below has names that do not sort like they are
written (hip, knee, ankle, toe -> ankle, hip, knee, toe) to test it. PyEyesWeb `labels` / `joint_map` are not CHOP
parameters (the channel order replaces them); `units` only names the unit and is not a parameter.
The simulator is a stream operator, the orientations operator is stateless; the time step of a
sample is 1 / sample rate of the input (PyEyesWeb: sampling_rate=rate).
"""
import numpy as np
import pytest

from conftest import Signal, assert_close
from data import smooth_walk
from pyeyesweb.physical_signals import GenericModelOrientations, GenericModelSimulator, MassSpringModel

MASSES = ["ankle", "hip", "knee", "toe"]      # the order of the channels (sorted by name)
SPRINGS = ["foot", "shin", "thigh"]


def model_xml(stiffness=2000.0, hip_mass=50.0):
    return f"""<Model>
  <Masses>
    <Mass name="hip" mass="{hip_mass}" x="0" y="1" z="0"/>
    <Mass name="knee" mass="3" x="0" y="0.6" z="0"/>
    <Mass name="ankle" mass="1.5" x="0" y="0.2" z="0"/>
    <Mass name="toe" mass="0.5" x="0.15" y="0.2" z="0"/>
  </Masses>
  <Springs>
    <Spring name="thigh" mass1="hip" mass2="knee" restLength="0.4" lengthStiffness="{stiffness}" lengthDamping="1"
            restDirX="0" restDirY="-1" restDirZ="0" dirStiffness="{stiffness}" dirDamping="1"/>
    <Spring name="shin" mass1="knee" mass2="ankle" restLength="0.4" lengthStiffness="{stiffness}" lengthDamping="1"
            restDirX="0" restDirY="-1" restDirZ="0" dirStiffness="{stiffness}" dirDamping="1"/>
    <Spring name="foot" mass1="ankle" mass2="toe" restLength="0.15" lengthStiffness="{stiffness}" lengthDamping="1"
            restDirX="1" restDirY="0" restDirZ="0" dirStiffness="{stiffness}" dirDamping="1"/>
  </Springs>
</Model>"""


XML = model_xml()


def model(xml=XML):
    return MassSpringModel.from_xml_string(xml)


# ---- helpers --------------------------------------------------------------------------------------------------------
def f32(x):
    return np.asarray(x, dtype=np.float32).astype(np.float64)


def positions(n, rate=60.0, seed=1):
    """Masses in the channel order of the CHOPs (sorted names), joint-major: (n, 12). The hip is the head of the chain."""
    rest = {"hip": (0, 1, 0), "knee": (0, .6, 0), "ankle": (0, .2, 0), "toe": (.15, .2, 0)}
    cols = [np.array(rest[m]) + 0.12 * smooth_walk(n, 3, rate=rate, seed=seed + k) for k, m in enumerate(MASSES)]
    return f32(np.hstack(cols))


def directions(pos):
    """The bone vectors of the positions, as GenericModelOrientations gives them (joint-major, float32)."""
    feature = GenericModelOrientations(model())
    return f32(np.vstack([feature.process(row.reshape(-1, 3)).directions.reshape(-1) for row in pos]))


def cook(node, data, rate=60.0, **kw):
    return node.cook(Signal(np.asarray(data, dtype=np.float32), sample_rate=rate), sample_rate=rate, **kw)


def setup(node, xml=XML, **pars):
    node.set("Modelxml", xml)
    for k, v in pars.items():
        node.set(k, v)


def flat(feature, result):
    values = result.to_flat_dict()
    return np.concatenate([np.atleast_1d(np.asarray(values[n], dtype=float)) for n in feature.outputs.flat_names])


def py_rows(feature, rows):
    """feature.process on every row (n, 3 * points) reshaped to points: (values (n, channels), statuses)."""
    results = [feature.process(np.asarray(r, dtype=float).reshape(-1, 3)) for r in rows]
    return np.array([flat(feature, r) for r in results]), np.array([int(r.status) for r in results])


def stream(node, data, chunk, rate=60.0):
    return np.vstack([cook(node, data[i:i + chunk], rate).data for i in range(0, len(data), chunk)])


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


# the CHOP parameter of each PyEyesWeb keyword, for the cases below
BASE_PARS = {"gravity": ("Gravityx", "Gravityy", "Gravityz"), "floor_position": ("Floorx", "Floory", "Floorz"),
             "reference_direction": ("Refdirx", "Refdiry", "Refdirz")}
BASE_NAMES = {"integration_step": "Integrationstep", "damping": "Damping", "viscosity": "Viscosity",
              "length_forces": "Lengthforces", "rotation_forces": "Rotationforces",
              "ground_interaction": "Groundinteraction", "use_input_lengths": "Useinputlengths",
              "start_from_input": "Startfrominput"}


def apply(node, kw):
    """Set the CHOP parameters that correspond to the PyEyesWeb keywords `kw`."""
    for key, value in kw.items():
        if key in BASE_PARS:
            for name, v in zip(BASE_PARS[key], value):
                node.set(name, v)
        else:
            node.set(BASE_NAMES[key], value)


# ---- the two operators, as data ------------------------------------------------------------------------------------
def make_orientations(kw, rate):
    return GenericModelOrientations(model(), **kw)


def make_simulator(kw, rate):
    return GenericModelSimulator(model(), sampling_rate=rate, **kw)


def input_of(kind, pos):
    return pos if kind == "Orientations" else directions(pos)


MAKERS = {"Orientations": make_orientations, "Simulator": make_simulator}
OUT_CHANNELS = {"Orientations": 9, "Simulator": 12}
STATEFUL = ["Simulator"]

CASES = {
    "Orientations": {"default": ({}, 40, 60.0)},
    "Simulator": {
        "default": ({}, 50, 60.0),
        "gravity_floor": (dict(gravity=(0.0, -9.81, 0.0), ground_interaction=True, floor_position=(0.0, 0.1, 0.0),
                               damping=3.0, viscosity=0.5), 50, 25.0),
        "input_lengths_step": (dict(use_input_lengths=True, integration_step=0.002, damping=5.0), 40, 30.0),
        "forces_off_ref": (dict(rotation_forces=False, length_forces=True, reference_direction=(0.0, 1.0, 0.0)), 40, 60.0),
        "start_from_input": (dict(start_from_input=True, damping=3.0), 40, 60.0),
    },
}


def cases():
    return [(kind, name) for kind, group in CASES.items() for name in group]


def case_ids():
    return [f"{k}-{n}" for k, n in cases()]


# ---- declaration ----------------------------------------------------------------------------------------------------
DECLARATION = {"Orientations": ("Ewgenericmodelorientations", "EW L1 Generic Model Orientations"),
               "Simulator": ("Ewgenericmodelsimulator", "EW L1 Generic Model Simulator")}


@pytest.mark.parametrize("kind", list(MAKERS))
def test_declaration(plugin, kind):
    node = plugin(f"GenericModel{kind}")
    assert (node.op_type, node.op_label) == DECLARATION[kind]
    assert (node.num_inputs, node.min_inputs, node.max_inputs) == (1, 1, 1)
    assert not node.setup_issues
    setup(node)
    feature = MAKERS[kind]({}, 60.0)
    pos = positions(5)
    out = cook(node, input_of(kind, pos))
    assert out.status_name == "OK"
    assert out.names == list(feature.outputs.flat_names)
    assert out.data.shape == (5, OUT_CHANNELS[kind])
    # the order the input has to follow is shown on the Info DAT
    assert out.dat("input_names") == " ".join(MASSES if kind == "Orientations" else SPRINGS)


@pytest.mark.parametrize("kind", STATEFUL)
def test_defaults_are_those_of_pyeyesweb(plugin, kind):
    node = plugin(f"GenericModel{kind}")
    feature = MAKERS[kind]({}, 60.0)
    for key in feature._params:
        if key in ("model", "units", "sampling_rate"):
            continue
        value = feature._params[key]
        names = BASE_PARS.get(key) or (BASE_NAMES[key],)
        got = [node.get(n) for n in names]
        want = list(value) if isinstance(value, (tuple, list)) else [value]
        assert got == pytest.approx(want) or got == want, key


# ---- numeric parity -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [1, 5])
@pytest.mark.parametrize("kind,name", cases(), ids=case_ids())
def test_parity(plugin, kind, name, seed):
    kw, n, rate = CASES[kind][name]
    node = plugin(f"GenericModel{kind}")
    setup(node)
    apply(node, kw)
    data = input_of(kind, positions(n, rate, seed))
    expected, status = py_rows(MAKERS[kind](kw, rate), data)
    assert set(status) == {0}
    out = clip(node, data, rate) if kind != "Orientations" else cook(node, data, rate)
    assert out.status_name == "OK"
    assert_close(out.data, expected, what=f"{kind} {name}")


def test_orientations_are_the_bone_vectors(plugin):
    node = plugin("GenericModelOrientations")
    setup(node)
    pos = positions(6)
    out = cook(node, pos).data
    p = pos.reshape(6, 4, 3)
    ankle, hip, knee, toe = (p[:, i] for i in range(4))
    assert_close(out[:, 0:3], toe - ankle)        # foot: ankle -> toe
    assert_close(out[:, 3:6], ankle - knee)       # shin
    assert_close(out[:, 6:9], knee - hip)         # thigh
    assert node.get("Modelxml") == XML


def test_orientations_one_cook_per_sample_and_rate(plugin):
    node = plugin("GenericModelOrientations")
    setup(node)
    out = cook(node, positions(9), rate=30.0)
    assert out.data.shape[0] == 9 and out.sample_rate == 30.0


# ---- the model: Modelxml / Modelfile -------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["Orientations", "Simulator"])
def test_modelfile_equals_modelxml(plugin, tmp_path, kind):
    data = input_of(kind, positions(20))
    by_xml = plugin(f"GenericModel{kind}")
    setup(by_xml)
    path = tmp_path / "leg.xml"
    path.write_text(XML, encoding="utf-8")
    by_file = plugin(f"GenericModel{kind}")
    by_file.set("Modelfile", str(path))
    assert_close(cook(by_file, data).data, cook(by_xml, data).data)
    assert by_file.cook(Signal(data[:2].astype(np.float32), sample_rate=60.0)).status_name == "OK"
    # Modelxml has priority over Modelfile
    by_file.set("Modelxml", model_xml(hip_mass=2.0))
    if kind != "Orientations":
        by_file.pulse("Reset")
    other = plugin(f"GenericModel{kind}")
    setup(other, model_xml(hip_mass=2.0))
    assert_close(cook(by_file, data).data, cook(other, data).data)


def test_model_change_restarts_state_and_file_is_reloaded(plugin, tmp_path):
    data = directions(positions(20))
    node = plugin("GenericModelSimulator")
    path = tmp_path / "leg.xml"
    path.write_text(XML, encoding="utf-8")
    node.set("Modelfile", str(path))
    first = cook(node, data).data
    again = cook(node, data).data
    assert not np.allclose(first, again)         # the state goes on
    path.write_text(model_xml(stiffness=500.0), encoding="utf-8")
    import os
    os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
    changed = cook(node, data).data
    fresh = GenericModelSimulator(model(model_xml(stiffness=500.0)), sampling_rate=60.0)
    assert_close(changed, py_rows(fresh, data)[0], what="a new model starts afresh")
    # same topology, other values through Modelxml
    node.set("Modelxml", XML)
    assert_close(cook(node, data).data, py_rows(GenericModelSimulator(model(), sampling_rate=60.0), data)[0])


def test_no_model_or_bad_model(plugin):
    for kind in MAKERS:
        node = plugin(f"GenericModel{kind}")
        out = cook(node, positions(4))                     # no model at all
        assert_invalid(out)
        assert "no model" in out.reason
        assert out.names and len(out.names) >= 1           # a placeholder channel, never zero channels
        node.set("Modelxml", "<Model><Masses/></Model>")   # no springs section
        assert_invalid(cook(node, positions(4)))
        node.set("Modelxml", "not xml at all")
        assert_invalid(cook(node, positions(4)))
        node.set("Modelxml", "")
        node.set("Modelfile", "C:/no/such/file.xml")
        out = cook(node, positions(4))
        assert_invalid(out)
        node.set("Modelxml", XML)                          # recovers
        assert cook(node, input_of(kind, positions(4))).status_name == "OK"


def test_model_with_a_bad_spring_is_invalid(plugin):
    node = plugin("GenericModelOrientations")
    setup(node, XML.replace('mass2="knee"', 'mass2="nowhere"'))
    assert_invalid(cook(node, positions(4)))


# ---- state ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("chunk", [1, 3, 7])
@pytest.mark.parametrize("kind", STATEFUL)
def test_state_chunks_clip_process(plugin, kind, chunk):
    kw = {}
    node = plugin(f"GenericModel{kind}")
    setup(node)
    apply(node, kw)
    data = input_of(kind, positions(29, seed=4))
    expected, _ = py_rows(MAKERS[kind](kw, 60.0), data)
    assert_close(stream(node, data, chunk), expected, what="stream chunks vs process")
    assert_close(clip(node, data).data, expected, what="clip vs process")


@pytest.mark.parametrize("kind", STATEFUL)
def test_reset(plugin, kind):
    node = plugin(f"GenericModel{kind}")
    setup(node)
    data = input_of(kind, positions(25, seed=6))
    first = stream(node, data, 25)
    second = stream(node, data, 25)
    assert not np.allclose(first, second)
    node.pulse("Reset")
    assert_close(stream(node, data, 25), first, what="Reset forgets")


def test_start_from_input_only_on_the_first_frame_after_reset(plugin):
    node = plugin("GenericModelSimulator")
    setup(node, Startfrominput=1, Damping=3.0)
    data = directions(positions(12, seed=2))
    expected, _ = py_rows(GenericModelSimulator(model(), sampling_rate=60.0, start_from_input=True, damping=3.0), data)
    assert_close(stream(node, data, 5), expected)
    node.pulse("Reset")
    assert_close(stream(node, data, 12), expected, what="again after Reset")
    node.set("Startfrominput", 0)
    node.pulse("Reset")
    plain, _ = py_rows(GenericModelSimulator(model(), sampling_rate=60.0, damping=3.0), data)
    assert_close(stream(node, data, 12), plain)
    assert not np.allclose(plain, expected)


@pytest.mark.parametrize("kind", STATEFUL)
def test_live_and_structural_parameters(plugin, kind):
    node = plugin(f"GenericModel{kind}")
    setup(node, Damping=3.0)
    data = input_of(kind, positions(30, seed=8))
    head, tail = data[:15], data[15:]
    # LIVE: a change of damping / viscosity / forces keeps the state (reference: one feature, parameter changed)
    feature = MAKERS[kind](dict(damping=3.0), 60.0)
    a, _ = py_rows(feature, head)
    feature.damping = 6.0
    feature.viscosity = 0.4
    b, _ = py_rows(feature, tail)
    assert_close(cook(node, head).data, a)
    node.set("Damping", 6.0)
    node.set("Viscosity", 0.4)
    assert_close(cook(node, tail).data, b, what="live parameters keep the state")
    # STRUCTURAL: another model restarts the state; the second half equals a fresh feature on its own
    node.set("Modelxml", model_xml(hip_mass=2.0))
    fresh = MAKERS[kind](dict(damping=6.0, viscosity=0.4), 60.0)
    fresh = type(fresh)(model(model_xml(hip_mass=2.0)), sampling_rate=60.0, damping=6.0, viscosity=0.4)
    assert_close(cook(node, tail).data, py_rows(fresh, tail)[0], what="a new model starts afresh")


# ---- statuses and edges ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", list(MAKERS))
def test_wrong_channel_count(plugin, kind):
    node = plugin(f"GenericModel{kind}")
    setup(node)
    good = input_of(kind, positions(6))
    for channels in (good.shape[1] - 1, good.shape[1] + 3, 1):
        bad = np.zeros((6, channels))
        assert_invalid(cook(node, bad))
    assert cook(node, good).status_name == "OK"


@pytest.mark.parametrize("kind", list(MAKERS))
def test_single_sample_and_not_a_timeslice(plugin, kind):
    node = plugin(f"GenericModel{kind}")
    setup(node)
    data = input_of(kind, positions(5))
    assert cook(node, data[:1]).status_name == "OK"
    if kind != "Orientations":
        assert_invalid(cook(node, data, timeslice=3))  # use Source = clip


@pytest.mark.parametrize("kind", list(MAKERS))
def test_dropout_row_is_missing_like_in_pyeyesweb(plugin, kind):
    kw = dict(damping=3.0)
    node = plugin(f"GenericModel{kind}")
    setup(node)
    apply(node, kw if kind != "Orientations" else {})
    data = input_of(kind, positions(20, seed=9)).copy()
    data[6:9, 3:6] = np.nan            # one point (row 1: its x y z) missing for three frames
    data[12, 7] = np.nan               # a single NaN component: the whole point is missing
    expected, status = py_rows(MAKERS[kind](kw if kind != "Orientations" else {}, 60.0), data)
    assert set(status) == {0}
    out = clip(node, data) if kind != "Orientations" else cook(node, data)
    assert out.status_name == "OK"
    assert_close(out.data, expected)
    if kind == "Orientations":
        assert np.isnan(out.data[6:9]).any()   # a spring with a missing mass is NaN, as in PyEyesWeb


@pytest.mark.parametrize("kind", list(MAKERS))
def test_non_finite_frames(plugin, kind):
    kw = dict(damping=3.0) if kind != "Orientations" else {}
    node = plugin(f"GenericModel{kind}")
    setup(node)
    apply(node, kw)
    data = input_of(kind, positions(10, seed=5)).copy()
    inf, allnan = data.copy(), data.copy()
    inf[4, 2] = np.inf
    allnan[4, :] = np.nan
    for bad in (inf, allnan):
        out = clip(node, bad) if kind != "Orientations" else cook(node, bad)
        assert out.status_name == "INVALID_INPUT" and out.warning
        assert not np.nan_to_num(out.data[4]).any()          # the bad sample is zero
        # PyEyesWeb: the same frame is INVALID_INPUT and does not touch the model
        feature = MAKERS[kind](kw, 60.0)
        values, status = py_rows(feature, [r for i, r in enumerate(bad) if i != 4])
        assert set(status) == {0}
        rows = np.vstack([out.data[:4], out.data[5:]])
        assert_close(rows, values)
        r = feature.process(bad[4].reshape(-1, 3))
        assert int(r.status) == 3
    # a frame that is only partly NaN is valid (the other points are present)
    part = data.copy()
    part[4, :3] = np.nan
    assert (clip(node, part) if kind != "Orientations" else cook(node, part)).status_name == "OK"


def test_invalid_parameters_are_invalid_input(plugin):
    for kind in STATEFUL:
        node = plugin(f"GenericModel{kind}")
        setup(node)
        node.set("Integrationstep", 0.0)
        data = input_of(kind, positions(4))
        assert_invalid(cook(node, data))
        with pytest.raises(ValueError):
            MAKERS[kind](dict(integration_step=0.0), 60.0)
        node.set("Integrationstep", 0.001)
        assert cook(node, data).status_name == "OK"
