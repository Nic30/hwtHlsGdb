import ast
import binascii
import logging
from math import ceil, inf
import re
from typing import Optional, Dict, Tuple, Generator, Union, List, Set, Literal

from hwt.hdl.types.bits import HBits
from hwt.hdl.types.bitsConst import HBitsConst
from hwt.hdl.const import HConst
from hwtHls.llvm.llvmIr import Function, BasicBlock, Instruction, TypeToIntegerType, IntegerType, \
    LLVMStringContext
from hwtHls.ssa.analysis.llvmIrInterpret import LlvmIrInterpret
from hwtHlsGdb.gdbCmdHandler import GdbCmdHandler, CycleLimitReached
from hwtHlsGdb.gdbRemoteMessages import gdbReplyStopped, gdbReplyOk, \
    gdbReplyError, gdbReplyCurrentThreadId, gdbReplyThreadIds, \
    ERROR_BAD_ACCESS_SIZE_FOR_ADDRESS, _bytesToInt32Array, GdbBreakPointType, \
    GdbTargetSignal
from hwtSimApi.constants import CLK_PERIOD
from pyDigitalWaveTools.vcd.writer import VcdWriter

trace = logging.getLogger("GdbServerHandlerLllvmMir:trace").debug

RE_ID = re.compile('[^0-9a-zA-Z_]+')
LLVM_IR_SRC_CODELINE_OFFSET = 6


class LlvmIrSimPcReg:
    """
    Program Counter register for simulation purposes
    """
    INDEX = 0
    pass


class LlvmRegisterInfo():

    def __init__(self, codeline: int, registerIndex: Optional[int], instr: Instruction, dtype: Optional[IntegerType], name:Optional[str], dtypeName: Optional[str]):
        self.codeline = codeline
        self.registerIndex = registerIndex
        self.instr = instr
        self.dtype = dtype
        self.name = name
        self.dtypeName = dtypeName


def llvmIrIterRegs(codelineOffset: int, regIndexOffset: int, fn: Function, sanitizeNames: bool):
    seenNames: Set[str] = set()
    for bb in fn:
        bb: BasicBlock
        for instr in bb:
            instr: Instruction
            t: IntegerType = TypeToIntegerType(instr.getType())
            if t is None:
                yield LlvmRegisterInfo(codelineOffset, None, instr, None, None, None)
                codelineOffset += 1
                continue

            name = instr.printAsOperand()
            dtypeName, name = name.split(' ', 1)
            name = name.strip()
            # if name.startswith("label "):
            #    name = name[len("label "):]
            if name.startswith("%"):
                name = name[1:]
            if name.startswith('"') and name.endswith('"'):
                name = ast.literal_eval(name)

            assert name, instr
            _name = name
            if sanitizeNames:
                _name = name = RE_ID.sub("_", name)

            nameI = 1
            while name in seenNames:
                name = f"{_name}_{nameI}"
                nameI += 1
            seenNames.add(name)

            yield LlvmRegisterInfo(codelineOffset, regIndexOffset, instr, t, name, dtypeName)
            codelineOffset += 1
            regIndexOffset += 1

        codelineOffset += 2


