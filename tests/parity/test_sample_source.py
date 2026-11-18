"""The Source parameter of the sample-wise operators (no state between samples).

In Stream mode (the default) the output is always ONE sample, the result for the newest input sample, whatever number of samples
a live source gives in a frame (1 or 2): it never flips between a slice and a series, and the input need not be a timeslice. In
Clip mode the output has one sample per input sample. Hit Cell Detector behaves the same (tested at the end of the file).
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
]


def data(channels, samples=8, seed=3):
    return np.random.default_rng(seed).standard_normal((samples, channels)).astype(np.float32)


def cook(node, x, **kw):
    return node.cook(Signal(x, sample_rate=60.0), sample_rate=60.0, **kw)


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_the_source_parameter_exists_and_defaults_to_stream(plugin, name, channels):
    node = plugin(name, default=True)
    assert node.get("Source") == "stream"
    assert [item[0] for item in node.param("Source").menu] == ["stream", "clip"]


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_stream_is_always_one_sample_the_newest(plugin, name, channels):
    node = plugin(name, default=True)
    for slice_length in (1, 2, 1, 2):        # a live source: 1 sample in a frame, 2 in the next
        x = data(channels, slice_length, seed=slice_length)
        out = cook(node, x)
        assert not out.timeslice and out.data.shape[0] == 1
        clip = plugin(name)                  # clip mode: one value per sample; the last one is the newest
        assert_close(out.data[0], cook(clip, x).data[-1], what=f"{name} {slice_length}")


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_stream_does_not_need_a_timeslice_input(plugin, name, channels):
    node = plugin(name, default=True)
    out = cook(node, data(channels, 8), timeslice=1)
    assert out.data.shape[0] == 1 and "not a timeslice" not in out.warning


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_clip_takes_the_length_of_the_input_and_is_not_a_timeslice(plugin, name, channels):
    node = plugin(name)
    out = cook(node, data(channels, 8), timeslice=1)
    assert not out.timeslice
    assert out.data.shape[0] == 8 and out.warning == ""


@pytest.mark.parametrize("name,channels", OPERATORS)
def test_stream_and_clip_agree_on_the_newest_sample(plugin, name, channels):
    x = data(channels, 8)
    stream = cook(plugin(name, default=True), x).data
    assert_close(stream[0], cook(plugin(name), x).data[-1], what=name)


# ---- Hit Cell Detector: the stream output is one sample, the newest ----------------------------------------------------------
def hit_cell(point, **kw):
    from pyeyesweb.physical_signals import HitCellDetector
    return HitCellDetector(**kw).process(np.array([point], np.float32)).cells.astype(float)[0]


def test_hit_cell_stream_is_always_one_sample_the_newest(plugin):
    node = plugin("HitCellDetector")
    rng = np.random.default_rng(5)
    for slice_length in (1, 2, 1, 2, 2):       # a live source: 1 or 2 points in a frame
        x = rng.uniform(0, 1, (slice_length, 2)).astype(np.float32)
        out = cook(node, x)
        assert not out.timeslice                # a fixed one-sample output: no slice, no series that flips
        assert out.data.shape == (1, 2) and out.status_name == "OK"
        assert_close(out.data[0], hit_cell(x[-1]), what=f"{slice_length} points")


def test_hit_cell_stream_does_not_need_a_timeslice_input(plugin):
    node = plugin("HitCellDetector")
    x = np.random.default_rng(6).uniform(0, 1, (8, 2)).astype(np.float32)
    out = cook(node, x, timeslice=1)
    assert out.status_name == "OK" and out.data.shape == (1, 2)
    assert_close(out.data[0], hit_cell(x[-1]))


def test_hit_cell_clip_gives_one_cell_per_point(plugin):
    node = plugin("HitCellDetector")
    node.set("Source", "clip")
    x = np.random.default_rng(7).uniform(0, 1, (8, 2)).astype(np.float32)
    out = cook(node, x)
    assert not out.timeslice and out.data.shape == (8, 2)
    assert_close(out.data, np.array([hit_cell(p) for p in x]))


def test_hit_cell_stream_only_the_newest_point_counts(plugin):
    node = plugin("HitCellDetector")
    node.set("Clipvalues", 0)
    outside_then_inside = np.array([[1.5, 0.5], [0.2, 0.3]], np.float32)   # an old point outside the area does not matter
    out = cook(node, outside_then_inside)
    assert out.status_name == "OK"
    assert_close(out.data[0], hit_cell(outside_then_inside[-1], clip_values=False))
    out = cook(node, outside_then_inside[::-1])                              # the newest outside: nothing hit
    assert out.status_name == "INVALID_INPUT" and (out.data == -1).all()
    nan_old = np.array([[np.nan, 0.5], [0.2, 0.3]], np.float32)             # a NaN in an old point does not matter either
    assert cook(plugin("HitCellDetector"), nan_old).status_name == "OK"
    assert cook(plugin("HitCellDetector"), nan_old[::-1]).status_name == "INVALID_INPUT"
