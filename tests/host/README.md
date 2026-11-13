# Mock TouchDesigner host

Runs the CHOP DLLs of EyesWebTD outside TouchDesigner: `ew_td_host.dll` loads one operator DLL with `LoadLibrary`,
creates a node and cooks it in the order TouchDesigner does; `ewhost.py` drives it from Python with numpy arrays, so
that a test can cook an operator on data and compare the result with PyEyesWeb. Nothing here is linked to the operators.

```
ew_td_host.h/.cpp     the host, plain C API (ewh_*), C++17, includes the TouchDesigner SDK headers (TD_CHOP_SDK)
fixture/              ew_td_fixture.dll: a CHOP that exists only to test the host (every parameter kind, crashes on request);
                      ew_td_fixture_top.dll: the same for TOP inputs (downloads the TOP and reports the pixels it got)
ewhost.py             ctypes wrapper, numpy only
test_host.py          pytest tests of the host (real operators + the fixture + a generic cook of every operator DLL)
pytest.ini            switches pytest's faulthandler off (it reports the crashes that the tests provoke on purpose)
```

## Build and run

```
cmake -S EyesWebTD -B <build> -G "Visual Studio 17 2022" -A x64
cmake --build <build> --config Release -- -m          # operators in <build>/Plugins/EyesWeb/<layer>/, host in <build>/Release/
set EW_TD_PLUGINS=<build>/Plugins/EyesWeb             # directory with <layer>/*.dll
python -m pytest EyesWebTD/tests/host                 # numpy and pytest only
```

Environment variables:

* `EW_TD_PLUGINS`: the directory that holds `<layer>/*.dll` (`<build>/Plugins/EyesWeb`). Tests that need operators skip
  with a message when it is unset.
* `EW_TD_HOST`: path of `ew_td_host.dll`. Default: `<build>/{Release,RelWithDebInfo,MinSizeRel,Debug}/ew_td_host.dll`,
  where `<build>` is two levels above `EW_TD_PLUGINS`. `ew_td_fixture.dll` is looked for next to the host DLL.

## Python API (`ewhost.py`)

```python
from ewhost import Chop, Signal
chop = Chop("<build>/Plugins/EyesWeb/low_level/Ew_DirectnessCHOP.dll")
chop.op_type, chop.op_label, chop.author, chop.num_inputs, chop.min_inputs, chop.max_inputs   # FillCHOPPluginInfo
chop.params            # [Param(name, kind 'float'|'int'|'toggle'|'pulse'|'string'|'menu', default, label, page, menu=[(name, label)], ...)]
chop.setup_issues      # problems the host found in the declarations ("error: ..." / "warning: ...")
chop.set("Window", 80); chop.set("Source", "clip"); chop.pulse("Reset"); chop.get("Window")
out = chop.cook(xy, sample_rate=60.0, timeslice=None, start_index=0)
out = chop.cook(Signal(x, names=["x", "y"], sample_rate=120.0), None, other)    # several inputs, an empty slot
out = chop.cook(Image(mask))                                                    # a TOP on input 0 (see "TOP inputs")
out = chop.cook(tops={"Top": Image(frame)})                                     # a TOP given to the TOP parameter "Top"
out.data               # float32 (samples, channels)
out.names, out.warning, out.error, out.popup
out.info               # Info CHOP: name -> value
out.info_dat           # Info DAT rows: [(name, text), ...]
out.status_name, out.status, out.reason, out.dat("state_reset")                  # from the Info CHOP / DAT of the base layer
out.type, out.label, out.sample_rate, out.start_index, out.timeslice, out.output_declared, out.cook_count
chop.reset_instance()  # a fresh node: state, parameters and cook count start again
```

`cook()` arguments: inputs are float arrays `(samples, channels)` (1-D is one channel), `Signal`s or `None` (an empty
input slot; trailing empty slots are not counted, as in TouchDesigner). `sample_rate` is the timeline rate: the rate of
inputs that name none and the FPS seen through `getTimeInfo`. `timeslice` is the length of the slice for an operator that
outputs a timeslice (default: the length of input 0; pass another length to simulate an input that is not a timeslice).
`fill` (default NaN) is what the output buffers hold before the cook; TouchDesigner gives unspecified memory, NaN shows
what an operator did not write.

