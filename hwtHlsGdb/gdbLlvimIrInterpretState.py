from contextlib import ExitStack
from typing import  Optional, IO, Any, Tuple, List, Dict

from hwtHls.llvm.llvmIr import LlvmCompilationBundle, Instruction, IntegerType
from hwtHlsGdb.gdbRemoteClient import GdbRemoteClient


class GdbInterpretState():

    def __init__(self, dbgFile: Optional[IO[Any]]):
        self.cmdIos: List[Tuple[IO[Any], IO[Any]]] = []
        self.remote: Optional[GdbRemoteClient] = None
        self.appTty: Optional[Tuple[IO[Any], IO[Any]]] = None
        self.dbgFile: Optional[IO[Any]] = dbgFile
        self.llvm: Optional[LlvmCompilationBundle] = None
        # codeline, instruction, result type, register name
        self.llvmRegs: Tuple[int, Instruction, Optional[IntegerType], Optional[str]] = []
        # number to codeline
        self.breakpoints: Dict[int, int] = {}
        self.breakpointIdCntr = 0
        self.tmpVariables: Dict[str, str] = {}  # requested name to assigned name
        self.tmpVariablesIdCntr = 0
        self.exe: Optional[str] = None  # path to debugged IR file
        self.curStackDepth = 1
        self.exitStack: Optional[ExitStack] = None
