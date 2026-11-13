"""Setup of the package tests: finds ewhost and, when available, PyEyesWeb with its compiled core (as tests/parity)."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # the workspace that holds EyesWebTD, PyEyesWeb and EyesWebCore
for path in (HERE.parent / "host", ROOT / "PyEyesWeb", Path(os.environ.get("EYESWEB_CORE_PATH", ROOT / "EyesWebCore" / "build" / "Release"))):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