## TOP inputs

An operator reads a TOP through `OP_Inputs::getInputTOP(i)` (a TOP wired to input i) or `OP_Inputs::getParTOP(name)` (the
TOP named by a parameter declared with `appendTOP`), then `OP_TOPInput::downloadTexture(options, nullptr)`, which gives an
`OP_SmartRef<OP_TOPDownloadResult>` (`getData()`, `size`, `textureDesc`). `getTOPDataInCPUMemory` is deprecated and private
in the SDK this was written against (TouchDesigner 2025.32280, OpenGL types) and the host does not implement it.

```python
from ewhost import Image
Image(a)    # a: (H, W) or (H, W, C), C = 1..4, row 0 on top. uint8: 8-bit fixed; bool: 0 / 255 mask; float: 32-bit float
chop.cook(Image(a))                          # wired to input 0: getInputTOP(0); getInputCHOP(0) is nullptr for that slot
chop.cook(line, Image(a))                    # a CHOP on input 0, a TOP on input 1
chop.cook(tops={"Top": Image(a)})            # getParTOP("Top"); the parameter must be declared, otherwise HostError
```

An image lives for one cook, like a CHOP input. A declared TOP parameter that was given no image reads as `nullptr`, as an
empty parameter does. `getNumInputs` counts up to the last connected input, TOPs included. The C API is
`ewh_set_top_input` / `ewh_set_top_par` (ew_td_host.h); the other functions and the ABI are unchanged, so an older
`ew_td_host.dll` still works with `ewhost.py` for CHOP inputs.

What `downloadTexture` returns, and what is a convention rather than something checked in TouchDesigner:

* **Native format** of the texture: `uint8` gives Mono8Fixed / RG8Fixed / RGBA8Fixed (1 / 2 / 3 or 4 channels), float gives
  Mono32Float / RG32Float / RGBA32Float. TouchDesigner has no 3-channel textures: a 3-channel image gets an opaque alpha.
  `textureDesc` carries width, height, depth 1, `e2D` and that format; `totalCooks` and `opPath` are set.
* **Requested format** (`options.pixelFormat`, Invalid = native): Mono8/16Fixed, RG8/16Fixed, RGBA8/16Fixed, BGRA8Fixed,
  Mono/RG/RGBA32Float are converted. Fixed point is `v * (2^bits - 1)` rounded and clamped, 8-bit values are `byte / 255`
  as float. Channels: a 1-channel image reads as (r, r, r, 1), 2 channels as (r, g, 0, 1); Mono takes r, RG takes r and g, BGRA
  swaps r and b. Mono from a colour image is therefore its RED channel (the real conversion of TouchDesigner was not
  verified). Other formats (A8, MonoA, 16-bit float, RGB10A2, RGB11) are refused: the cook raises `HostUnsupported`.
* **Row order**: TouchDesigner textures have their origin at the bottom left, so without `verticalFlip` the first row of the
  downloaded memory is the BOTTOM row of the image; with `options.verticalFlip = true` it is the top row, the order a numpy
  array, a video frame and PyEyesWeb use. The host mimics this (the image given from Python has row 0 on top), and the imaging
  operators ask for `verticalFlip = true` so that y counts downward from the top as in PyEyesWeb. The convention follows the
  documented meaning of `verticalFlip`; it was not checked against a running TouchDesigner.
* **Colour space**: the host behaves as a project with working colour space Passthrough: no conversion, `colorSpace` and
  `referenceWhite` of the options are ignored.
* `getCUDAArray` and `getTOP(path)` are not implemented (error, `HostUnsupported`).

Errors: `OperatorFault` (the operator crashed: access violation, C++ exception leaving the plugin, terminate, abort,
division by zero; the host survives and the message names the stage), `HostUnsupported` (the operator asked for an
undeclared parameter, called an `OP_Inputs` function the host does not implement, or declared an impossible output),
`HostError` (bad argument, DLL not loadable). After an `OperatorFault` call `reset_instance()` before cooking again.

