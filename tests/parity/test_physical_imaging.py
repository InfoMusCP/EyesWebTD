"""Parity of SilhouetteCentroids, SilhouetteBodyParts and Videogram (CHOP operators with a TOP input) with PyEyesWeb.

The images reach the operators as TOPs of the mock host (ewhost.Image: row 0 on top, 8-bit or float32), and the operators
read them with OP_TOPInput::downloadTexture, flipped so that row 0 is the top of the image, as in PyEyesWeb. Both sides see the
same pixels. The outputs that are images in PyEyesWeb are carried as follows (see the header of each operator):
  * SilhouetteCentroids / SilhouetteBodyParts: the numbers of `centroids` (the CHOP has no `normalized`: the user divides by
    the size of the image), `regions`, `is_found` as channels of one sample; the per-part `masks` have no CHOP form;
  * Videogram: the videogram image of shape (H, window, C) as `window` samples of H * C channels (channel h * C + c at sample s
    is image[h, s, c]; vertical mode: image[s, w, c]).
A centroid that is absent is NaN on both sides; the regions of parts that were not found are 0 on both sides.
"""
import numpy as np
import pytest

from conftest import assert_close
from ewhost import Image
from pyeyesweb.data_models.results import Status
from pyeyesweb.physical_signals import SilhouetteBodyParts, SilhouetteCentroids, Videogram

LABELS = ("center_of_gravity", "head", "left_shoulder", "left_elbow", "left_forearm", "left_hand", "right_shoulder", "right_elbow",
          "right_forearm", "right_hand", "left_knee", "left_foot", "right_knee", "right_foot")
PARTS = ("left_leg", "right_leg", "trunk", "left_arm", "right_arm", "head")  # left = smaller x


def par(label):
    """The parameter (toggle) of a part: first letter capital, then lower case, no separators."""
    return label.replace("_", "").capitalize()


# ---- silhouettes ------------------------------------------------------------------------------------------------------------
def figure(shift=0, arm_row=75, height=240, width=320, arm_half=80, leg_gap=13, lean=0):
    """A stick-like human mask (head, trunk, arms as a horizontal bar, two legs): bool (height, width), row 0 on top."""
    rows, cols = np.mgrid[:height, :width]
    c = 160 + shift
    body = (abs(cols - c - lean) <= 28) & (rows >= 60) & (rows <= 140)
    body |= ((cols - c) ** 2 / 18 ** 2 + (rows - 40) ** 2 / 22 ** 2 <= 1)
    body |= (abs(rows - arm_row) <= 7) & (cols >= c - arm_half) & (cols <= c + arm_half)
    body |= (abs(cols - (c - leg_gap)) <= 9) & (rows > 140) & (rows <= 225)
    body |= (abs(cols - (c + leg_gap)) <= 9) & (rows > 140) & (rows <= 225)
    return body


def blob(seed, height=120, width=90):
    """An irregular blob (no body shape at all): random rectangles, asymmetric."""
    rng = np.random.default_rng(seed)
    mask = np.zeros((height, width), dtype=bool)
    for _ in range(6):
        y, x = rng.integers(5, height - 30), rng.integers(5, width - 25)
        mask[y:y + rng.integers(8, 30), x:x + rng.integers(6, 25)] = True
    return mask


def u8(mask):
    return mask.astype(np.uint8) * 255


SILHOUETTES = {"figure": figure(), "arms_low": figure(shift=-20, arm_row=100, leg_gap=17, lean=6), "blob1": blob(1), "blob2": blob(2)}


def assert_top_invalid(out, reason=None):
    assert out.status_name == "INVALID_INPUT" and out.status == 3 and out.warning
    if reason:
        assert reason in out.reason
    assert not np.nan_to_num(out.data).any()


# ======================================================================================================== SilhouetteCentroids
def centroid_row(result):
    """PyEyesWeb centroids, flattened as the channels of the CHOP (the `normalized` of PyEyesWeb is left to the user)."""
    return np.asarray(result.centroids, float).ravel()


def centroids_parity(node, mask, **kw):
    feature = SilhouetteCentroids(**kw)
    expected = centroid_row(feature.process(u8(mask)))
    out = node.cook(tops={"Top": Image(u8(mask))})
    assert out.data.shape == (1, 28)
    assert_close(out.data[0], expected, what=str(kw))
    return out


