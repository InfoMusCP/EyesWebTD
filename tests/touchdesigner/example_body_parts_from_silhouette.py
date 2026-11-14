"""Body Parts from Curvature on a real silhouette (run in the Textport of TouchDesigner).

    exec(open(r"<EyesWebTD>/tests/touchdesigner/example_body_parts_from_silhouette.py").read())
    build("/project1/mask")        # the TOP holding the silhouette mask: person white, background black

It builds /project1/ew_example_bpfc:

    outline (Script CHOP: the outline of the silhouette, tx / ty)
      -> curvature (Ewcontourcurvature) -> merge (curvature, tx, ty) -> parts (Ewbodypartsfromcurvature)

The outline is the boundary of the mask (Moore neighbour tracing), resampled at equal steps and smoothed: a closed
contour of Points samples, counter-clockwise, in units of the image width (x to the right, y up). Give it a mask of ONE
person without holes or specks (clean it with a Blur then a Threshold TOP). On a synthetic person with rounded limbs, arms
out, the 5 maxima are the head, both hands and both feet, and the minima the armpits, crotch and neck.

The Script CHOP has these parameters on its Outline page: Top (the mask), Threshold, Points, Smooth (the samples of the
moving average of the radius: raise it for a noisy mask) and Downsample (read every n-th pixel: speed). The maxima of the
curvature are the tips (head, hands, feet) and the minima the valleys (armpits, crotch). Raise Minimum Distance of the
`parts` node when the mask is noisy. Delete /project1/ew_example_bpfc afterwards.
"""
import td  # noqa: F401  (only available inside TouchDesigner)

CALLBACKS = '''
import numpy as np


_RING = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]  # (dx, dy): the 8 neighbours in order


def outline_from_mask(mask, points=200, smooth=5, downsample=2):
    """The outer outline of a boolean mask (row 0 at the bottom, as a TOP gives it) as closed, counter-clockwise (x, y).

    The boundary is followed pixel by pixel (Moore neighbour tracing) from the topmost pixel, then resampled at `points`
    equal steps along its length and smoothed by a circular moving average of `smooth` samples. x and y are in units of
    the image width (y up). Only the blob that holds the topmost pixel is followed: give a mask of one person."""
    small = np.pad(mask[::downsample, ::downsample], 1)
    rows, cols = np.nonzero(small)
    if len(rows) < 10:
        return None
    top = rows.max()                                             # the topmost row of the picture has the highest index
    start = (int(cols[rows == top].min()), int(top))             # its left neighbour is background
    path, cur, back = [start], start, 0                          # `back`: ring index of the background pixel we came from
    for _ in range(4 * small.size):
        for k in range(1, 9):
            index = (back + k) % 8
            nx, ny = cur[0] + _RING[index][0], cur[1] + _RING[index][1]
            if small[ny, nx]:
                break
        else:
            break                                                # an isolated pixel
        before = _RING[(index - 1) % 8]                          # the last background pixel checked, next to the new one
        back = _RING.index((cur[0] + before[0] - nx, cur[1] + before[1] - ny))
        cur = (nx, ny)
        if cur == start:
            break
        path.append(cur)
    xy = np.array(path, dtype=float)
    if len(xy) < 8:
        return None
    ring = np.vstack([xy, xy[:1]])
    length = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(ring, axis=0).T))])
    along = np.linspace(0, length[-1], points, endpoint=False)
    x, y = np.interp(along, length, ring[:, 0]), np.interp(along, length, ring[:, 1])
    if smooth > 1:
        k = int(smooth)
        kernel = np.ones(k) / k
        x = np.convolve(np.concatenate([x[-k:], x, x[:k]]), kernel, mode="same")[k:-k]
        y = np.convolve(np.concatenate([y[-k:], y, y[:k]]), kernel, mode="same")[k:-k]
    if 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) < 0:  # clockwise: reverse, so that tips are maxima
        x, y = x[::-1], y[::-1]
    return x / small.shape[1], y / small.shape[1]


def onSetupParameters(scriptOp):
    page = scriptOp.appendCustomPage("Outline")
    page.appendTOP("Top", label="Mask TOP")
    page.appendFloat("Threshold", label="Threshold")[0].default = 0.5
    page.appendInt("Points", label="Points")[0].default = 200
    page.appendInt("Smooth", label="Smooth")[0].default = 9
    page.appendInt("Downsample", label="Downsample")[0].default = 2
    return


def onCook(scriptOp):
    scriptOp.clear()
    top = scriptOp.par.Top.eval()
    points = max(16, int(scriptOp.par.Points))
    scriptOp.numSamples = points
    tx, ty = scriptOp.appendChan("tx"), scriptOp.appendChan("ty")
    if top is None:
        return
    image = top.numpyArray(delayed=False)
    mask = image[:, :, 0] > float(scriptOp.par.Threshold)
    outline = outline_from_mask(mask, points, int(scriptOp.par.Smooth), max(1, int(scriptOp.par.Downsample)))
    if outline is None:
        return
    tx.vals, ty.vals = list(outline[0]), list(outline[1])
    return
'''


def _create(parent, op_type, name):
    for candidate in (op_type, op_type + "CHOP"):
        try:
            return parent.create(candidate, name)
        except Exception:
            pass
    raise RuntimeError("type %s not found: is the plugin loaded?" % op_type)


def build(mask_top_path, parent_path="/project1"):
    mask = op(mask_top_path)  # noqa: F821  (TouchDesigner global)
    if mask is None:
        print("No TOP at %r: give the path of the TOP that holds the silhouette mask." % mask_top_path)
        return None
    parent = op(parent_path)  # noqa: F821
    if parent.op("ew_example_bpfc"):
        parent.op("ew_example_bpfc").destroy()
    box = parent.create(td.baseCOMP, "ew_example_bpfc")

    outline = box.create(td.scriptCHOP, "outline")
    outline.par.callbacks.eval().text = CALLBACKS  # the callbacks DAT that TouchDesigner made for the Script CHOP
    outline.par.Top = mask.path
    outline.cook(force=True)

    curvature = _create(box, "Ewcontourcurvature", "curvature")
    curvature.inputConnectors[0].connect(outline)

    merge = box.create(td.mergeCHOP, "merge")
    merge.inputConnectors[0].connect(curvature)  # first the curvature, then tx and ty
    merge.inputConnectors[1].connect(outline)

    parts = _create(box, "Ewbodypartsfromcurvature", "parts")
    parts.inputConnectors[0].connect(merge)
    parts.par.Numberofpoints = 6
    parts.par.Minimumdistance = 8
    parts.cook(force=True)

    print("outline: %d points, merge channels: %s (must be curvature, tx, ty)" % (outline.numSamples, [c.name for c in merge.chans()]))
    print("errors:", parts.errors() or "none", "| warnings:", parts.warnings() or "none")
    print("%-3s %8s %8s | %8s %8s   (units of the image width, y up)" % ("#", "min_x", "min_y", "max_x", "max_y"))
    for i in range(parts.numSamples):
        print("%-3d %8.3f %8.3f | %8.3f %8.3f" % (i, parts["min_x"][i], parts["min_y"][i], parts["max_x"][i], parts["max_y"][i]))
    return parts
