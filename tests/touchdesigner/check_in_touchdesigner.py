"""Check of the installed operators inside TouchDesigner (the other tests use a host emulator).

Run it in the Textport of TouchDesigner after installing the plugins (the DLLs of Plugins/ in
%USERPROFILE%\\Documents\\Derivative\\Plugins, then restart TouchDesigner):

    exec(open(r"<EyesWebTD>/tests/touchdesigner/check_in_touchdesigner.py").read())
    check(r"<package>/palette/operators.txt")

For every operator of operators.txt it creates a node in /project1/ew_check, feeds it a noise input of the right kind (a
CHOP with the channels the operator needs, or a noise TOP for the image operators), cooks it, and prints one line: created,
channels, samples, NaN values, errors and warnings. A warning such as INVALID_INPUT or WARMING_UP is expected for some
operators on random input; a failure to create, a crash or an error is not. The network is left in place for inspection;
delete /project1/ew_check afterwards.
"""
import math

import td  # noqa: F401  (only available inside TouchDesigner)

# channels of the noise input; operators not listed take 3 channels (one point x, y, z)
CHANNELS = {
    "Ewbinarypulsesregularity": 1, "Ewscalarpeakdetector": 1, "Ewsampleentropy": 1, "Ewmultiscaleentropy": 2,
    "Ewperiodicity": 1, "Ewrarity": 2, "Ewgesturesegmenter": 1, "Ewensembledominance": 3, "Ewhitcelldetector": 2,
    "Ewphaselockingvalue": 2, "Eweventsynchronization": 2, "Eweventsynchronizationmecs": 4,
    "Ewpartialrecurrencesynchronization": 3, "Ewcontourcurvature": 2, "Ewbodypartsfromcurvature": 2,
    "Ewkineticenergy": 9, "Ewsymmetry": 15, "Ewpointsdensity": 9, "Ewboundingboxfilledarea": 12,
    "Ewellipsoidsphericity": 9, "Ewequilibrium": 9, "Ewtrianglesymmetry": 6, "Ewdirectness": 3,
    "Ewspectralarclength": 1, "Ewlogdimensionlessjerk": 1, "Ewsubmovementcount": 1,
}
IMAGE_OPERATORS = {"Ewsilhouettecentroids", "Ewsilhouettebodyparts", "Ewvideogram"}
TWO_INPUTS = {"Ewcrossrecurrenceplot", "Ewtimewindowsynchronizer"}
SAMPLES = 200


def _create(parent, op_type, name):
    for candidate in (op_type, op_type + "CHOP"):
        try:
            return parent.create(candidate, name)
        except Exception:
            pass
    cls = getattr(td, op_type + "CHOP", None) or getattr(td, op_type, None)
    if cls is None:
        raise RuntimeError("type not found: is the plugin loaded?")
    return parent.create(cls, name)


def _noise_chop(parent, name, channels):
    noise = parent.create(td.noiseCHOP, name)
    noise.par.channelname = "chan[1-%d]" % channels
    for par, value in (("start", 0), ("end", SAMPLES - 1), ("amp", 0.5), ("offset", 0.5)):
        try:
            getattr(noise.par, par).val = value
        except Exception:
            pass
    return noise


def _values(node):
    values = []
    for channel in node.chans():
        values.extend(channel.vals)
    return values


def check(operators_txt, parent_path="/project1"):
    """Create, feed and cook every operator of `operators_txt`; print a report and return the lines with a problem."""
    parent = op(parent_path)  # noqa: F821  (TouchDesigner global)
    if parent.op("ew_check"):
        parent.op("ew_check").destroy()
    box = parent.create(td.baseCOMP, "ew_check")
    with open(operators_txt) as f:
        operators = [line.split() for line in f if line.strip() and not line.startswith("#")]
    problems = []
    print("%-36s %-8s %6s %7s %4s  %s" % ("operator", "created", "chans", "samples", "NaN", "errors / warnings"))
    for layer, op_type in operators:
        try:
            node = _create(box, op_type, op_type)
        except Exception as e:
            line = "%-36s %-8s %s" % (op_type, "NO", e)
            print(line)
            problems.append(line)
            continue
        try:
            if op_type in IMAGE_OPERATORS:
                image = box.create(td.noiseTOP, op_type + "_image")
                if hasattr(node.par, "Top"):
                    node.par.Top = image.path
                else:
                    image.outputConnectors[0].connect(node)
            else:
                source = _noise_chop(box, op_type + "_in", CHANNELS.get(op_type, 3))
                for index in range(2 if op_type in TWO_INPUTS else 1):
                    source.outputConnectors[0].connect(node.inputConnectors[index])
            node.cook(force=True)
            values = _values(node)
            nans = sum(1 for v in values if isinstance(v, float) and math.isnan(v))
            messages = "; ".join(m for m in (node.errors(), node.warnings()) if m)
            line = "%-36s %-8s %6d %7d %4d  %s" % (op_type, "yes", node.numChans, node.numSamples, nans, messages)
            print(line)
            if node.errors() or node.numChans == 0:
                problems.append(line)
        except Exception as e:
            line = "%-36s %-8s cook failed: %s" % (op_type, "yes", e)
            print(line)
            problems.append(line)
    print("\n%d operators, %d with a problem" % (len(operators), len(problems)))
    return problems