def test_centroids_declaration(plugin):
    node = plugin("SilhouetteCentroids")
    assert (node.op_type, node.op_label) == ("Ewsilhouettecentroids", "EW L1 Silhouette Centroids")
    assert (node.min_inputs, node.max_inputs) == (0, 0)             # the TOP is the Top parameter: no input
    assert not [i for i in node.setup_issues if i.startswith("error")]
    out = node.cook(tops={"Top": Image(u8(figure()))})
    assert tuple(out.names) == tuple(SilhouetteCentroids._OUTPUTS.flat_names) and len(out.names) == 28
    assert out.names[0] == "centroids_center_of_gravity_x"
    assert out.num_samples == 1 and out.status_name == "OK" and out.warning == ""
    names = [p.name for p in node.params]
    assert {"Top", "Silhouette", "Filtercentroids", "Alpha", "Addintermediatecentroids", "Reset"} <= set(names)
    assert "Threshold" not in names                               # thresholding is left to the user (a Threshold TOP)
    assert [par(label) in names for label in LABELS] == [True] * 14
    assert node.param("Silhouette").default == "full" and node.param("Alpha").default == 0.75
    assert node.param("Silhouette").menu_names == ["full", "upper", "lower", "left", "right"]
    assert "Source" not in names                                  # not a sample-wise operator


@pytest.mark.parametrize("name", list(SILHOUETTES))
def test_centroids_default_parameters(plugin, name):
    centroids_parity(plugin("SilhouetteCentroids"), SILHOUETTES[name])


@pytest.mark.parametrize("silhouette", ["upper", "lower", "left", "right"])
@pytest.mark.parametrize("name", ["figure", "blob1"])
def test_centroids_silhouette_types(plugin, silhouette, name):
    node = plugin("SilhouetteCentroids")
    node.set("Silhouette", silhouette)
    centroids_parity(node, SILHOUETTES[name], silhouette=silhouette)


@pytest.mark.parametrize("name", ["figure", "arms_low", "blob2"])
def test_centroids_parts_and_intermediates(plugin, name):
    parts = ["head", "left_hand", "right_foot"]                 # hand needs elbow and forearm, which are computed but not output
    for intermediates in (False, True):
        node = plugin("SilhouetteCentroids")
        for label in LABELS:
            node.set(par(label), label in parts)
        node.set("Addintermediatecentroids", intermediates)
        out = centroids_parity(node, SILHOUETTES[name], parts=parts, add_intermediate_centroids=intermediates)
        assert np.isnan(out.data[0]).any()                       # the parts that were not asked for are NaN


def test_centroids_absent_centroids_are_nan_like_pyeyesweb(plugin):
    node = plugin("SilhouetteCentroids")
    for label in LABELS:
        node.set(par(label), label == "center_of_gravity")
    out = centroids_parity(node, SILHOUETTES["figure"], parts=["center_of_gravity"])
    assert not np.isnan(out.data[0, 0:2]).any() and np.isnan(out.data[0, 2:28]).all()
    assert out.status_name == "OK"


def test_centroids_filter_sequence_matches_pyeyesweb(plugin):
    node = plugin("SilhouetteCentroids")
    node.set("Filtercentroids", 1)
    node.set("Alpha", 0.4)
    feature = SilhouetteCentroids(filter_centroids=True, alpha=0.4)
    for k in range(12):
        mask = figure(shift=3 * k - 15, arm_row=60 + 4 * k)
        expected = centroid_row(feature.process(u8(mask)))
        assert_close(node.cook(tops={"Top": Image(u8(mask))}).data[0], expected, what=f"frame {k}")


