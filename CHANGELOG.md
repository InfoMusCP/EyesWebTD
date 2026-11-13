# Changelog

Version numbers follow `VERSION` (MAJOR.MINOR.PATCH). TouchDesigner compares MAJOR and MINOR of the operators saved in a
.toe with the installed ones: a MAJOR change breaks saved projects (renamed parameters or channels), MINOR adds operators or
parameters.

## 0.1.0 (unreleased)

First release of the layered operator set: 37 operators, one per feature of the first PyEyesWeb release (36) and
`TimeWindowSynchronizer`, in five layers (physical signals, low-level, mid-level, high-level, analysis primitives).

- Operators are named after the PyEyesWeb features and carry the layer in the label (`EW L2 Kinetic Energy`); channel names
  follow PyEyesWeb.
- Parameter names are the PyEyesWeb public names without underscores (`Maxlag`, `Filterwindowlength`), menu entries the
  PyEyesWeb choices.
- Stream operators have `Source` (stream / clip) and `Reset`; buffer operators have `Reset`; parameters are applied live.
- Every operator has an Info CHOP / DAT with status, reason and sample counts.
- Gesture Segmenter gives the duration of each gesture and pause (Motion Duration merged in) and has no noise input.
- Parameter names are a capital followed by lowercase letters and digits (the TouchDesigner rule); checked by the package tests.
- Each DLL carries the package version (file properties and the operator's major / minor version).
