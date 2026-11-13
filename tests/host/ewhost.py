"""Python wrapper of the mock TouchDesigner host (ew_td_host.dll): cook an EyesWebTD CHOP DLL on numpy data.

    from ewhost import Chop, Signal, Image
    chop = Chop("Plugins/EyesWeb/low_level/Ew_DirectnessCHOP.dll")
    out = chop.cook(xy)                 # xy: float32 (samples, channels)
    out = chop.cook(Image(mask))        # a TOP input: mask uint8 / float32 (H, W[, C]), row 0 on top
    out.data, out.names, out.warning, out.info, out.status_name

Only numpy is needed. See README.md for what the host mimics and where it differs from TouchDesigner.
"""
from __future__ import annotations

import ctypes as C
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

ABI_VERSION = 1

_KINDS = {0: "float", 1: "int", 2: "toggle", 3: "pulse", 4: "string", 5: "menu"}
_CODE_OK, _CODE_FAULT, _CODE_HOST = 0, 1, 2


class HostError(RuntimeError):
    """The mock host could not do what was asked (load failure, bad argument, unknown parameter)."""


class OperatorFault(HostError):
    """The operator crashed or let a C++ exception escape: a defect of the operator, the host survived."""


class HostUnsupported(HostError):
    """The operator used the host API in a way the host cannot serve (undeclared parameter, unimplemented
    OP_Inputs function, impossible output shape). The message says what."""


class _ParamInfo(C.Structure):
    _fields_ = [("kind", C.c_int32), ("size", C.c_int32), ("num_menu", C.c_int32), ("reserved", C.c_int32),
                ("default", C.c_double * 4), ("min", C.c_double * 4), ("max", C.c_double * 4),
                ("slider_min", C.c_double * 4), ("slider_max", C.c_double * 4),
                ("clamp_min", C.c_int32 * 4), ("clamp_max", C.c_int32 * 4)]


class _Input(C.Structure):
    _fields_ = [("connected", C.c_int32), ("channels", C.c_int32), ("samples", C.c_int32), ("reserved", C.c_int32),
                ("sample_rate", C.c_double), ("data", C.POINTER(C.c_float)), ("names", C.POINTER(C.c_char_p))]


class _CookInfo(C.Structure):
    _fields_ = [("num_channels", C.c_int32), ("num_samples", C.c_int32), ("sample_rate", C.c_double),
                ("start_index", C.c_double), ("timeslice", C.c_int32), ("output_declared", C.c_int32),
                ("input_match_index", C.c_int32), ("cook_count", C.c_int32)]


_lib_cache: dict[str, C.CDLL] = {}


def host_library_path() -> Path:
    """The ew_td_host.dll to use: EW_TD_HOST, else next to the build tree of EW_TD_PLUGINS (<build>/Release/...)."""
    env = os.environ.get("EW_TD_HOST")
    if env:
        return Path(env)
    plugins = os.environ.get("EW_TD_PLUGINS")
    if plugins:
        build = Path(plugins).resolve().parents[1]
        for config in ("Release", "RelWithDebInfo", "MinSizeRel", "Debug", "."):
            candidate = build / config / "ew_td_host.dll"
            if candidate.exists():
                return candidate
    raise HostError("ew_td_host.dll not found: set EW_TD_HOST to its path (or EW_TD_PLUGINS to <build>/Plugins/EyesWeb)")