def test_centroids_state_reset_and_parameter_changes(plugin):
    node = plugin("SilhouetteCentroids")
    node.set("Filtercentroids", 1)
    node.set("Alpha", 0.4)
    frames = [u8(figure(shift=4 * k - 20, arm_row=60 + 5 * k)) for k in range(8)]
    reference = SilhouetteCentroids(filter_centroids=True, alpha=0.4)
    for frame in frames[:4]:
        node.cook(tops={"Top": Image(frame)})
        reference.process(frame)
    # a live parameter (alpha) keeps the filters
    node.set("Alpha", 0.9)
    reference.alpha = 0.9
    assert_close(node.cook(tops={"Top": Image(frames[4])}).data[0], centroid_row(reference.process(frames[4])), what="alpha changed live")
    # Reset forgets them: the next frame passes through unfiltered, like a new feature
    node.pulse("Reset")
    fresh = SilhouetteCentroids(filter_centroids=True, alpha=0.9)
    assert_close(node.cook(tops={"Top": Image(frames[5])}).data[0], centroid_row(fresh.process(frames[5])), what="after Reset")
    assert node.cook(tops={"Top": Image(frames[6])}).dat("resets") == "1"
    # a structural parameter (silhouette) restarts the filters
    node.set("Silhouette", "upper")
    fresh = SilhouetteCentroids(filter_centroids=True, alpha=0.9, silhouette="upper")
    assert_close(node.cook(tops={"Top": Image(frames[7])}).data[0], centroid_row(fresh.process(frames[7])), what="silhouette changed")


def test_centroids_filter_off_has_no_memory(plugin):
    node = plugin("SilhouetteCentroids")
    a, b = u8(SILHOUETTES["figure"]), u8(SILHOUETTES["arms_low"])
    first = node.cook(tops={"Top": Image(b)}).data.copy()
    node.cook(tops={"Top": Image(a)})
    assert np.array_equal(node.cook(tops={"Top": Image(b)}).data, first, equal_nan=True)


def test_centroids_orientation_is_top_down_in_pixels(plugin):
    node = plugin("SilhouetteCentroids")
    mask = np.zeros((20, 30), np.uint8)
    mask[2:6, 20:24] = 255                                       # near the top, to the right
    out = node.cook(tops={"Top": Image(mask)})
    x, y = out.data[0, 0], out.data[0, 1]
    assert (x, y) == (21.0, 3.0)                                 # y = 3: counted from the TOP of the image


def test_centroids_input_forms_give_the_same_result(plugin):
    node = plugin("SilhouetteCentroids")
    mask = SILHOUETTES["figure"]
    reference = node.cook(tops={"Top": Image(u8(mask))}).data.copy()
    for image in (Image(mask), Image(mask.astype(np.float32)), Image(np.dstack([u8(mask)] * 3)),
                  Image(np.dstack([u8(mask), np.zeros_like(u8(mask)), np.zeros_like(u8(mask)), u8(mask)]))):
        assert np.array_equal(node.cook(tops={"Top": image}).data, reference, equal_nan=True)
    assert np.array_equal(node.cook(tops={"Top": Image(u8(mask))}).data, reference, equal_nan=True)


def test_centroids_statuses(plugin):
    node = plugin("SilhouetteCentroids")
    result = SilhouetteCentroids().process(np.zeros((10, 10), np.uint8))
    assert result.status == Status.INVALID_INPUT and result.reason == "no foreground pixels in the silhouette"
    out = node.cook(tops={"Top": Image(np.zeros((10, 10), np.uint8))})
    assert_top_invalid(out, result.reason)
    assert out.data.shape == (1, 28)
    assert_top_invalid(node.cook(), "no TOP")                      # nothing connected
    assert node.cook(tops={"Top": Image(u8(figure()))}).status_name == "OK"      # recovers on the next frame
    assert_top_invalid(node.cook(tops={"Top": Image(np.zeros((4, 4), np.float32) + np.float32(np.nan))}), "no foreground")   # NaN is no foreground


def test_centroids_invalid_frame_does_not_disturb_the_filters(plugin):
    node = plugin("SilhouetteCentroids")
    node.set("Filtercentroids", 1)
    node.set("Alpha", 0.5)
    feature = SilhouetteCentroids(filter_centroids=True, alpha=0.5)
    frames = [u8(figure(shift=5 * k)) for k in range(3)]
    blank = np.zeros((240, 320), np.uint8)
    for frame in (frames[0], blank, frames[1], blank, frames[2]):
        result = feature.process(frame)
        out = node.cook(tops={"Top": Image(frame)})
        if result.status == Status.OK:
            assert_close(out.data[0], centroid_row(result))
        else:
            assert out.status_name == "INVALID_INPUT"


def test_centroids_edges_do_not_crash(plugin):
    node = plugin("SilhouetteCentroids")
    for mask in (np.ones((1, 1), bool), np.ones((7, 5), bool), np.eye(9, dtype=bool), np.ones((300, 200), bool)):
        centroids_parity(node, mask)
        node.pulse("Reset")


