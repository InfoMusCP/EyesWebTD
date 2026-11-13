"""Shared setup of the parity tests: the CHOP operators cooked in the mock host against the PyEyesWeb features.

Environment (see tests/host/README.md): EW_TD_PLUGINS = <build>/Plugins/EyesWeb (the built operator DLLs). PyEyesWeb and
the compiled core module are found next to this repository (PyEyesWeb/, EyesWebCore/build/Release/) or through
EYESWEB_CORE_PATH.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # the workspace that holds EyesWebTD, PyEyesWeb and EyesWebCore
for path in (HERE.parent / "host", ROOT / "PyEyesWeb", Path(os.environ.get("EYESWEB_CORE_PATH", ROOT / "EyesWebCore" / "build" / "Release"))):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ewhost import Chop, Signal  # noqa: E402  (after the path set-up)


# Operators of the features held back from the first release (PyEyesWeb `released=False`): not built.
HELD_BACK = {"Harmonicity", "MotionNoiseDetector", "Suddenness", "SuddennessImpulsivity", "ContractionImpulsivity",
             "PositionDependingPotentials", "RegionDependingPotentials", "NonlinearInterdependence",
             "SpikeSynchronization"}


def _plugin_dir() -> Path:
    value = os.environ.get("EW_TD_PLUGINS")
    if not value:
        pytest.skip("EW_TD_PLUGINS is not set (directory with <layer>/Ew_<Name>CHOP.dll)", allow_module_level=True)
    return Path(value)


@pytest.fixture
def plugin():
    """plugin("Directness") -> a fresh node of the operator Ew_DirectnessCHOP (state is per node)."""
    nodes = []

    def make(name: str) -> Chop:
        matches = list(_plugin_dir().glob(f"*/Ew_{name}CHOP.dll"))
        if not matches and name in HELD_BACK:
            pytest.skip(f"{name}: held back from the release, its operator is not built (chops/_held_back)")
        assert matches, f"no operator DLL for {name} under {_plugin_dir()}"
        node = Chop(matches[0])
        nodes.append(node)
        return node

    yield make
    for node in nodes:
        node.close()


@pytest.fixture
def rng():
    return np.random.default_rng(12345)


def assert_close(actual, expected, rtol=1e-4, atol=1e-5, what=""):
    """float32 CHOP output against a float64 PyEyesWeb value: equal NaNs, otherwise close."""
    actual = np.asarray(actual, dtype=float)
    expected = np.asarray(expected, dtype=float)
    assert actual.shape == expected.shape, f"{what} shape {actual.shape} != {expected.shape}"
    np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True, err_msg=what)


__all__ = ["Signal", "assert_close"]
