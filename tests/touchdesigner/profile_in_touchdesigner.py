"""Cook time of the Silhouette operators inside TouchDesigner (run in the Textport).

    exec(open(r"<EyesWebTD>/tests/touchdesigner/profile_in_touchdesigner.py").read())
    profile("/project1/mask_top")          # the TOP holding the silhouette, at the resolution you use

It creates the two operators next to the TOP, forces them to cook for `frames` frames and prints the mean CPU time of each
(`cpuCookTime`, in ms, which includes the readback of the image from the GPU) next to the time of the TOP itself. Delete
/project1/ew_profile afterwards.
"""
import td  # noqa: F401  (only available inside TouchDesigner)


def profile(top_path, frames=120):
    top = op(top_path)  # noqa: F821  (TouchDesigner global)
    if top is None:
        found = [o.path for o in op("/").findChildren(type=td.TOP, depth=3)][:30]  # noqa: F821
        print("No operator at %r. Use the path of a TOP, for example one of:" % top_path)
        for path in found:
            print("   ", path)
        return
    parent = top.parent()
    if parent.op("ew_profile"):
        parent.op("ew_profile").destroy()
    box = parent.create(td.baseCOMP, "ew_profile")
    nodes = {}
    for name in ("Ewsilhouettecentroids", "Ewsilhouettebodyparts"):
        node = box.create(name + "CHOP" if not hasattr(td, name) else name, name)
        node.par.Top = top.path
        nodes[name] = node
    print("TOP %s: %dx%d" % (top.path, top.width, top.height))
    totals = {name: 0.0 for name in nodes}
    for _ in range(frames):
        for name, node in nodes.items():
            node.cook(force=True)
            totals[name] += node.cpuCookTime
    for name in nodes:
        print("%-26s %.3f ms per cook (CPU, includes the readback)" % (name, totals[name] / frames))
    print("frame budget at 60 fps: 16.7 ms")