## What the host mimics (CHOP_CPlusPlusBase.h)

* Loading: `FillCHOPPluginInfo` with the API version bounds set (see below), `CreateCHOPInstance` with a filled
  `OP_NodeInfo`, `setupParameters` once, `DestroyCHOPInstance` on reset and close.
* Cook: queued `pulsePressed` calls, `getGeneralInfo`, `getOutputInfo` (pre-filled from input `inputMatchIndex`; when it
  returns false the output takes names, length, rate and start of that input), `getChannelName` once per channel,
  `execute`, `getNumInfoCHOPChans`/`getInfoCHOPChan`, `getInfoDATSize`/`getInfoDATEntries` (by row or column),
  `getInfoPopupString`, `getWarningString`, `getErrorString`.
* Timeslice (`getGeneralInfo` sets it): output length from the caller (`timeslice`, default the length of input 0), start
  index `start_index`; otherwise `CHOP_OutputInfo::numSamples` and `startIndex`.
* `OP_Inputs`: every pure virtual exists. Implemented: `getNumInputs`, `getInputCHOP` (nullptr for an empty slot), `getParDouble`,
  `getParInt`, `getParString`, `getParFilePath`, `getParDouble2/3/4`, `getParInt2/3/4`, `getParRGB/RGBA`, `enablePar`,
  `getTimeInfo`, `getInputTOP`, `getParTOP` (with `OP_TOPInput::downloadTexture`, see TOP inputs). Everything else (DAT,
  SOP, POP, Python, object, path based access, `getTOP`) records an error and returns nullptr/false: the cook then raises `HostUnsupported` (the error is not thrown inside the operator, which would be
  caught and hidden by its own try/catch).
* Parameters: all `append*` calls. Numeric (float, int, XY... up to 4 values), toggle, pulse, string, menu (value is the
  selected item NAME for `getParString`, the INDEX for `getParInt/Double`), string menu. Defaults at creation; `set` clamps
  with `clampMins/clampMaxes`, rounds ints, normalises toggles. `getParInt` of a float parameter truncates. Reference
  parameters (DAT, CHOP, ...) are kept as plain strings. Names are checked: must start with a capital letter, letters and
  digits only (error, the parameter is refused as `InvalidName`), duplicates refused; a capital letter after the first
  gives a warning (see below).
* `OP_String`, `OP_InfoCHOPChan`, `OP_InfoDATEntries` receive what the operator sets.
* Every call into the plugin is wrapped in `__try/__except` (and a `catch`); `terminate`, `abort` and CRT
  invalid-parameter handlers are turned into exceptions too.

## Where it knowingly differs from TouchDesigner

* No time model: every cook is a cook; `getTimeInfo` gives `rate = sample_rate`, `frame = cook number`, `deltaFrames` 1
  (0 on the first cook). The length of a timeslice is chosen by the caller, not computed from elapsed frames.
* The cook is always forced: no dirty flags, no `cookEveryFrame`. Inputs and parameters are cooked in the order the
  caller gives them; `OP_NodeInfo::context` is null (calling it crashes), `customOP` is null.
* The API version bounds of `CHOP_PluginInfo` are private const members that only TouchDesigner's class may set; the
  host writes them at their (static_assert-checked) offsets. A change of the SDK layout is caught at compile time.
* Parameter naming rule: the host accepts a capital followed by any letters/digits and only WARNS about capitals after the
  first (TouchDesigner's own rule is a capital followed by lowercase letters and digits; what it does with other names
  was not verified here).
* An integer parameter set to 2.5 becomes 3 (rounded); TouchDesigner's exact rule for a float assigned to an int
  parameter was not verified. `getParString` of a numeric parameter returns the number as `%g`.
* Output with 0 channels or 0 samples is refused as a host error (TouchDesigner's behaviour was not verified).
* Single thread; a `__fastfail` (a /GS buffer overrun) cannot be intercepted and ends the process.
* No visual state, no Python, no callbacks DAT, no dynamic menus (`buildDynamicMenu` is never called).