# ========================================================================================================= SilhouetteBodyParts
def regions_row(result):
    return np.concatenate([np.asarray(result.regions, float).ravel(), np.asarray(result.is_found, float)])


def bodyparts_parity(node, mask, **kw):
    expected = regions_row(SilhouetteBodyParts(**kw).process(u8(mask)))
    out = node.cook(tops={"Top": Image(u8(mask))})
    assert out.data.shape == (1, 30)
    assert_close(out.data[0], expected, what=str(kw))
    return out


def test_bodyparts_declaration(plugin):
    node = plugin("SilhouetteBodyParts")
    assert (node.op_type, node.op_label) == ("Ewsilhouettebodyparts", "EW L1 Silhouette Body Parts")
    assert (node.min_inputs, node.max_inputs) == (0, 0)             # the TOP is the Top parameter: no input
    assert not [i for i in node.setup_issues if i.startswith("error")]
    out = node.cook(tops={"Top": Image(u8(figure()))})
    names = SilhouetteBodyParts._OUTPUTS.flat_names                 # the fixed outputs: regions and is_found (masks are images)
    assert tuple(out.names) == names and len(names) == 30 and not any(n.startswith("masks") for n in out.names)
    assert out.names[0] == "regions_left_leg_x" and out.names[24] == "is_found_left_leg"
    pnames = [p.name for p in node.params]
    assert {"Top", "Armpercentage", "Legssearch", "Legsoffset", "Armsminthreshold", "Armsmaxthreshold"} <= set(pnames)
    assert "Threshold" not in pnames
    assert all(par(p) in pnames for p in PARTS)
    assert "Reset" not in pnames and "Source" not in pnames        # a frame operator keeps nothing
    defaults = {p.name: p.default for p in node.params}
    assert (defaults["Armpercentage"], defaults["Legssearch"], defaults["Legsoffset"]) == (0.8, 0.5, 0.2)
    assert (defaults["Armsminthreshold"], defaults["Armsmaxthreshold"]) == (0.2, 0.5)


@pytest.mark.parametrize("name", list(SILHOUETTES))
def test_bodyparts_default_parameters(plugin, name):
    out = bodyparts_parity(plugin("SilhouetteBodyParts"), SILHOUETTES[name])
    if name == "figure":
        assert out.data[0, 24:].tolist() == [1.0] * 6               # all six parts found


@pytest.mark.parametrize("name", ["figure", "arms_low", "blob1"])
def test_bodyparts_non_default_parameters(plugin, name):
    cases = [dict(arm_percentage=0.6), dict(legs_search=0.3, legs_offset=0.4), dict(arms_min_threshold=0.1, arms_max_threshold=0.7),
             dict(arm_percentage=1.2), dict(arm_percentage=0.5, legs_search=0.7, legs_offset=0.1, arms_min_threshold=0.3, arms_max_threshold=0.4)]
    for kw in cases:
        node = plugin("SilhouetteBodyParts")
        for key, value in kw.items():
            node.set(key.replace("_", "").capitalize(), value)
        bodyparts_parity(node, SILHOUETTES[name], **kw)


@pytest.mark.parametrize("parts", [["head"], ["trunk", "left_arm"], ["right_leg", "left_leg", "head"], []])
def test_bodyparts_parts_selection(plugin, parts):
    node = plugin("SilhouetteBodyParts")
    for part in PARTS:
        node.set(par(part), part in parts)
    out = bodyparts_parity(node, SILHOUETTES["figure"], parts=parts)
    assert [bool(v) for v in out.data[0, 24:]] == [part in parts for part in PARTS]


def test_bodyparts_a_part_at_the_frame_border_is_found_like_pyeyesweb(plugin):
    # EyesWeb dropped a part touching the first column or row; it is kept now (final round D2), in both.
    node = plugin("SilhouetteBodyParts")
    out = bodyparts_parity(node, figure(shift=-140), )              # the left side of the body reaches column 0
    regions = out.data[0, :24].reshape(6, 4)
    assert (regions[:, 0] == 0).any() and all(out.data[0, 24 + slot] == 1 for slot in np.flatnonzero(regions[:, 0] == 0))


