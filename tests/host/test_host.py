"""Tests of the mock TouchDesigner host itself (ewhost.py / ew_td_host.dll).

Two groups:
  * real operators (Directness frame, MotionNoiseDetector stream, Rarity buffer) found through EW_TD_PLUGINS, the
    directory that holds <layer>/*.dll (<build>/Plugins/EyesWeb); skipped when it is unset;
  * the fixture plugin (ew_td_fixture.dll, next to ew_td_host.dll), which declares a parameter of every kind and can
    misbehave on request, to test the host against the raw TouchDesigner contract.
ew_td_host.dll is found through EW_TD_HOST or, by default, next to the build tree of EW_TD_PLUGINS.
"""
import os
from pathlib import Path

import numpy as np
import pytest

import ewhost
from ewhost import Chop, HostError, HostUnsupported, Image, OperatorFault, Signal


# ---- finding the binaries ---------------------------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def host_dll():
    try:
        return ewhost.host_library_path()
    except HostError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def plugins_dir(host_dll):
    env = os.environ.get("EW_TD_PLUGINS")
    if not env:
        pytest.skip("EW_TD_PLUGINS is not set (the directory <build>/Plugins/EyesWeb that holds <layer>/*.dll)")
    return Path(env)


def find_operator(plugins_dir, name):
    matches = list(plugins_dir.glob(f"*/Ew_{name}CHOP.dll"))
    if not matches:
        pytest.skip(f"Ew_{name}CHOP.dll not found under {plugins_dir}")
    return matches[0]


@pytest.fixture
def directness(plugins_dir):
    with Chop(find_operator(plugins_dir, "Directness")) as c:
        yield c


@pytest.fixture
def stream(plugins_dir):
    with Chop(find_operator(plugins_dir, "MotionNoiseDetector")) as c:
        c.set("Dims", 2)
        yield c


@pytest.fixture
def buffer(plugins_dir):
    with Chop(find_operator(plugins_dir, "Rarity")) as c:
        yield c


@pytest.fixture
def fixture_chop(host_dll):
    path = Path(host_dll).with_name("ew_td_fixture.dll")
    if not path.exists():
        pytest.skip(f"{path} not found (build the ew_td_fixture target)")
    with Chop(path) as c:
        yield c


def line(n=10, channels=2):
    t = np.arange(n, dtype=np.float32)
    return np.stack([t * (c + 1) for c in range(channels)], axis=1)


def skeleton(n=40, seed=0):
    """x, y of two joints (4 channels) jumping at random, for MotionNoiseDetector with Dims=2: the motion is noisy."""
    rng = np.random.default_rng(seed)
    return (rng.normal(size=(n, 4)) * 5.0).astype(np.float32)


# ---- plugin info and parameters of real operators ---------------------------------------------------------------------

def test_plugin_info(directness):
    assert directness.op_type == "Ewdirectness"
    assert directness.op_label == "EW L2 Directness"
    assert directness.author == "EyesWebTD"
    assert directness.author_email
    assert (directness.min_inputs, directness.max_inputs, directness.num_inputs) == (1, 1, 1)


def test_declared_parameters(stream):
    by_name = {p.name: p for p in stream.params}
    assert list(by_name) == ["Dims", "Threshold", "Source", "Reset"]
    assert by_name["Dims"].kind == "int" and by_name["Dims"].default == 3 and by_name["Dims"].page == "Motion Noise Detector"
    assert by_name["Dims"].clamp_min and by_name["Dims"].clamp_max and (by_name["Dims"].minimum, by_name["Dims"].maximum) == (1, 4)
    assert by_name["Window"].kind == "int" and by_name["Window"].clamp_min and not by_name["Window"].clamp_max
    assert by_name["Threshold"].kind == "float" and by_name["Threshold"].default == pytest.approx(0.005)
    source = by_name["Source"]
    assert source.kind == "menu" and source.default == "stream" and source.page == "Cook"
    assert source.menu == [("stream", "Stream (live timeslice)"), ("clip", "Clip (recording, fresh state each cook)")]
    assert by_name["Reset"].kind == "pulse" and by_name["Reset"].default is None
    assert stream.setup_issues == []