def _load_library(path: Optional[os.PathLike] = None) -> C.CDLL:
    path = str(Path(path) if path else host_library_path())
    lib = _lib_cache.get(path)
    if lib is not None:
        return lib
    lib = C.CDLL(path)
    p, s, i, d, f = C.c_void_p, C.c_char_p, C.c_int, C.c_double, C.c_float
    sigs = {
        "ewh_abi_version": (i, []),
        "ewh_open": (p, [s, C.c_char_p, i]),
        "ewh_close": (None, [p]),
        "ewh_last_error": (s, [p]),
        "ewh_plugin_text": (s, [p, i]),
        "ewh_plugin_inputs": (i, [p, C.POINTER(i), C.POINTER(i)]),
        "ewh_plugin_version": (i, [p, C.POINTER(i), C.POINTER(i), C.POINTER(i)]),
        "ewh_reset_instance": (i, [p]),
        "ewh_param_count": (i, [p]),
        "ewh_param_info": (i, [p, i, C.POINTER(_ParamInfo)]),
        "ewh_param_text": (s, [p, i, i]),
        "ewh_param_menu_name": (s, [p, i, i]),
        "ewh_param_menu_label": (s, [p, i, i]),
        "ewh_setup_issues": (s, [p]),
        "ewh_set_number": (i, [p, s, i, d]),
        "ewh_set_string": (i, [p, s, s]),
        "ewh_pulse": (i, [p, s]),
        "ewh_get_number": (i, [p, s, i, C.POINTER(d)]),
        "ewh_get_string": (s, [p, s]),
        "ewh_param_enabled": (i, [p, s]),
        "ewh_cook": (i, [p, C.POINTER(_Input), i, d, i, d, f]),
        "ewh_result_info": (i, [p, C.POINTER(_CookInfo)]),
        "ewh_result_data": (i, [p, C.POINTER(f), i]),
        "ewh_result_name": (s, [p, i]),
        "ewh_result_warning": (s, [p]),
        "ewh_result_error": (s, [p]),
        "ewh_result_popup": (s, [p]),
        "ewh_info_chop_count": (i, [p]),
        "ewh_info_chop_name": (s, [p, i]),
        "ewh_info_chop_value": (f, [p, i]),
        "ewh_info_dat_size": (i, [p, C.POINTER(i), C.POINTER(i)]),
        "ewh_info_dat_cell": (s, [p, i, i]),
    }
    for name, (res, args) in sigs.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    if lib.ewh_abi_version() != ABI_VERSION:
        raise HostError(f"{path}: ABI version {lib.ewh_abi_version()}, ewhost.py expects {ABI_VERSION}")
    _lib_cache[path] = lib
    return lib


_FIELD_INDEX = {"x": 0, "y": 1, "z": 2}


def _text(raw: Optional[bytes]) -> str:
    return raw.decode("utf-8", "replace") if raw else ""


@dataclass
class Param:
    """A parameter as declared by setupParameters."""
    name: str
    kind: str                      # 'float' | 'int' | 'toggle' | 'pulse' | 'string' | 'menu'
    default: object                # number, bool-like int, str; menu: the item name; pulse: None
    label: str
    page: str
    menu: list[tuple[str, str]] = field(default_factory=list)  # (name, label) of a menu
    size: int = 1
    minimum: float = 0.0
    maximum: float = 1.0
    clamp_min: bool = False
    clamp_max: bool = False
    slider_min: float = 0.0
    slider_max: float = 1.0

    @property
    def menu_names(self) -> list[str]:
        return [n for n, _ in self.menu]


@dataclass
class Signal:
    """An input: float data (samples, channels) (1-D is one channel), optional channel names and sample rate."""
    data: np.ndarray
    names: Optional[Sequence[str]] = None
    sample_rate: Optional[float] = None

    def __post_init__(self):
        a = np.asarray(self.data)
        if a.ndim == 1:
            a = a[:, None]
        if a.ndim != 2:
            raise ValueError("input data must be (samples, channels) or 1-D")
        self.data = a
        if self.names is not None and len(self.names) != a.shape[1]:
            raise ValueError(f"{len(self.names)} names for {a.shape[1]} channels")


class Image:
    """An input that is a TOP: an image `data` of shape (H, W) or (H, W, C) with C = 1, 2, 3 or 4, row 0 at the top (as a
    numpy array or a video frame holds it). uint8 is 8-bit fixed point (0-255 is 0.0-1.0), a bool array is a 0 / 255 mask,
    floating point is a 32-bit float texture (nominal 0-1). The operator reads it through OP_TOPInput::downloadTexture; the
    host converts to the pixel format it asks for and flips the rows when it asks for verticalFlip (see README.md)."""

    def __init__(self, data):
        a = np.asarray(data)
        if a.ndim == 2:
            a = a[:, :, None]
        if a.ndim != 3 or not 1 <= a.shape[2] <= 4 or a.shape[0] < 1 or a.shape[1] < 1:
            raise ValueError(f"an image must be (H, W) or (H, W, C) with 1 <= C <= 4 and no empty side, got shape {a.shape}")
        if a.dtype == np.bool_:
            a = a.astype(np.uint8) * 255
        if a.dtype == np.uint8:
            self.is_float = False
        elif a.dtype.kind == "f":
            a, self.is_float = a.astype(np.float32), True
        else:
            raise ValueError(f"image dtype {a.dtype} is not supported: use uint8, bool or a floating point type")
        self.data = np.ascontiguousarray(a)

    @property
    def height(self) -> int:
        return self.data.shape[0]

    @property
    def width(self) -> int:
        return self.data.shape[1]

    @property
    def channels(self) -> int:
        return self.data.shape[2]


