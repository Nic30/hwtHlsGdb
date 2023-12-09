from typing import Any, IO

from hwtHlsGdb.gdbCmdHandlerLlvmIr import LLVM_IR_SRC_CODELINE_OFFSET
from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import GdbMiCmd, sendReplyDone, \
    gdbMsgFormatBreakpoint, NL


def gdbLlvmIrProcessCmdBreak(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    dbgFile = state.dbgFile
    if cmd.name == 'break-insert':
        # https://www.zeuthen.desy.de/dv/documentation/unixguide/infohtml/gdb/GDB_002fMI-Breakpoint-Commands.html#GDB_002fMI-Breakpoint-Commands
        # https://sourceware.org/gdb/onlinedocs/gdb/GDB_002fMI-Breakpoint-Commands.html#GDB_002fMI-Breakpoint-Commands
        codeline = None
        if cmd.args == ['-t', '-f', 'main'] or cmd.args == ['-f', 'main']:
            assert state.remote is not None, cmd
            codeline = LLVM_IR_SRC_CODELINE_OFFSET

        elif len(cmd.args) == 2 and cmd.args[0] == "-f":
            file, codeline = cmd.args[1].split(":")
            assert file == state.exe or state.exe.endswith(file)
            codeline = int(codeline)

        if codeline is not None:
            state.remote.breakInsert(codeline * 8)
            bkpt = gdbMsgFormatBreakpoint(state.llvm, state.exe, codeline, state.breakpointIdCntr, codeline * 8)
            state.breakpoints[state.breakpointIdCntr] = codeline
            state.breakpointIdCntr += 1
            w.write(f'=breakpoint-created,bkpt={bkpt:s}{NL}')
            sendReplyDone(cmd, w, dbgFile, (('bkpt', bkpt),))
            return True

    elif cmd.name == 'break-delete':
        if len(cmd.args) == 1:
            number = int(cmd.args[0])
            codeline = state.breakpoints.pop(number)
            state.remote.breakDelete(codeline * 8)
            w.write(f' =breakpoint-deleted,id={number:d}{NL}')
            sendReplyDone(cmd, w, dbgFile, ())
            return True
    # =breakpoint-modified,bkpt={...}
    # =breakpoint-deleted,id=number
    return False