def test_set_clamps_and_menu(stream):
    stream.set("Dims", 9)
    assert stream.get("Dims") == 3
    stream.set("Dims", 0)
    assert stream.get("Dims") == 1
    stream.set("Window", 1)
    assert stream.get("Window") == 2          # clamped at the minimum only
    stream.set("Window", 5000)
    assert stream.get("Window") == 5000
    stream.set("Source", "clip")
    assert stream.get("Source") == "clip"
    with pytest.raises(HostError):
        stream.set("Source", "tape")
    with pytest.raises(KeyError):
        stream.set("Nope", 1)
    with pytest.raises(HostError):
        stream.pulse("Dims")


# ---- frame operator (Directness) ----------------------------------------------------------------------------------------

def test_frame_normal_cook(directness):
    out = directness.cook(line(10, 3))
    assert out.names == ["directness_index"]
    assert out.data.shape == (1, 1) and out.data.dtype == np.float32
    assert out.data[0, 0] == pytest.approx(1.0)   # a straight line
    assert out.warning == "" and out.error == ""
    assert out.status == 0 and out.status_name == "OK"
    assert out.type == "Ewdirectness" and out.label == "EW L2 Directness"
    assert out.output_declared and not out.timeslice
    assert out.sample_rate == pytest.approx(60.0)


def test_frame_detour_is_lower_than_one(directness):
    zigzag = np.array([[0, 0], [1, 5], [2, 0], [3, 5], [4, 0]], dtype=np.float32)
    out = directness.cook(zigzag)
    assert 0 < out.data[0, 0] < 0.5


def test_frame_accepts_1d_input_as_one_channel_and_rejects_it(directness):
    out = directness.cook(np.arange(10, dtype=np.float32))
    assert out.status_name == "INVALID_INPUT"
    assert "at least 2 channels" in out.warning
    assert out.warning == out.reason


def test_frame_too_short_input_is_warming_up(directness):
    out = directness.cook(line(1, 2))             # one sample: not enough yet, not an error
    assert out.status_name == "WARMING_UP" and out.reason == "1 of 2 samples"
    assert out.warning == ""
    assert np.all(out.data == 0)


def test_frame_bad_input_gives_warning_and_zeros(directness):
    out = directness.cook(np.zeros((10, 1), dtype=np.float32))   # one channel: not a trajectory
    assert "at least 2 channels" in out.warning
    assert out.status == 3 and out.status_name == "INVALID_INPUT"
    assert np.all(out.data == 0)
    # the operator recovers at the next good input
    good = directness.cook(line(10, 2))
    assert good.warning == "" and good.data[0, 0] == pytest.approx(1.0)


def test_frame_sample_rate_follows_the_input(directness):
    assert directness.cook(Signal(line(10, 2), sample_rate=120.0)).sample_rate == pytest.approx(120.0)
    assert directness.cook(line(10, 2), sample_rate=30.0).sample_rate == pytest.approx(30.0)


def test_no_input_is_handled(directness):
    out = directness.cook()
    assert out.data.shape == (1, 1) and out.data[0, 0] == 0
    assert out.status_name == "NO_OUTPUT" and out.reason == "no input"
    assert out.warning == ""                      # no input is not a warning
    assert out.info["channels"] == 1 and out.info["samples"] == 1


def test_empty_input_slot_counts_as_no_input(directness):
    out = directness.cook(None)
    assert out.status_name == "NO_OUTPUT"


def test_info_chop_and_dat(directness):
    out = directness.cook(line(10, 2))
    assert out.info == {"status": 0.0, "channels": 1.0, "samples": 1.0, "sample_rate": 60.0}
    names = [row[0] for row in out.info_dat]
    assert names == ["status", "reason", "channels", "samples", "sample_rate"]
    assert all(len(row) == 2 for row in out.info_dat)
    assert out.dat("status") == "OK" and out.dat("channels") == "1" and out.dat("missing") is None
    assert out.cook_count == 1
    assert directness.cook(line(10, 2)).cook_count == 2


