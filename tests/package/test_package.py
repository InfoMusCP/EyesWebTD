"""Checks of the built package (<build>/Plugins/EyesWeb, or the Plugins/EyesWeb of an installed package) that need no
TouchDesigner: every DLL declares the operator that its name, its layer folder and the VERSION file say it is, and, when
PyEyesWeb is importable, the operators and the PyEyesWeb catalog agree (same features, same layers).

Environment: EW_TD_PLUGINS = the directory with <layer>/Ew_<Feature>CHOP.dll (as for the other tests).
"""
import os
import re
from pathlib import Path

import pytest

import ewhost
from ewhost import Chop, HostError

ROOT = Path(__file__).resolve().parents[2]  # EyesWebTD/
LAYER_PREFIX = {"physical_signals": "L1", "low_level": "L2", "mid_level": "L3", "high_level": "L4", "analysis_primitives": "AP"}
# PyEyesWeb classes that are not features an operator can wrap
NOT_OPERATORS = {"MassSpringModel"}  # the model data type that the GenericModel features take
# operators of PyEyesWeb utility classes that the catalog does not list
NOT_IN_CATALOG = {("physical_signals", "TimeWindowSynchronizer")}


@pytest.fixture(scope="module")
def dlls():
    env = os.environ.get("EW_TD_PLUGINS")
    if not env:
        pytest.skip("EW_TD_PLUGINS is not set (the directory <build>/Plugins/EyesWeb that holds <layer>/*.dll)")
    try:
        ewhost.host_library_path()
    except HostError as e:
        pytest.skip(str(e))
    found = sorted(Path(env).glob("*/Ew_*CHOP.dll"))
    assert found, f"no operator DLL under {env}"
    return found


@pytest.fixture(scope="module")
def operators(dlls):
    nodes = {}
    for dll in dlls:
        with Chop(dll) as node:
            nodes[dll] = dict(type=node.op_type, label=node.op_label, author=node.author_email, api=node.api_version,
                              major=node.major_version, minor=node.minor_version)
    return nodes


def test_parameter_names(dlls):
    """TouchDesigner custom parameter names: a capital followed by lowercase letters and digits."""
    bad = []
    for dll in dlls:
        with Chop(dll) as node:
            bad += [f"{node.op_type}.{p.name}" for p in node.params if not re.fullmatch(r"[A-Z][a-z0-9]*", p.name)]
    assert not bad, bad


def feature_name(dll: Path) -> str:
    return re.fullmatch(r"Ew_(.+)CHOP\.dll", dll.name).group(1)


def test_layout_matches_the_sources(dlls):
    """One DLL per source file of chops/<layer>/, in the folder of its layer, and nothing else."""
    built = {(d.parent.name, feature_name(d)) for d in dlls}
    sources = {(p.parent.name, p.name[:-len("CHOP.cpp")]) for p in (ROOT / "chops").glob("*/*CHOP.cpp")}
    assert built == sources


def test_names_labels_and_layers(dlls, operators):
    for dll in dlls:
        info = operators[dll]
        layer, name = dll.parent.name, feature_name(dll)
        assert layer in LAYER_PREFIX, f"{dll}: unknown layer folder"
        assert info["type"] == "Ew" + name.lower(), dll.name
        assert re.fullmatch(r"[A-Z][a-z0-9]+", info["type"]), f"{info['type']} is not a valid TouchDesigner operator type"
        assert info["label"].startswith(f"EW {LAYER_PREFIX[layer]} "), f"{dll.name}: label '{info['label']}' is not in layer {layer}"
        assert re.sub(r"[^a-z0-9]", "", info["label"].lower()) == f"ew{LAYER_PREFIX[layer]}{name}".lower(), dll.name
    types = [i["type"] for i in operators.values()]
    assert len(types) == len(set(types)), "two operators with the same type"


def test_metadata_and_version(operators):
    major, minor, _ = (int(x) for x in (ROOT / "VERSION").read_text().strip().split("."))
    for dll, info in operators.items():
        assert info["author"] == "cp.infomus@gmail.com", dll.name
        assert (info["major"], info["minor"]) == (major, minor), f"{dll.name}: version {info['major']}.{info['minor']}"
    assert len({i["api"] for i in operators.values()}) == 1, "operators built against different API versions"


def test_matches_the_pyeyesweb_catalog(dlls):
    try:
        from pyeyesweb.catalog import catalog
        features = catalog()
    except Exception as e:  # PyEyesWeb or its compiled core is not available
        pytest.skip(f"PyEyesWeb catalog not available: {e}")
    expected = {(f.layer.package.rsplit(".", 1)[-1], f.name) for f in features if f.name not in NOT_OPERATORS}
    built = {(d.parent.name, feature_name(d)) for d in dlls}
    assert built - expected - NOT_IN_CATALOG == set(), "operators without a PyEyesWeb feature in that layer"
    assert expected - built == set(), "PyEyesWeb features without an operator"
