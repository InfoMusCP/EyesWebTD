# EyesWeb palette

`build_palette.py` builds the palette inside TouchDesigner: a container per layer (L1 to L4 and analysis primitives) with one
instance of each installed operator, and a `presets` container with small networks (pose to kinetic energy, pose to gesture
segmentation, one joint to suddenness).

A `.tox` is written by TouchDesigner, so the `EyesWeb.tox` of a release is made once with this script and saved from
TouchDesigner (right click, Save Component .tox) into this folder; the package step then includes every `.tox` here.
See the docstring of the script for how to run it. It has not been run yet: it needs a TouchDesigner session with the
plugins installed.