def test_reset_instance_gives_a_fresh_node(directness):
    directness.cook(line(10, 2))
    assert directness.cook(line(10, 2)).cook_count == 2
    directness.reset_instance()
    assert directness.cook(line(10, 2)).cook_count == 1


# ---- stream operator (MotionNoiseDetector) ------------------------------------------------------------------------------

def test_stream_shape_and_names(stream):
    x = skeleton(16)
    out = stream.cook(x)
    assert out.names == ["is_noisy"]
    assert out.data.shape == (16, 1)
    assert out.timeslice and out.sample_rate == pytest.approx(60.0)
    assert out.status_name in ("OK", "WARMING_UP")
    assert out.dat("state_reset") == "first cook"
    assert out.info["samples_processed"] == 16 and out.info["resets"] == 0


def test_stream_rejects_a_non_timeslice_input(stream):
    x = skeleton(16)
    out = stream.cook(x, timeslice=1)             # the slice is 1 sample, the input has 16
    assert out.status_name == "INVALID_INPUT"
    assert "not a timeslice" in out.warning and "Clip" in out.warning
    assert np.all(out.data == 0) and out.data.shape == (1, 1)


def test_clip_accepts_a_non_timeslice_input(stream):
    stream.set("Source", "clip")
    x = skeleton(16)
    out = stream.cook(x, timeslice=1)             # a clip ignores the slice length
    assert out.warning == ""
    assert out.data.shape == (16, 1)
    assert not out.timeslice


def test_clip_starts_afresh_each_cook(stream):
    stream.set("Source", "clip")
    x = skeleton(30)
    first = stream.cook(x).data
    second = stream.cook(x).data
    np.testing.assert_array_equal(first, second)


def test_stream_keeps_state_between_cooks(stream):
    x = skeleton(30)
    first = stream.cook(x).data
    second = stream.cook(x).data
    assert not np.array_equal(first, second)      # the window carries over the first cook


def test_reset_pulse_resets_the_state(stream):
    x = skeleton(30)
    first = stream.cook(x).data
    stream.pulse("Reset")
    again = stream.cook(x)
    np.testing.assert_array_equal(first, again.data)
    assert again.dat("state_reset") == "reset pulse" and again.info["resets"] == 1
    assert again.info["samples_processed"] == 30


def test_two_timeslices_equal_one_clip(plugins_dir):
    x = skeleton(40, seed=3)
    path = find_operator(plugins_dir, "MotionNoiseDetector")
    with Chop(path) as live, Chop(path) as clip:
        for c in (live, clip):
            c.set("Dims", 2)
        clip.set("Source", "clip")
        whole = clip.cook(x).data
        a = live.cook(x[:15])
        b = live.cook(x[15:])
        assert a.data.shape == (15, 1) and b.data.shape == (25, 1)
        np.testing.assert_allclose(np.vstack([a.data, b.data]), whole, rtol=0, atol=0)
        assert b.info["samples_processed"] == 40


def test_stream_resets_when_the_input_changes_shape(stream):
    stream.cook(skeleton(10))
    out = stream.cook(Signal(skeleton(10), sample_rate=120.0))
    assert out.dat("state_reset") == "input changed" and out.info["resets"] == 1


def test_stream_bad_channel_count_warns(stream):
    out = stream.cook(np.zeros((8, 3), dtype=np.float32))     # 3 channels for Dims = 2
    assert out.status_name == "INVALID_INPUT" and "multiple of Dims" in out.warning
    assert np.all(out.data == 0)


# ---- buffer operator (Rarity) ---------------------------------------------------------------------------------------------

def test_buffer_shape_names_and_reset(buffer):
    x = np.random.default_rng(1).random((20, 3)).astype(np.float32)
    first = buffer.cook(x)
    assert first.names == ["rarity_0", "rarity_1", "rarity_2"]
    assert first.data.shape == (20, 3)
    assert first.info["resets"] == 0
    second = buffer.cook(x)
    assert not np.array_equal(first.data, second.data)       # the memory persists
    buffer.pulse("Reset")
    third = buffer.cook(x)
    np.testing.assert_array_equal(first.data, third.data)
    assert third.info["resets"] == 1


