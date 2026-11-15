"""Builds the EyesWeb palette inside TouchDesigner: one container per layer with one instance of each installed operator,
and the presets (small networks) in a container of their own. Save the result as EyesWeb.tox (right click > Save
Component .tox...) and add it to the palette.

Run it in TouchDesigner, in a Text DAT or the Textport, after the plugins are installed (the operators must appear in the
OP Create dialog):

    exec(open(r"<package>/palette/build_palette.py").read()); build(op("/project1"))

Not run outside TouchDesigner. How a custom operator is created from Python (the name of its type) is the part to check
first: build() tries the type name as it is, with 'CHOP' appended and the class in td, and reports the operators that it
could not create.
"""
import td  # noqa: F401  (only available inside TouchDesigner)

# layer folder -> (container name, order of the conceptual model)
LAYERS = [
    ("physical_signals", "L1_physical_signals"),
    ("low_level", "L2_low_level"),
    ("mid_level", "L3_mid_level"),
    ("high_level", "L4_high_level"),
    ("analysis_primitives", "AP_analysis_primitives"),
]

# Presets: name -> (note, [(node name, operator type, {parameter: value}), ...]); each node is wired to the previous one.
# 'null' is a Null CHOP that stands for the input to connect (no operator of the plugin).
PRESETS = {
    "pose_to_kinetic_energy": (
        "Connect a joint-major position CHOP (x, y, z per joint, e.g. the 99 channels of the MediaPipe pose) to 'pose'.",
        [("pose", "null", {}), ("energy", "Ewkineticenergy", {"Dims": 3, "Inputmode": "position"})],
    ),
    "joint_to_kinematics": (
        "Connect ONE joint (3 channels) to 'joint': the operators take a single trajectory. Use a Select CHOP to pick it.",
        [("joint", "null", {}), ("kinematics", "Ewkinematics", {})],
    ),
}


def _installed():
    """(layer, operator type) of every operator, from operators.txt next to this script (written by the build)."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "operators.txt")
    with open(path) as f:
        return [tuple(line.split()) for line in f if line.strip()]


def _create(parent, op_type, name):
    for candidate in (op_type, op_type + "CHOP"):
        try:
            return parent.create(candidate, name)
        except Exception:
            pass
    cls = getattr(td, op_type + "CHOP", None) or getattr(td, op_type, None)
    if cls is not None:
        return parent.create(cls, name)
    raise RuntimeError(f"cannot create {op_type}")


def build(parent):
    """Create the palette under `parent` and return the container."""
    root = parent.create(td.baseCOMP, "EyesWeb")
    failed = []
    containers = {layer: root.create(td.baseCOMP, name) for layer, name in LAYERS}
    for layer, op_type in _installed():
        try:
            _create(containers[layer], op_type, op_type)
        except Exception as e:
            failed.append(f"{op_type}: {e}")
    presets = root.create(td.baseCOMP, "presets")
    for name, (note, nodes) in PRESETS.items():
        box = presets.create(td.baseCOMP, name)
        box.comment = note
        previous = None
        for node_name, op_type, pars in nodes:
            node = box.create(td.nullCHOP, node_name) if op_type == "null" else _create(box, op_type, node_name)
            for par, value in pars.items():
                getattr(node.par, par).val = value
            if previous is not None:
                previous.outputConnectors[0].connect(node)
            previous = node
    for layer, container in containers.items():
        container.layout()
    root.layout()
    if failed:
        print("Operators that could not be created (is the plugin loaded?):\n  " + "\n  ".join(failed))
    return root
