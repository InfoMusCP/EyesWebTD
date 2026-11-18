# Third-party notices

The EyesWebTD operators (the DLLs in `Plugins/EyesWeb/`) contain, or are built with, the following components.

## EyesWebCore (statically linked into every DLL)

The C++ core with the ports of the EyesWeb blocks, the same code that PyEyesWeb uses through the `eyesweb-core` wheel.
Copyright (c) 2026 InfoMus Lab - Casa Paganini. Distributed in binary form only, under the InfoMus Binary Licence
(`LICENSE-EyesWebCore` in the release package): use, including commercial use, and redistribution of the unmodified
binaries are free, with the licence and these notices kept and the credit "InfoMus Lab - Casa Paganini, University of
Genoa" given. The source code of EyesWebTD itself is under the Apache License 2.0 (`LICENSE`, `NOTICE`).

## pocketfft (header only, compiled into the DLLs through EyesWebCore)

Copyright (C) 2010-2018 Max-Planck-Society. BSD 3-clause licence.

```
Copyright (C) 2010-2018 Max-Planck-Society
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice, this
  list of conditions and the following disclaimer in the documentation and/or
  other materials provided with the distribution.
* Neither the name of the copyright holder nor the names of its contributors may
  be used to endorse or promote products derived from this software without
  specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## TouchDesigner C++ plugin headers (build time only, not part of the package)

`third_party/touchdesigner_sdk/CPlusPlus_Common.h` and `CHOP_CPlusPlusBase.h` are Derivative Inc. files from TouchDesigner
2025.32280, kept unmodified with their notice, under Derivative's Shared Use License (printed at the top of each file).
Their code is compiled into the DLLs; the files themselves are not shipped in the package. Using the plugins needs a
TouchDesigner licence from Derivative.