def test_buffer_mode_distance_gives_one_sample(buffer):
    buffer.set("Method", "mode_distance")
    x = np.random.default_rng(2).random((30, 2)).astype(np.float32)
    out = buffer.cook(x)
    assert out.data.shape == (1, 2) and out.names == ["rarity_0", "rarity_1"]


def test_buffer_without_input(buffer):
    out = buffer.cook()
    assert out.data.shape == (1, 1) and out.status_name == "NO_OUTPUT"


# ---- every operator survives a generic cook ---------------------------------------------------------------------------------

def all_operator_dlls():
    env = os.environ.get("EW_TD_PLUGINS")
    return sorted(Path(env).glob("*/*.dll")) if env else []


@pytest.mark.parametrize("dll", all_operator_dlls(), ids=lambda p: p.stem)
def test_operator_loads_and_does_not_crash_the_host(dll, host_dll):
    with Chop(dll) as c:
        assert c.op_type.startswith("Ew") and c.op_label
        assert [i for i in c.setup_issues if i.startswith("error")] == []
        n = max(c.max_inputs, 1)
        rng = np.random.default_rng(0)
        for shape in [(64, 6), (1, 1), (3, 12)]:
            c.reset_instance()
            inputs = [rng.normal(size=shape).astype(np.float32) for _ in range(n)]
            out = c.cook(*inputs)                       # an OperatorFault or HostUnsupported fails the test
            assert out.data.dtype == np.float32 and out.data.shape[0] >= 1
        c.reset_instance()
        c.cook()                                        # no input
        c.cook(*[np.full((16, 6), np.nan, dtype=np.float32) for _ in range(n)])


# ---- the host against the raw contract (fixture plugin) -----------------------------------------------------------------------

def test_fixture_plugin_info_and_declared_parameters(fixture_chop):
    c = fixture_chop
    assert (c.op_type, c.op_label, c.min_inputs, c.max_inputs) == ("Ewfixture", "EW Host Fixture", 0, 2)
    kinds = {p.name: p.kind for p in c.params}
    assert kinds == {"Gain": "float", "Count": "int", "Match": "int", "Flag": "toggle", "Offset": "float", "Poke": "pulse",
                     "Text": "string", "Mode": "menu", "OddName": "float"}
    assert c.param("Offset").size == 3 and c.param("Gain").page == "Fixture" and c.param("Match").page == "Custom"
    assert c.param("Text").default == "hello" and c.param("Mode").default == "normal" and c.param("Gain").default == 1.0
    assert c.param("Mode").menu_names[:3] == ["normal", "timeslice", "match_input"] and len(c.param("Mode").menu) == 15
    issues = "\n".join(c.setup_issues)
    assert "OddName" in issues and "warning" in issues      # capital after the first letter
    assert "bad name" in issues and "invalid parameter name" in issues
    assert "Gain: appendFloat: duplicate" in issues         # the second Gain was refused


def test_fixture_set_semantics(fixture_chop):
    c = fixture_chop
    c.set("Gain", 20)
    assert c.get("Gain") == 10.0                              # clamped
    c.set("Gain", -3)
    assert c.get("Gain") == 0.0
    c.set("Count", 3.6)
    assert c.get("Count") == 4                                # an int parameter rounds
    c.set("Count", 100)
    assert c.get("Count") == 8
    c.set("Flag", 5)
    assert c.get("Flag") == 1
    c.set("Flag", False)
    assert c.get("Flag") == 0
    c.set("Mode", "timeslice")
    assert c.get("Mode") == "timeslice"
    c.set("Mode", 2)                                          # by index
    assert c.get("Mode") == "match_input"
    with pytest.raises(HostError):
        c.set("Mode", 15)
    with pytest.raises(HostError):
        c.set("Mode", "nope")
    with pytest.raises(HostError):
        c.set("Gain", "high")
    c.set("Text", 12)                                         # a string parameter takes any text
    assert c.get("Text") == "12"
    c.set("Offset", [1, 2, 3])
    with pytest.raises(HostError):
        c.set("Poke", 1)


