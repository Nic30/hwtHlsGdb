# hwtHlsGdb

This python package contains an implementation of debugger for [hwtHls](https://github.com/Nic30/hwtHls)/LLVM intermediate formats.
It implements a GDB/MI (Machine Interface) and GDB Remote Serial Protocol. It mimics GDB and thus it is compatible with any GDB compatible
IDE. It is tested with Visual Studio Code and Eclipse.


## Limitations and intended use

A GDB for software program just executes the binary and IO is handled as for any other program.
For hardware this simply is not possible and IO is offten very complicated and tied with verification or physical enviroment.
And it is rarely possible to generate all transactions in advance. From this reason it is more practical to use
GDB server running in simulation as shown in following code.

```python3
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import List

from hwt.simulator.simTestCase import SimTestCase
from hwtHls.frontend.ast.astToSsa import HlsAstToSsa
from hwtHls.llvm.llvmIr import Function, MachineFunction, LLVMStringContext
from hwtHls.platform.debugBundle import HlsDebugBundle
from hwtHls.platform.virtual import VirtualHlsPlatform
from hwtHls.ssa.analysis.llvmIrInterpret import SimIoUnderflowErr
from hwtHlsGdb.gdbCmdHandlerLlvmIr import GdbCmdHandlerLllvmIr
from hwtHlsGdb.gdbCmdHandlerLlvmMir import GdbCmdHandlerLllvmMir
from hwtHlsGdb.gdbServerStub import GDBServerStub
from hwtHls.ssa.transformation.ssaPass import SsaPass
from hwtHls.ssa.translation.toLlvm import ToLlvmIrTranslator
from pyDigitalWaveTools.vcd.writer import VcdWriter

class TestCase(SimTestCase):
    def _testLlvmIr(self, u: DUT, strCtx: LLVMStringContext, f: Function,
                    handlerCls: Literal[GdbCmdHandlerLllvmIr, GdbCmdHandlerLllvmMir], vcdFileSuffix: str):
    	"""
    	Run GDB server for LLVM IR and log progress to VCD file
    	"""
        dataIn = [1, 2, 3]
        dataOut = []
        args = [iter(dataIn), dataOut]
        try:
            with open(Path(self.DEFAULT_LOG_DIR, f"{self.getTestName()}{vcdFileSuffix}"), "w") as vcdFile:
                waveLog = VcdWriter(vcdFile)
                gdbLlvmIrHandler = handlerCls(strCtx, f, args, waveLog)
                gdbServer = GDBServerStub(gdbLlvmIrHandler)
                gdbServer.start() # There execution hangs untill the gdb client connects
        except SimIoUnderflowErr:
            pass  # all inputs consummed

    def test(self):
        m = HwModuleDUT() # Design Under Test (your component)
        tc = self

        class GdbHlsPlatform(VirtualHlsPlatform):

            def runSsaPasses(self, hls: "HlsScope", toSsa: HlsAstToSsa):
                res = super(TestVirtualHlsPlatform, self).runSsaPasses(hls, toSsa)
                tr: ToLlvmIrTranslator = toSsa.start
                tc._testLlvmIr(m, tr.llvm.strCtx, tr.llvm.main, GdbCmdHandlerLllvmIr, ".llvmIrWave.vcd")
                return res

            def runNetlistTranslation(self, hls: "HlsScope", toSsa: HlsAstToSsa,
                                      mf: MachineFunction, *args):
                tr: ToLlvmIrTranslator = toSsa.start
                tc._testLlvmIr(m, tr.llvm.getMachineFunction(tr.llvm.main), GdbCmdHandlerLllvmMir, '.llvmMirWave.vcd')
                netlist = super(TestVirtualHlsPlatform, self).runNetlistTranslation(hls, toSsa, mf, *args)
                return netlist

        self.compileSimAndStart(m, target_platform=TestVirtualHlsPlatform(debugFilter=HlsDebugBundle.ALL_RELIABLE))


if __name__ == "__main__":
    import unittest
    testLoader = unittest.TestLoader()
    suite = testLoader.loadTestsFromTestCase(TestCase)
    runner = unittest.TextTestRunner(verbosity=3)
    runner.run(suite)
```

## How to setup IDE to use this

1. Prepare you simulation which will act as GDB server (as shown in previous example)
2. Tell IDE to use hwtHlsGdb/gdbLlvmIr.py as GDB executable

### Visual Studio Code

* Install C/C++ extension https://marketplace.visualstudio.com/items?itemName=ms-vscode.cpptools
* Create a launch configuration
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "LLVM debug active file",
            "type": "cppdbg",
            "request": "launch",
            "program": "${fileDirname}/02.preLlvm.ll",
            "args": [],
            "stopAtEntry": false,
            "cwd": "${fileDirname}",
            "environment": [],
            "externalConsole": false,
            "MIMode": "gdb",
            "miDebuggerPath": "${workspaceFolder}/hwtHlsGdb/hwtHlsGdb/gdbLlvimIr.py",
            "setupCommands": [
                {
                    "text": "target-select remote 127.0.0.1:10000",
                    "ignoreFailures": false
                }
            ]
        }
    ]
}
``` 
* Now you should be able to run it as any other project in VScode (usign F5)
* "program" file needs to be one produced from simulation
* "miDebuggerPath" must point to a file in this directory

### Eclipse

* Install Eclipse CDT (C/C++ Development Tooling) extension https://projects.eclipse.org/projects/tools.cdt
* Ctrl+3 (Access commands or other items) -> 
* Debug configurations ->
* C/C++ Remote Application (add new) ->
* Using GDB (DSF) Automatic Remote Debugging Launcher (at the bottom on Main form) ->  Change to Using GDB (DSF) Manual Remote Debugging Launcher
* Debbuger tab -> Main sub-tab -> GDB Debugger set to gdbLlvimIr.py from this repo
  * Connection sub-tab (make sure that the port and IP is correct)


## How it works?

* see doc in `hwtHlsGdb/__init__.py`


### Installation
```
pip3 install git+https://github.com/Nic30/hwtHlsGdb.git # install this library from git
```


## Similar open-source projects

* https://sourceware.org/gdb/ - the project which is beeing 
* https://github.com/nomtats/gdbserver-stub
* https://github.com/cs01/pygdbmi
* https://github.com/simark/pygdbmi
