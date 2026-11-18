"""Parity tests of the held-back CHOPs ContourCurvature and BodyPartsFromCurvature (chops/_held_back, not built).

These operators left the TouchDesigner catalog (design review 2026-11-17): a contour has no practical source in TouchDesigner.
The tests are kept for a return of the operators; they were written for the API before the review, where PyEyesWeb had a
public ContourCurvature and BodyPartsFromCurvature took (curvature, contour), so they have to be updated before they are
collected (`BodyPartsFromCurvature` now takes the contour only).
"""
import numpy as np
import pytest

import data
from conftest import Signal, assert_close
from pyeyesweb.data_models import Status


def f32(a):
    return np.asarray(a, dtype=np.float32).astype(np.float64)



def blob(n, phase=0.0, seed=0, noise=0.0):
    """A closed star-like contour of n points (x, y), float32 values."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = 10 + 3 * np.cos(5 * t + phase) + 0.3 * np.cos(2 * t) + noise * np.random.default_rng(seed).standard_normal(n)
    return f32(np.column_stack([r * np.cos(t), r * np.sin(t)]))

CONTOURS = [pytest.param(blob(57), id="star57"), pytest.param(blob(83, 0.7, seed=3, noise=0.15), id="noisy83")]


def cook(node, x, rate=60.0, **kw):
    return node.cook(Signal(f32(x), sample_rate=rate), **kw)


def declared(node, op_type, label, inputs=1):
    assert (node.op_type, node.op_label) == (op_type, label)
    assert node.min_inputs == node.max_inputs == inputs
    return node



# --- ContourCurvature ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("contour", CONTOURS)
def test_contour_curvature_parity(plugin, contour):
    out = cook(plugin("ContourCurvature"), contour)
    expected = ContourCurvature().process(contour).curvature
    assert out.status_name == "OK" and out.data.shape == (len(contour), 1)
    assert_close(out.data[:, 0], expected, what="curvature")


def test_contour_curvature_extra_channels_ignored(plugin):
    c = blob(57)
    out = cook(plugin("ContourCurvature"), np.column_stack([c, c[:, 0]]))
    assert_close(out.data[:, 0], ContourCurvature().process(c).curvature)


def test_contour_curvature_one_channel_is_invalid_input(plugin):
    out = cook(plugin("ContourCurvature"), blob(57)[:, :1])
    assert out.status_name == "INVALID_INPUT" and out.warning
    assert not out.data.any()


def test_contour_curvature_nan(plugin):
    c = blob(57)
    c[5, 0] = np.nan
    assert ContourCurvature().process(c).status == Status.INVALID_INPUT
    assert cook(plugin("ContourCurvature"), c).status_name == "INVALID_INPUT"


# --- BodyPartsFromCurvature ----------------------------------------------------------------------------------------


def body_frames(n=120, count=6, step=0.35):
    """Contours whose lobes rotate a little from frame to frame, with their curvature (float32 values)."""
    for k in range(count):
        contour = blob(n, step * k)
        yield f32(ContourCurvature().process(contour).curvature), contour


def body_input(curvature, contour):
    return np.column_stack([curvature, contour])


def body_expected(result, rows):
    """The CHOP layout: minimums in channels 0-1, maximums in 2-3, one row per extremum in label order, zero padded."""
    out = np.zeros((rows, 4))
    for i, point in enumerate(list(result.minimums.values())[:rows]):
        out[i, 0:2] = point
    for i, point in enumerate(list(result.maximums.values())[:rows]):
        out[i, 2:4] = point
    return out

BODY_SETS = [pytest.param({}, {}, id="default"),
             pytest.param({"Minimumdistance": 8, "Numberofpoints": 3}, {"minimum_distance": 8, "number_of_points": 3}, id="mindist8-points3"),
             pytest.param({"Trackpoints": 0, "Numberofpoints": 7}, {"track_points": False, "number_of_points": 7}, id="untracked"),
             pytest.param({"Trackingdistance": 2.0}, {"tracking_distance": 2.0}, id="tracking-distance2")]


@pytest.mark.parametrize("pars, kwargs", BODY_SETS)
def test_body_parts_parity_over_a_sequence(plugin, pars, kwargs):
    node = plugin("BodyPartsFromCurvature")
    for k, v in pars.items():
        node.set(k, v)
    feature = BodyPartsFromCurvature(**kwargs)
    rows = pars.get("Numberofpoints", 5)
    for curvature, contour in body_frames():
        out = node.cook(body_input(curvature, contour))
        assert out.status_name == "OK" and out.data.shape == (rows, 4)
        assert_close(out.data, body_expected(feature.process(curvature, contour), rows))


def test_body_parts_reset_forgets_the_tracked_points(plugin):
    """The labels, hence the order of the rows, depend on the previous cooks; Reset makes the next cook a first one."""
    node = plugin("BodyPartsFromCurvature")
    frames = list(body_frames())
    for f in frames[:4]:
        node.cook(body_input(*f))
    tracked = node.cook(body_input(*frames[3])).data.copy()
    fresh = body_expected(BodyPartsFromCurvature().process(*frames[3]), 5)
    assert not np.allclose(tracked, fresh), "the tracked state has no effect on this data: the test would be vacuous"
    node.pulse("Reset")
    assert_close(node.cook(body_input(*frames[3])).data, fresh)


def test_body_parts_parameters_are_live(plugin):
    """Mindist, Pointsnum and Trackpoints are live in the core (adoptParams never resets): the tracked points stay."""
    node = plugin("BodyPartsFromCurvature")
    feature = BodyPartsFromCurvature()
    for i, f in enumerate(body_frames()):
        if i == 3:
            node.set("Minimumdistance", 4)
            feature.minimum_distance = 4
        out = node.cook(body_input(*f))
        assert_close(out.data, body_expected(feature.process(*f), 5), what=f"frame {i}")


def test_body_parts_edges(plugin):
    node = plugin("BodyPartsFromCurvature")
    curvature, contour = next(body_frames())
    out = node.cook(body_input(curvature, contour)[:, :2])
    assert out.status_name == "INVALID_INPUT" and out.warning and not out.data.any()
    assert node.cook(body_input(curvature, contour)).status_name == "OK"  # the node recovers