def test_fixture_values_as_the_operator_reads_them(fixture_chop):
    c = fixture_chop
    c.set("Gain", 2.9)
    c.set("Offset", [1, 2, 3])
    out = c.cook(line(4, 1))
    assert out.dat("float_as_int") == "2"                     # getParInt of a float parameter truncates
    assert out.dat("mode_index") == "0" and out.dat("text") == "hello"
    np.testing.assert_allclose(out.data[:, 0], line(4, 1)[:, 0] * 2.9 + 321, rtol=1e-6)
    c.set("Mode", "timeslice")
    assert c.cook(line(4, 1)).dat("mode_index") == "1"        # getParInt of a menu is the item index
    assert c.cook(line(4, 1)).dat("mode") == "timeslice"      # getParString of a menu is the item name


def test_fixture_pulses_arrive_before_the_next_cook(fixture_chop):
    c = fixture_chop
    assert c.cook(line(3, 1)).info["pokes"] == 0
    c.pulse("Poke")
    c.pulse("Poke")
    assert c.cook(line(3, 1)).info["pokes"] == 2              # delivered at the start of this cook
    assert c.cook(line(3, 1)).info["pokes"] == 2              # and not again
    c.pulse("Poke")
    c.reset_instance()                                        # a new node forgets the pending pulse
    assert c.cook(line(3, 1)).info["pokes"] == 0
    with pytest.raises(HostError):
        c.pulse("Gain")


def test_fixture_output_and_names(fixture_chop):
    c = fixture_chop
    c.set("Count", 3)
    out = c.cook(line(5, 1))
    assert out.names == ["out_0", "out_1", "out_2"] and out.data.shape == (5, 3)
    np.testing.assert_allclose(out.data[:, 0], line(5, 1)[:, 0])
    assert (out.data[:, 1] == 1).all() and (out.data[:, 2] == 2).all()   # no such input channel: the channel index
    assert out.output_declared and not out.timeslice and out.start_index == 0


def test_fixture_input_names_and_defaults(fixture_chop):
    c = fixture_chop
    assert c.cook(line(4, 3)).dat("input_names") == "chan1,chan2,chan3"
    assert c.cook(Signal(line(4, 2), names=["x", "y"])).dat("input_names") == "x,y"
    assert c.cook(np.zeros(4, dtype=np.float32)).dat("input_names") == "chan1"
    with pytest.raises(ValueError):
        Signal(line(4, 2), names=["x"])


def test_fixture_inputs_and_empty_slots(fixture_chop):
    c = fixture_chop
    assert c.cook().info["inputs"] == 0
    assert c.cook(line(3, 1)).info["inputs"] == 1
    assert c.cook(line(3, 1), line(3, 1)).info["inputs"] == 2
    out = c.cook(None, line(3, 1))                            # input 0 empty: getInputCHOP(0) is nullptr
    assert out.info["inputs"] == 2 and out.dat("input_names") == ""
    assert c.cook(line(3, 1), None).info["inputs"] == 1       # trailing empty slot is not counted


def test_fixture_timeslice_length_and_start_index(fixture_chop):
    c = fixture_chop
    c.set("Mode", "timeslice")
    out = c.cook(line(6, 1), start_index=100)
    assert out.timeslice and out.data.shape == (6, 2)
    np.testing.assert_array_equal(out.data[:, 0], np.arange(100, 106))
    assert out.start_index == 100
    out = c.cook(line(6, 1), timeslice=2, start_index=7)      # the host dictates the slice
    assert out.data.shape == (2, 2) and out.info["start"] == 7
    assert c.cook().data.shape[0] == 1                        # no input: one sample


def test_fixture_non_timeslice_uses_the_declared_shape(fixture_chop):
    c = fixture_chop
    c.set("Mode", "fixed_clip")
    out = c.cook(line(3, 1), timeslice=9)
    assert out.data.shape == (5, 2) and out.start_index == 7 and not out.timeslice