def test_bodyparts_is_stateless_and_follows_each_frame(plugin):
    node = plugin("SilhouetteBodyParts")
    first = node.cook(tops={"Top": Image(u8(SILHOUETTES["figure"]))}).data.copy()
    for name in ("blob1", "arms_low", "blob2", "figure"):
        bodyparts_parity(node, SILHOUETTES[name])
    assert np.array_equal(node.cook(tops={"Top": Image(u8(SILHOUETTES["figure"]))}).data, first)


def test_bodyparts_orientation_and_input_forms(plugin):
    node = plugin("SilhouetteBodyParts")
    mask = SILHOUETTES["figure"]
    reference = node.cook(tops={"Top": Image(u8(mask))}).data.copy()
    assert reference[0, 20 + 1] < 60                                # the head (columns 20..23 = head x, y, w, h): near the top
    flipped = node.cook(tops={"Top": Image(u8(mask[::-1]))}).data
    assert not np.array_equal(flipped, reference)                   # the image is not read upside down
    for image in (Image(mask), Image(mask.astype(np.float32)), Image(np.dstack([u8(mask)] * 3))):
        assert np.array_equal(node.cook(tops={"Top": image}).data, reference)
    assert np.array_equal(node.cook(tops={"Top": Image(u8(mask))}).data, reference)


def test_bodyparts_statuses(plugin):
    node = plugin("SilhouetteBodyParts")
    result = SilhouetteBodyParts().process(np.zeros((10, 10), np.uint8))
    assert result.status == Status.INVALID_INPUT and result.reason == "no foreground pixels in the silhouette"
    assert_top_invalid(node.cook(tops={"Top": Image(np.zeros((10, 10), np.uint8))}), result.reason)
    assert_top_invalid(node.cook(), "no TOP")
    assert node.cook(tops={"Top": Image(u8(figure()))}).status_name == "OK"


def test_bodyparts_edges_do_not_crash(plugin):
    node = plugin("SilhouetteBodyParts")
    for mask in (np.ones((1, 1), bool), np.ones((3, 40), bool), np.ones((40, 3), bool), np.eye(11, dtype=bool), np.ones((200, 150), bool)):
        bodyparts_parity(node, mask)


# =============================================================================================================== Videogram
def video(n, height=12, width=16, channels=None, seed=0, dtype=np.uint8):
    """Frames with a moving bright bar and noise: (n, H, W[, C]) 8-bit."""
    rng = np.random.default_rng(seed)
    shape = (n, height, width) + ((channels,) if channels else ())
    frames = rng.integers(0, 40, shape)
    for k in range(n):
        frames[k, (2 * k) % height, :] += 150
        frames[k, :, (3 * k) % width] += 60
    return np.clip(frames, 0, 255).astype(dtype)


def chop_image(out, frame_hw, channels, mode):
    """The CHOP output as the PyEyesWeb image (H, window, C) or (window, W, C)."""
    window = out.data.shape[0]
    bins = out.data.shape[1] // channels
    cube = out.data.reshape(window, bins, channels)               # sample, position, colour
    return cube.transpose(1, 0, 2) if mode == "horizontal" else cube


def videogram_run(node, frames, channels=1, **kw):
    """Feed the frames to the node and to PyEyesWeb, compare the image after every frame; the last CHOP output."""
    feature = Videogram(**kw)
    mode = kw.get("mode", "horizontal")
    out = None
    for k, frame in enumerate(frames):
        expected = feature.process(frame).videogram
        out = node.cook(Image(frame))
        got = chop_image(out, frame.shape[:2], channels, mode)
        assert got.shape == expected.shape, f"frame {k}: {got.shape} != {expected.shape}"
        assert np.array_equal(got, expected), f"frame {k}"
    return out


def configure(node, **kw):
    for key, value in kw.items():
        node.set({"end_of_image_mode": "Endofimagemode"}.get(key, key.capitalize()), value)