class GdbCmdHandlerLllvmIr(GdbCmdHandler):
    """
    An object which translates GDB remote commands to a simulator of LLVM IR.
    
    :note: LLVM Instruction = GDB target register
    :ivar fnArgs: arguments for simulated LLVM IR function.
    :ivar registerToIndex: dictionary mapping 
    :ivar nowTime: simulation time for logging purposes
    :ivar timeStep: time step for simulation time
    """

    def __init__(self, interpret: LlvmIrInterpret,
                 fnArgs: tuple,
                 codelineOffset: int=LLVM_IR_SRC_CODELINE_OFFSET):
        super(GdbCmdHandlerLllvmIr, self).__init__()
        self.interpret = interpret
        self.fnArgs = fnArgs
        self.registerToIndex: Dict[Instruction, int] = {}
        self.registerToName: Dict[Instruction, str] = {}
        self.registerValue: Dict[Instruction, HConst] = {}
        self.registers: List[Union[Instruction, Literal[LlvmIrSimPcReg]]] = [LlvmIrSimPcReg, ]
        self.REGISTER_INFO: List[str] = [
            f'name:pc;bitsize:64;offset:0;encoding:uint;format:hex;set:Program Counter;generic:pc;'
        ]
        self.instrCodeline: Dict[Instruction, int] = {}
        regOffset = 8
        for r in llvmIrIterRegs(codelineOffset, len(self.REGISTER_INFO), interpret.F, False):
            instr: Instruction = r.instr
            self.instrCodeline[instr] = r.codeline
            t = r.dtype
            if t is None:
                continue
            self.registers.append(instr)
            self.REGISTER_INFO.append(
                f'name:{r.name};bitsize:{t.getBitWidth()};offset:{regOffset};encoding:uint;format:hex;set:LLVM IR reg;generic:{r.name};'
            )
            self.registerToIndex[instr] = r.registerIndex
            self.registerToName[instr] = r.name
            self.registerValue[instr] = HBits(t.getBitWidth()).from_py(None)
            regOffset += ceil(t.getBitWidth() / 8)

        self.indexToRegister = {v: k for k, v in self.registerToIndex.items()}
        self.bb: Optional[BasicBlock] = None
        self.instr: Optional[Instruction] = None  # :note: this is always a next instruction which was not executed yet
        self.predBb: Optional[BasicBlock] = None
        self.simBlockLabel = None
        self.memory = {}
        self.breakpoints = {}
        self.codelineOffset = codelineOffset

    def runCurrentInstr(self) -> Union[int, CycleLimitReached, None]:
        """
        :returns: optional address of breakpoint if any breakpoint meet
        """
        waveLog = self.waveLog
        if self.cycleLimit == 0:
            return CycleLimitReached
        self.cycleLimit -= 1

        if not self.waveLogInitialized:
            _, self.simCodelineLabel, self.simTimeLabel, self.simBlockLabel = self.interpret._prepareVcdWriter(
                waveLog, self.strCtx, self.fn, self.timeStep, self.codelineOffset)
            self.waveLogInitialized = True
        predBb = self.predBb
        bb = self.bb
        instr = self.instr
        try:
            if instr is None:
                assert bb is None
                assert predBb is None
                bb = self.fn.getEntryBlock()
                instr = next(iter(bb), None)
                assert instr is not None, bb
                instrAddr = self.instrCodeline[instr] * 8
                if instrAddr in self.breakpoints:
                    return instrAddr

            self.nowTime += self.timeStep
            if waveLog is not None:
                waveLog.logChange(self.nowTime, self.simTimeLabel, self.nowTime, None)
                waveLog.logChange(self.nowTime, self.simCodelineLabel, instr, None)
            predBb, bb, isJump = self._runLlvmIrFunctionInstr(waveLog, self.nowTime, self.registerValue, instr,
                                                         predBb, bb, self.fnArgs,
                                                         self.simBlockLabel)
            prevInstr = instr
            if isJump:
                instr = next(iter(bb), None)
            else:
                instr = instr.getNextNode()

            assert instr is not None, (prevInstr, isJump, bb)
            instrAddr = self.instrCodeline[instr] * 8
            if instrAddr in self.breakpoints:
                return instrAddr
            else:
                return None
        finally:
            self.predBb = predBb
            self.bb = bb
            self.instr = instr

    def handleInterruption(self):
        trace('interrupted')
        return gdbReplyOk(None)

    def handleHaltReason(self):
        trace('haltReason')
        return gdbReplyStopped(GdbTargetSignal.TRAP)

    def handleReadRegisters(self):
        trace("readRegisters")
        values = []
        for r in self.registers:
            if r is LlvmIrSimPcReg:
                if self.instr is None:
                    v = 0
                else:
                    v = self.instrCodeline[self.instr] * 8
                byteSize = 8
            else:
                _v: HBitsConst = self.registerValue[r]
                v = _v.val & _v.vld_mask
                byteSize = ceil(_v._dtype.bit_length() / 8)
            v = v.to_bytes(byteSize, 'little')
            values.append(v)

        return gdbReplyOk(b''.join(values))

    def handleReadRegister(self, index: int):
        trace(f'readRegister{index}')
        if index == LlvmIrSimPcReg.INDEX:
            if self.instr is None:
                v = self.codelineOffset
            else:
                v = self.instrCodeline[self.instr]
            v *= 8
            byteSize = 8
        else:
            r = self.registers[index]
            _v = v = self.registerValue[r]
            v = (v.val & v.vld_mask)
            byteSize = ceil(_v._dtype.bit_length() / 8)

        v = v.to_bytes(byteSize, 'little')
        return gdbReplyOk(v)

    def handleWriteRegisters(self, databytes: bytes):
        trace("writeRegisters")
        raise NotImplementedError()
        values = _bytesToInt32Array(databytes)
        # Skip the $zero register.
        for i, v in enumerate(values):
            self.registers[i] = v
        return gdbReplyOk(None)

    def handleReadMemory(self, address, length):
        trace("readMemory")
        raise NotImplementedError()
        start = max(address, 0)
        end = min(start + length, len(self.memory))
        return gdbReplyOk(self.memory[start, end])

    def handleWriteMemory(self, address: int, values: bytes):
        trace("writeMemory")
        raise NotImplementedError()
        start = max(address, 0)
        end = start + len(values)
        if len(self.memory) < end:
            # Bad access size for address
            return gdbReplyError(ERROR_BAD_ACCESS_SIZE_FOR_ADDRESS)

        self.memory[start:end] = values
        return gdbReplyOk(None)

    def handleStep(self, address: Optional[int]):
        trace("step")
        self.cycleLimit = 1
        return gdbReplyOk(None)

    def handleContinue(self, address: Optional[int]):
        trace("continue")
        self.cycleLimit = inf
        return gdbReplyOk(None)

    def handleQSupported(self, features: Dict[str, bool]):
        return gdbReplyOk('QStartNoAckMode+;swbreak+;hwbreak+')

    def handle_qTStatus(self):
        return gdbReplyOk('T0;tnotrun:0;tframes:0;tcreated:0;tfree:50*!;tsize:50*!;circular:0;disconn:0;starttime:0;stoptime:0;username:;notes::')

    def handle_qTfV(self):
        # n:value:builtin:name
        name = binascii.hexlify("trace_timestamp".encode()).decode()
        return gdbReplyOk(f'1:0:1:{name:s}')

    def handle_qTsV(self):
        return gdbReplyOk('l')  # end of the list

    def handleThreadInfo(self):
        return gdbReplyThreadIds([0x0])

    def handleCurrentThread(self):
        return gdbReplyCurrentThreadId(0x0)

    def handleRegisterInfo(self, index: int):
        trace(f'registerInfo:{index}')
        if index < len(self.REGISTER_INFO):
            return gdbReplyOk(self.REGISTER_INFO[index])
        return gdbReplyError(1)

    def handleHostInfo(self):
        trace('hostInfo')
        triple = binascii.hexlify("x86_64-unknown-gnu".encode()).decode()
        return gdbReplyOk(f'triple:{triple:s};endian:little;ptrsize:8;')

    def handleMemoryRegionInfo(self, address):
        trace('memoryRegionInfo')
        return gdbReplyOk('start:00000000;size:100000;permissions:rwx;')

    def handleSelectExecutionThread(self, threadId):
        trace(f'select execution thread:{threadId}')
        return gdbReplyOk(None)

    def handleSelectRegisterThread(self, threadId):
        trace(f'select register thread:{threadId}')
        return gdbReplyOk(None)

    def handleSelectMemoryThread(self, threadId):
        trace(f'select memory thread:{threadId}')
        return gdbReplyOk(None)

    def handleAddBreakpoint(self, btype: GdbBreakPointType, address, kind: int):
        trace(f'addBreakpoint at:{address:x}')
        self.breakpoints[address] = True
        return gdbReplyOk(None)

    def handleRemoveBreakpoint(self, btype: GdbBreakPointType, address, kind: int):
        trace(f'removeBreakpoint at:{address:x}')
        if address in self.breakpoints:
            del self.breakpoints[address]
            return gdbReplyOk(None)
        else:
            return gdbReplyError(1)