def test_fixture_matching_an_input_when_getOutputInfo_returns_false(fixture_chop):
    c = fixture_chop
    c.set("Mode", "match_input")
    out = c.cook(Signal(line(7, 3), names=["a", "b", "c"], sample_rate=90.0), line(2, 1))
    assert not out.output_declared
    assert out.names == ["a", "b", "c"] and out.data.shape == (7, 3) and out.sample_rate == pytest.approx(90.0)
    c.set("Match", 1)                                         # inputMatchIndex
    out = c.cook(line(7, 3), line(2, 1))
    assert out.names == ["chan1"] and out.data.shape == (2, 1) and out.start_index == 0
    with pytest.raises(HostUnsupported):                      # nothing to match
        c.cook(line(7, 3), None)


def test_fixture_unwritten_output_shows_the_fill_value(fixture_chop):
    c = fixture_chop
    c.set("Mode", "leave_unwritten")
    assert np.isnan(c.cook(line(3, 1)).data).all()
    assert (c.cook(line(3, 1), fill=-7.0).data == -7.0).all()


def test_fixture_warning_error_popup_and_enable(fixture_chop):
    c = fixture_chop
    out = c.cook(line(3, 1))
    assert out.warning == "" and out.error == "" and out.popup.startswith("node /project1/Ewfixture")
    assert not c.par_enabled("Text")                          # the operator called enablePar("Text", false)
    c.set("Flag", 1)
    assert c.cook(line(3, 1)).warning == "flag is on"
    assert c.par_enabled("Text")
    c.set("Flag", 0)
    c.set("Mode", "error_string")
    assert c.cook(line(3, 1)).error == "fixture error"


def test_fixture_time_info_and_start_index(fixture_chop):
    c = fixture_chop
    out = c.cook(line(3, 1), sample_rate=25.0, start_index=40)
    assert out.dat("rate") == "25.000000" and out.info["start"] == 40 and out.sample_rate == pytest.approx(25.0)


def test_fixture_cook_count_and_reset(fixture_chop):
    c = fixture_chop
    c.cook(line(3, 1))
    assert c.cook(line(3, 1)).info["cooks"] == 2
    c.set("Gain", 4)
    c.reset_instance()
    assert c.get("Gain") == 1.0                               # parameters at their defaults again
    assert c.cook(line(3, 1)).info["cooks"] == 1


@pytest.mark.parametrize("mode, text", [
    ("crash_access", "access violation (writing address 0x0)"),
    ("crash_read", "access violation (reading address 0x0)"),
    ("divide_zero", "division by zero"),
    ("throw", "fixture exception"),
    ("terminate", "called"),
    ("abort", "abort() called"),
])
def test_fixture_crash_is_reported_and_the_host_survives(fixture_chop, mode, text):
    c = fixture_chop
    c.set("Mode", mode)
    with pytest.raises(OperatorFault) as excinfo:
        c.cook(line(3, 1))
    assert "execute" in str(excinfo.value) and text in str(excinfo.value)
    c.reset_instance()                                        # the interpreter is alive and the plugin usable again
    assert c.cook(line(3, 1)).info["cooks"] == 1


@pytest.mark.parametrize("mode, text", [
    ("bad_par", "'Nope', which it did not declare"),
    ("unsupported", "OP_Inputs::getParDAT"),
    ("empty_output", "0 channels"),
])
def test_fixture_misuse_of_the_host_is_loud(fixture_chop, mode, text):
    c = fixture_chop
    c.set("Mode", mode)
    with pytest.raises(HostUnsupported) as excinfo:
        c.cook(line(3, 1))
    assert text in str(excinfo.value)


def test_fixture_missing_dll_and_not_a_plugin(host_dll, tmp_path):
    with pytest.raises(HostError):
        Chop(tmp_path / "missing.dll")
    with pytest.raises(HostError):
        Chop(host_dll)                                        # a DLL without the CHOP entry points