def test_videogram_declaration(plugin):
    node = plugin("Videogram")
    assert (node.op_type, node.op_label) == ("Ewvideogram", "EW L1 Videogram")
    assert (node.min_inputs, node.max_inputs) == (0, 1)
    assert not [i for i in node.setup_issues if i.startswith("error")]
    node.set("Window", 5)
    out = node.cook(Image(video(1)[0]))
    assert out.names == [f"videogram_{h}" for h in range(12)] and out.data.shape == (5, 12)
    names = [p.name for p in node.params]
    assert {"Top", "Window", "Mode", "Direction", "Endofimagemode", "Channels", "Reset"} <= set(names) and "Source" not in names
    assert node.param("Window").default == 500 and node.param("Mode").default == "horizontal"
    assert node.param("Direction").menu_names == ["left_to_right", "right_to_left"]
    assert node.param("Endofimagemode").menu_names == ["loop", "scroll"] and node.param("Channels").menu_names == ["gray", "rgb", "rgba"]
    out = node.cook(Image(video(1)[0]))
    assert out.status_name == "OK" and out.dat("write_position") == "2" and out.dat("frame_height") == "12"
    node.set("Mode", "vertical")
    assert node.cook(Image(video(1)[0])).names == [f"videogram_{w}" for w in range(16)]
    node.set("Channels", "rgb")
    assert node.cook(Image(video(1, channels=3)[0])).names[:4] == ["videogram_0_r", "videogram_0_g", "videogram_0_b", "videogram_1_r"]
    node.set("Channels", "rgba")
    assert node.cook(Image(video(1, channels=4)[0])).names[3] == "videogram_0_a"


@pytest.mark.parametrize("mode", ["horizontal", "vertical"])
@pytest.mark.parametrize("seed, size", [(0, (12, 16)), (1, (9, 5))])
def test_videogram_default_loop_over_a_wrapping_sequence(plugin, mode, seed, size):
    node = plugin("Videogram")
    node.set("Window", 7)
    node.set("Mode", mode)
    videogram_run(node, video(19, *size, seed=seed), window=7, mode=mode)       # 19 frames > 7 lines: the image wraps


@pytest.mark.parametrize("mode", ["horizontal", "vertical"])
@pytest.mark.parametrize("direction", ["left_to_right", "right_to_left"])
@pytest.mark.parametrize("end", ["loop", "scroll"])
def test_videogram_direction_and_end_of_image_mode(plugin, mode, direction, end):
    node = plugin("Videogram")
    configure(node, window=6, mode=mode, direction=direction, end_of_image_mode=end)
    videogram_run(node, video(15, seed=3), window=6, mode=mode, direction=direction, end_of_image_mode=end)


@pytest.mark.parametrize("channels, label", [(3, "rgb"), (4, "rgba")])
@pytest.mark.parametrize("mode", ["horizontal", "vertical"])
def test_videogram_colour_frames(plugin, channels, label, mode):
    node = plugin("Videogram")
    configure(node, window=5, mode=mode, channels=label)
    out = videogram_run(node, video(11, channels=channels, seed=4), channels=channels, window=5, mode=mode)
    assert out.data.shape[1] == (12 if mode == "horizontal" else 16) * channels


def test_videogram_gray_tops_and_float_tops(plugin):
    node = plugin("Videogram")
    node.set("Window", 5)
    frames = video(7, seed=5)
    feature = Videogram(window=5)
    for frame in frames:
        expected = feature.process(frame).videogram
        assert np.array_equal(chop_image(node.cook(Image(frame)), frame.shape, 1, "horizontal"), expected)
    # a float TOP is read as 8-bit: v * 255 rounded
    node.pulse("Reset")
    feature = Videogram(window=5)
    for frame in frames:
        as_float = (frame / 255.0).astype(np.float32)
        expected = feature.process(np.round(as_float * np.float32(255)).astype(np.uint8)).videogram
        assert np.array_equal(chop_image(node.cook(Image(as_float)), frame.shape, 1, "horizontal"), expected)


def test_videogram_gray_tops_read_as_colour(plugin):
    node = plugin("Videogram")
    configure(node, window=4, channels="rgb")
    frames = video(6, seed=6)
    feature = Videogram(window=4)
    for frame in frames:
        expected = feature.process(np.dstack([frame] * 3)).videogram
        assert np.array_equal(chop_image(node.cook(Image(frame)), frame.shape, 3, "horizontal"), expected)