@dataclass
class Cooked:
    """Result of one cook."""
    data: np.ndarray                     # (samples, channels) float32
    names: list[str]
    warning: str
    error: str
    popup: str
    info: dict[str, float]               # Info CHOP: channel name -> value
    info_dat: list[tuple]                # Info DAT rows (name, text) (all columns of a row when not 2)
    type: str                            # operator type (Ewdirectness)
    label: str                           # operator label
    sample_rate: float
    start_index: float
    timeslice: bool                      # the operator output a timeslice
    output_declared: bool                # getOutputInfo returned true
    cook_count: int

    @property
    def status_name(self) -> str:
        """The status the operator shows in its Info DAT ('OK', 'INVALID_INPUT', ...); '' when it has none."""
        return self.dat("status", "")

    @property
    def status(self) -> Optional[int]:
        v = self.info.get("status")
        return None if v is None else int(v)

    @property
    def reason(self) -> str:
        return self.dat("reason", "")

    def dat(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Text of the first Info DAT row called `name`."""
        for row in self.info_dat:
            if row and row[0] == name:
                return row[1] if len(row) > 1 else ""
        return default

    @property
    def num_channels(self) -> int:
        return self.data.shape[1]

    @property
    def num_samples(self) -> int:
        return self.data.shape[0]


def _as_input(x, default_rate: float):
    if x is None or isinstance(x, Image):
        return x
    if isinstance(x, Signal):
        return x
    return Signal(x)


class Chop:
    """One operator DLL loaded in the host, with one live instance (a node). The instance keeps its state between
    cooks; `reset_instance()` creates a fresh node (parameters back to their defaults, cook count 0)."""

    def __init__(self, dll_path, host_dll=None):
        self._lib = _load_library(host_dll)
        self.path = str(Path(dll_path))
        err = C.create_string_buffer(1024)
        self._h = self._lib.ewh_open(self.path.encode("utf-8"), err, len(err))
        if not self._h:
            raise HostError(_text(err.value))
        L, h = self._lib, self._h
        self.op_type = _text(L.ewh_plugin_text(h, 0))
        self.op_label = _text(L.ewh_plugin_text(h, 1))
        self.op_icon = _text(L.ewh_plugin_text(h, 2))
        self.author = _text(L.ewh_plugin_text(h, 3))
        self.author_email = _text(L.ewh_plugin_text(h, 4))
        lo, hi = C.c_int(), C.c_int()
        L.ewh_plugin_inputs(h, C.byref(lo), C.byref(hi))
        self.min_inputs, self.max_inputs = lo.value, hi.value
        api, major, minor = C.c_int(), C.c_int(), C.c_int()
        L.ewh_plugin_version(h, C.byref(api), C.byref(major), C.byref(minor))
        self.api_version, self.major_version, self.minor_version = api.value, major.value, minor.value
        self._read_params()

    # ---- life of the instance ----------------------------------------------------------------------------------------
    @property
    def num_inputs(self) -> int:
        """Number of inputs the operator expects: its maximum (equal to the minimum for all current operators)."""
        return self.max_inputs

    def reset_instance(self) -> None:
        """Destroy the node and create a fresh one: state, parameters and cook count start again."""
        if self._lib.ewh_reset_instance(self._h) != _CODE_OK:
            raise OperatorFault(_text(self._lib.ewh_last_error(self._h)))
        self._read_params()

    def close(self) -> None:
        if getattr(self, "_h", None):
            self._lib.ewh_close(self._h)
            self._h = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ---- parameters ----------------------------------------------------------------------------------------------------
    def _read_params(self) -> None:
        L, h = self._lib, self._h
        params = []
        for i in range(L.ewh_param_count(h)):
            info = _ParamInfo()
            L.ewh_param_info(h, i, C.byref(info))
            kind = _KINDS[info.kind]
            menu = [(_text(L.ewh_param_menu_name(h, i, j)), _text(L.ewh_param_menu_label(h, i, j))) for j in range(info.num_menu)]
            if kind in ("string", "menu"):
                default = _text(L.ewh_param_text(h, i, 3))
            elif kind == "pulse":
                default = None
            elif kind == "int":
                default = int(info.default[0])
            elif kind == "toggle":
                default = int(info.default[0])
            elif info.size > 1:
                default = [float(info.default[k]) for k in range(info.size)]  # vector parameter
            else:
                default = float(info.default[0])
            params.append(Param(name=_text(L.ewh_param_text(h, i, 0)), kind=kind, default=default,
                                label=_text(L.ewh_param_text(h, i, 1)), page=_text(L.ewh_param_text(h, i, 2)),
                                menu=menu, size=info.size, minimum=info.min[0], maximum=info.max[0],
                                clamp_min=bool(info.clamp_min[0]), clamp_max=bool(info.clamp_max[0]),
                                slider_min=info.slider_min[0], slider_max=info.slider_max[0]))
        self.params: list[Param] = params
        text = _text(L.ewh_setup_issues(h))
        self.setup_issues: list[str] = [line for line in text.split("\n") if line]

    def param(self, name: str) -> Param:
        for p in self.params:
            if p.name == name:
                return p
        raise KeyError(f"{self.op_type} has no parameter '{name}' (has: {', '.join(p.name for p in self.params)})")

    def set(self, name: str, value, index: int = 0) -> None:
        """Set a parameter as `op.par.Name = value` does: numbers are clamped, ints rounded, toggles any truthy value,
        menus take an item name (or an item index), strings any text. A sequence sets the values of a vector parameter."""
        if name[-1:] in _FIELD_INDEX and not any(q.name == name for q in self.params):
            # `Gravityx` of a vector parameter `Gravity`, as in TouchDesigner Python (op.par.Gravityx)
            base = name[:-1]
            if any(q.name == base and q.size > _FIELD_INDEX[name[-1]] for q in self.params):
                return self.set(base, value, _FIELD_INDEX[name[-1]])
        p = self.param(name)
        L, h = self._lib, self._h
        if p.kind == "pulse":
            raise HostError(f"'{name}' is a pulse: use pulse('{name}')")
        if isinstance(value, (list, tuple, np.ndarray)):
            for i, v in enumerate(value):
                self.set(name, v, i)
            return
        if p.kind in ("string", "menu") and isinstance(value, str):
            rc = L.ewh_set_string(h, name.encode(), value.encode("utf-8"))
        elif p.kind == "string":
            rc = L.ewh_set_string(h, name.encode(), str(value).encode("utf-8"))
        else:
            if isinstance(value, str):
                raise HostError(f"'{name}' is {p.kind}, not a string")
            rc = L.ewh_set_number(h, name.encode(), index, float(value))
        if rc != 0:
            raise HostError(_text(L.ewh_last_error(h)))

    def get(self, name: str):
        """Current value: number (int for int/toggle/menu-free kinds), str for string and menu."""
        p = self.param(name)
        L, h = self._lib, self._h
        if p.kind in ("string", "menu"):
            return _text(L.ewh_get_string(h, name.encode()))
        out = C.c_double()
        if L.ewh_get_number(h, name.encode(), 0, C.byref(out)) != 0:
            raise HostError(_text(L.ewh_last_error(h)))
        return int(out.value) if p.kind in ("int", "toggle") else out.value

    def pulse(self, name: str) -> None:
        """Press a pulse parameter; pulsePressed is called at the start of the next cook."""
        if self._lib.ewh_pulse(self._h, name.encode()) != 0:
            raise HostError(_text(self._lib.ewh_last_error(self._h)))

    def par_enabled(self, name: str) -> bool:
        """False when the operator disabled the parameter with enablePar(name, false) (greyed out in TouchDesigner)."""
        r = self._lib.ewh_param_enabled(self._h, name.encode())
        if r < 0:
            raise KeyError(name)
        return bool(r)

    # ---- cook ------------------------------------------------------------------------------------------------------------
    def cook(self, *inputs, sample_rate: float = 60.0, timeslice: Optional[int] = None, start_index: float = 0,
             fill: float = float("nan"), tops: Optional[dict] = None) -> Cooked:
        """Cook the operator once.

        inputs        float arrays (samples, channels) (1-D: one channel), `Signal`s (names, own rate) or None for an empty
                      input slot. No input at all is a cook of an unconnected operator.
        sample_rate   timeline rate: the rate of inputs that give none, and the FPS the operator sees (getTimeInfo).
        timeslice     samples of the slice when the operator outputs a timeslice (default: samples of input 0).
        start_index   start index of the inputs and of a timeslice output.
        fill          value of the output buffers before the cook (TouchDesigner gives uninitialised memory; NaN shows
                      what an operator did not write).
        tops          {parameter name: Image} for TOP parameters (appendTOP) read through getParTOP; like the inputs, an
                      image lives for one cook. An `Image` among the inputs is a TOP wired to that input (getInputTOP).
        Raises OperatorFault when the operator crashes (the host survives) and HostUnsupported when it asks the host for
        something it cannot give; both carry the message."""
        sigs = [_as_input(x, sample_rate) for x in inputs]
        keep = []  # buffers alive during the call
        arr = (_Input * max(len(sigs), 1))()
        for i, sig in enumerate(sigs):
            e = arr[i]
            if sig is None:
                e.connected = 0
                continue
            if isinstance(sig, Image):
                e.connected = 0                       # the slot holds a TOP, handed to the host separately
                if not hasattr(self._lib, "ewh_set_top_input"):
                    raise HostError("this ew_td_host.dll has no TOP support (rebuild it from tests/host)")
                self._lib.ewh_set_top_input.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int]
                self._lib.ewh_set_top_input.restype = C.c_int
                if self._lib.ewh_set_top_input(self._h, i, sig.data.ctypes.data, sig.width, sig.height, sig.channels,
                                               int(sig.is_float)) != 0:
                    raise HostError(_text(self._lib.ewh_last_error(self._h)))
                continue
            data = np.ascontiguousarray(np.asarray(sig.data, dtype=np.float32).T)  # channel-major
            keep.append(data)
            e.connected = 1
            e.channels, e.samples = data.shape
            e.sample_rate = float(sig.sample_rate) if sig.sample_rate else 0.0
            e.data = data.ctypes.data_as(C.POINTER(C.c_float))
            if sig.names is not None:
                raw = [n.encode("utf-8") for n in sig.names]
                names = (C.c_char_p * len(raw))(*raw)
                keep.append((raw, names))
                e.names = C.cast(names, C.POINTER(C.c_char_p))
        L, h = self._lib, self._h
        for name, image in (tops or {}).items():
            if not hasattr(L, "ewh_set_top_par"):
                raise HostError("this ew_td_host.dll has no TOP support (rebuild it from tests/host)")
            L.ewh_set_top_par.argtypes = [C.c_void_p, C.c_char_p, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int]
            L.ewh_set_top_par.restype = C.c_int
            if L.ewh_set_top_par(h, name.encode(), image.data.ctypes.data, image.width, image.height, image.channels,
                                 int(image.is_float)) != 0:
                raise HostError(_text(L.ewh_last_error(h)))
        rc = L.ewh_cook(h, arr, len(sigs), float(sample_rate), int(timeslice or 0), float(start_index), float(fill))
        if rc == _CODE_FAULT:
            raise OperatorFault(f"{self.op_type}: {_text(L.ewh_last_error(h))}")
        if rc == _CODE_HOST:
            raise HostUnsupported(f"{self.op_type}: {_text(L.ewh_last_error(h))}")
        return self._result()

    def _result(self) -> Cooked:
        L, h = self._lib, self._h
        info = _CookInfo()
        L.ewh_result_info(h, C.byref(info))
        n = info.num_channels * info.num_samples
        buf = np.empty(n, dtype=np.float32)
        L.ewh_result_data(h, buf.ctypes.data_as(C.POINTER(C.c_float)), n)
        data = np.ascontiguousarray(buf.reshape(info.num_channels, info.num_samples).T)
        names = [_text(L.ewh_result_name(h, c)) for c in range(info.num_channels)]
        chop_info = {}
        for i in range(L.ewh_info_chop_count(h)):
            chop_info[_text(L.ewh_info_chop_name(h, i))] = float(L.ewh_info_chop_value(h, i))
        rows, cols = C.c_int(), C.c_int()
        dat = []
        if L.ewh_info_dat_size(h, C.byref(rows), C.byref(cols)):
            for r in range(rows.value):
                dat.append(tuple(_text(L.ewh_info_dat_cell(h, r, c)) for c in range(cols.value)))
        return Cooked(data=data, names=names, warning=_text(L.ewh_result_warning(h)), error=_text(L.ewh_result_error(h)),
                      popup=_text(L.ewh_result_popup(h)), info=chop_info, info_dat=dat, type=self.op_type,
                      label=self.op_label, sample_rate=info.sample_rate, start_index=info.start_index,
                      timeslice=bool(info.timeslice), output_declared=bool(info.output_declared),
                      cook_count=info.cook_count)