# ---- TOP inputs (OP_Inputs::getInputTOP, OP_TOPInput::downloadTexture) -----------------------------------------------------------

MONO8, RG8, RGBA8, BGRA8 = 3, 4, 1, 0
MONO16, RG16, RGBA16 = 100, 101, 102
MONO32F, RG32F, RGBA32F = 5, 6, 2


@pytest.fixture
def top_chop(host_dll):
    path = Path(host_dll).with_name("ew_td_fixture_top.dll")
    if not path.exists():
        pytest.skip(f"{path} not found (build the ew_td_fixture_top target)")
    with Chop(path) as c:
        yield c


def pixels(chop, image, fmt="native", flip=False):
    chop.set("Format", fmt)
    chop.set("Flip", flip)
    return chop.cook(image)


ROWS = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)       # 2 rows x 3 columns, row 0 on top


def test_top_input_is_seen_as_a_top_and_not_as_a_chop(top_chop):
    out = top_chop.cook(Image(ROWS))
    assert out.dat("inputs") == "1" and out.dat("top_null") == "0" and out.dat("chop0_null") == "1"
    assert (out.dat("width"), out.dat("height")) == ("3", "2")
    assert out.dat("path") == "/project1/top1" and out.dat("op_id_total_cooks") == "2000,1"
    assert top_chop.cook(Image(ROWS)).dat("op_id_total_cooks") == "2000,2"       # totalCooks follows the cook


def test_top_input_lives_for_one_cook(top_chop):
    top_chop.cook(Image(ROWS))
    out = top_chop.cook()
    assert out.dat("inputs") == "0" and out.dat("top_null") == "1"
    out = top_chop.cook(line(3, 1))                           # a CHOP in slot 0 is no TOP
    assert out.dat("inputs") == "1" and out.dat("top_null") == "1" and out.dat("chop0_null") == "0"


def test_top_in_a_later_slot_and_empty_slots(top_chop):
    out = top_chop.cook(line(3, 1), Image(ROWS))
    assert out.dat("inputs") == "2" and out.dat("chop0_null") == "0" and out.dat("top_null") == "1"   # slot 0 holds the CHOP
    out = top_chop.cook(None, Image(ROWS))
    assert out.dat("inputs") == "2" and out.dat("chop0_null") == "1" and out.dat("top_null") == "1"


def test_native_format_follows_dtype_and_channels(top_chop):
    cases = [(np.zeros((2, 2), np.uint8), MONO8), (np.zeros((2, 2, 2), np.uint8), RG8), (np.zeros((2, 2, 3), np.uint8), RGBA8),
             (np.zeros((2, 2, 4), np.uint8), RGBA8), (np.zeros((2, 2), np.float32), MONO32F),
             (np.zeros((2, 2, 2), np.float64), RG32F), (np.zeros((2, 2, 3), np.float32), RGBA32F), (np.zeros((2, 2), bool), MONO8)]
    for data, expected in cases:
        out = pixels(top_chop, Image(data))
        assert out.dat("native_format") == str(expected) and out.dat("format") == str(expected), data.dtype


def test_rows_are_bottom_first_unless_the_download_is_flipped(top_chop):
    # TouchDesigner textures have their origin at the bottom left: without verticalFlip the first row in memory is the bottom row
    assert pixels(top_chop, Image(ROWS), flip=False).data[:, 0].tolist() == [4, 5, 6, 1, 2, 3]
    assert pixels(top_chop, Image(ROWS), flip=True).data[:, 0].tolist() == [1, 2, 3, 4, 5, 6]     # as the array reads
    assert pixels(top_chop, Image(ROWS), flip=True).dat("size") == "6"


