"""The Source parameter of the sample-wise operators (one output sample per input sample, no state).

In Stream mode (the default) the output is declared as a timeslice, so a live input that has 1 sample in a frame and 2 in the
next does not make the viewer flip between a series and a slice; an input that is not the slice TouchDesigner asked for is
INVALID_INPUT. In Clip mode the output has the length of the input.
"""
import numpy as np
import pytest

from conftest import Signal, assert_close

OPERATORS = [
    ("BoundingBoxFilledArea", 12),   # name, channels of the input
    ("EllipsoidSphericity", 12),
    ("PointsDensity", 12),
    ("Equilibrium", 12),
    ("TriangleSymmetry", 9),
    ("Symmetry", 12),
    ("HitCellDetector", 2),
]


def data(channels, samples=8, seed=3):
    return np.random.default_rng(seed).standard_normal((samples, channels)).astype(np.float32)


def cook(node, x, **kw):
    return node.cook(Signal(x, sample_rate=60.0), sample_rate=60.0, **kw)


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_the_source_parameter_exists_and_defaults_to_stream(plugin, name, channels):
    node = plugin(name)
    assert node.get("Source") == "stream"
    assert [item[0] for item in node.param("Source").menu] == ["stream", "clip"]


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_stream_is_a_timeslice_of_the_slice_length(plugin, name, channels):
    node = plugin(name)
    for slice_length in (1, 2, 1):          # a live source: 1 sample in a frame, 2 in the next
        out = cook(node, data(channels, slice_length))
        assert out.timeslice
        assert out.data.shape[0] == slice_length


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_stream_rejects_an_input_that_is_not_the_slice(plugin, name, channels):
    node = plugin(name)
    out = cook(node, data(channels, 8), timeslice=1)
    assert out.status_name == "INVALID_INPUT"
    assert "not a timeslice" in out.warning and "Clip" in out.warning


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_clip_takes_the_length_of_the_input_and_is_not_a_timeslice(plugin, name, channels):
    node = plugin(name)
    node.set("Source", "clip")
    out = cook(node, data(channels, 8), timeslice=1)
    assert not out.timeslice
    assert out.data.shape[0] == 8 and out.warning == ""


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_clip_and_stream_give_the_same_numbers(plugin, name, channels):
    x = data(channels, 8)
    stream = cook(plugin(name), x).data
    node = plugin(name)
    node.set("Source", "clip")
    assert_close(cook(node, x).data, stream, what=name)