def test_videogram_orientation_is_top_down(plugin):
    node = plugin("Videogram")
    node.set("Window", 2)
    frame = np.zeros((6, 4), np.uint8)
    frame[1, :] = 80                                              # only row 1, counted from the top
    out = node.cook(Image(frame))
    assert out.data[0].tolist() == [0, 80, 0, 0, 0, 0]            # channel h = row h of the frame (the mean of the row)
    assert out.data[1].tolist() == [0] * 6                        # the second line is not written yet


def test_videogram_state_reset_and_parameter_changes(plugin):
    node = plugin("Videogram")
    node.set("Window", 6)
    frames = video(14, seed=7)
    feature = Videogram(window=6)
    for frame in frames[:5]:
        feature.process(frame)
        out = node.cook(Image(frame))
    assert out.dat("write_position") == "5"
    # live parameters keep the image
    node.set("Direction", "right_to_left")
    node.set("Endofimagemode", "scroll")
    feature.direction, feature.end_of_image_mode = "right_to_left", "scroll"
    out = node.cook(Image(frames[5]))
    assert np.array_equal(chop_image(out, frames[5].shape, 1, "horizontal"), feature.process(frames[5]).videogram)
    # Reset clears it
    node.pulse("Reset")
    fresh = Videogram(window=6, direction="right_to_left", end_of_image_mode="scroll")
    out = node.cook(Image(frames[6]))
    assert np.array_equal(chop_image(out, frames[6].shape, 1, "horizontal"), fresh.process(frames[6]).videogram)
    assert out.dat("resets") == "1"
    # structural parameters restart it
    node.set("Window", 4)
    fresh = Videogram(window=4, direction="right_to_left", end_of_image_mode="scroll")
    out = node.cook(Image(frames[7]))
    assert out.data.shape == (4, 12)
    assert np.array_equal(chop_image(out, frames[7].shape, 1, "horizontal"), fresh.process(frames[7]).videogram)
    node.set("Mode", "vertical")
    fresh = Videogram(window=4, mode="vertical", direction="right_to_left", end_of_image_mode="scroll")
    out = node.cook(Image(frames[8]))
    assert np.array_equal(chop_image(out, frames[8].shape, 1, "vertical"), fresh.process(frames[8]).videogram)


def test_videogram_frame_size_change_restarts_with_a_reason(plugin):
    node = plugin("Videogram")
    node.set("Window", 5)
    feature = Videogram(window=5)
    small, big = video(4, 6, 8, seed=8), video(3, 10, 12, seed=9)
    for frame in small:
        feature.process(frame)
        node.cook(Image(frame))
    result = feature.process(big[0])
    out = node.cook(Image(big[0]))
    assert result.status == Status.OK and result.reason == "frame size changed: videogram restarted"
    assert out.status_name == "OK" and out.reason == result.reason and out.warning == ""
    assert np.array_equal(chop_image(out, big[0].shape, 1, "horizontal"), result.videogram)
    for frame in big[1:]:
        out = node.cook(Image(frame))
        assert np.array_equal(chop_image(out, frame.shape, 1, "horizontal"), feature.process(frame).videogram)
        assert out.reason == ""                                     # only the first frame of the new size carries the reason


def test_videogram_black_frames_and_edges(plugin):
    node = plugin("Videogram")
    node.set("Window", 3)
    out = node.cook(Image(np.zeros((5, 4), np.uint8)))
    assert out.status_name == "OK" and not out.data.any()          # a line of a black frame is 0
    for shape in ((1, 1), (1, 9), (9, 1)):
        videogram_run(plugin("Videogram"), [np.full(shape, 200, np.uint8), np.ones(shape, np.uint8)], window=500)


def test_videogram_default_window_is_500_samples(plugin):
    node = plugin("Videogram")
    out = node.cook(Image(video(1, 8, 8)[0]))
    assert out.data.shape == (500, 8) and node.param("Window").clamp_min and node.param("Window").minimum == 1


def test_videogram_statuses(plugin):
    node = plugin("Videogram")
    node.set("Window", 4)
    assert_top_invalid(node.cook(), "no TOP")
    assert node.cook(Image(video(1)[0])).status_name == "OK"
    assert_top_invalid(node.cook(), "no TOP")                      # an invalid cook does not break the state
    out = node.cook(Image(video(2)[1]))
    assert out.status_name == "OK" and out.dat("write_position") == "2"
    assert node.cook(tops={"Top": Image(video(1)[0])}).status_name == "OK"