def test_conversion_between_8_bit_and_float(top_chop):
    out = pixels(top_chop, Image(ROWS), "mono32f", flip=True)
    assert np.allclose(out.data[:, 0], ROWS.ravel() / 255.0, atol=0, rtol=1e-7) and out.dat("format") == str(MONO32F)
    out = pixels(top_chop, Image(ROWS), "mono16", flip=True)                  # 16-bit fixed: v * 65535 rounded
    assert out.data[:, 0].tolist() == [257, 514, 771, 1028, 1285, 1542] and out.dat("format") == str(MONO16)
    img = np.array([[0.0, 0.5, 1.0, 2.0, -1.0, 0.2]], dtype=np.float32)
    assert pixels(top_chop, Image(img), "mono8", flip=True).data[:, 0].tolist() == [0, 128, 255, 255, 0, 51]   # rounded, clamped
    assert np.array_equal(pixels(top_chop, Image(img), "mono32f", flip=True).data[:, 0], img[0])               # float untouched


def test_conversion_between_channel_layouts(top_chop):
    rgba = np.array([[[10, 20, 30, 40]]], dtype=np.uint8)                        # one pixel
    rgb = rgba[..., :3]
    cook = lambda image, fmt: pixels(top_chop, Image(image), fmt, flip=True).data[:, 0].tolist()
    assert cook(rgba, "rgba8") == [10, 20, 30, 40] and cook(rgba, "bgra8") == [30, 20, 10, 40]
    assert cook(rgba, "rg8") == [10, 20] and cook(rgba, "mono8") == [10]          # Mono takes the red channel
    assert cook(rgb, "rgba8") == [10, 20, 30, 255]                                  # no 3-channel textures: opaque alpha
    gray = np.array([[7]], dtype=np.uint8)
    assert cook(gray, "rgba8") == [7, 7, 7, 255] and cook(gray, "rg8") == [7, 7]    # Mono reads as (r, r, r, 1)
    assert pixels(top_chop, Image(np.array([[[1.0, 0.5]]], np.float32)), "rgba32f", flip=True).data[:, 0].tolist() == [1.0, 0.5, 0.0, 1.0]
    assert cook(rgba, "rgba16") == [2570, 5140, 7710, 10280]


def test_format_not_implemented_by_the_host_is_loud(top_chop):
    top_chop.set("Format", "a8")
    with pytest.raises(HostUnsupported) as excinfo:
        top_chop.cook(Image(ROWS))
    assert "downloadTexture" in str(excinfo.value) and "not implemented" in str(excinfo.value)


def test_image_arguments_are_checked():
    with pytest.raises(ValueError):
        Image(np.zeros((2, 2, 5), np.uint8))
    with pytest.raises(ValueError):
        Image(np.zeros(4, np.uint8))
    with pytest.raises(ValueError):
        Image(np.zeros((0, 3), np.uint8))
    with pytest.raises(ValueError):
        Image(np.zeros((2, 2), np.uint16))


def test_a_large_image_is_downloaded_whole(top_chop):
    img = (np.arange(240 * 320) % 251).astype(np.uint8).reshape(240, 320)
    out = pixels(top_chop, Image(img), flip=True)
    assert np.array_equal(out.data[:, 0].astype(np.uint8).reshape(240, 320), img)


def test_top_parameter_is_read_through_getParTOP(top_chop):
    out = top_chop.cook(tops={"Top": Image(ROWS)})
    assert out.dat("top_null") == "0" and out.dat("from_parameter") == "1" and out.dat("inputs") == "0"
    assert out.dat("path") == "/project1/Top" and out.dat("op_id_total_cooks") == "3000,1"
    assert out.data[:, 0].tolist() == [4, 5, 6, 1, 2, 3]                       # bottom row first, as without verticalFlip
    out = top_chop.cook()                                                      # nothing given: the parameter is empty
    assert out.dat("top_null") == "1" and out.dat("from_parameter") == "1"


def test_wired_top_wins_over_the_top_parameter(top_chop):
    other = np.full((2, 3), 9, dtype=np.uint8)
    out = top_chop.cook(Image(ROWS), tops={"Top": Image(other)})
    assert out.dat("from_parameter") == "0" and out.data[:, 0].tolist() == [4, 5, 6, 1, 2, 3]


def test_top_for_an_undeclared_parameter_is_refused(top_chop):
    with pytest.raises(HostError):
        top_chop.cook(tops={"Nope": Image(ROWS)})
