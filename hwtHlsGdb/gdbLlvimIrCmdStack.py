from typing import Any, IO

from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import GdbMiCmd, sendReplyDone, \
    gdbMsgFormatStack, gdbMiEscapeStr


def gdbLlvmIrProcessCmdStack(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    dbgFile = state.dbgFile
    if cmd.name == 'stack-info-depth':
        # https://ftp.gnu.org/old-gnu/Manuals/gdb/html_node/gdb_226.html
        if cmd.args == ['--thread', '1'] or cmd.args == ['--thread', '0']:
            sendReplyDone(cmd, w, dbgFile, (("depth", f'"{state.curStackDepth:d}"'),))
            return True
        elif cmd.args[:-1] == ['--thread', '1'] or cmd.args[:-1] == ['--thread', '0']:
            state.curStackDepth = min(state.curStackDepth, int(cmd.args[-1]))
            doneArgs = (("depth", f'"{state.curStackDepth}"'),)
            sendReplyDone(cmd, w, dbgFile, doneArgs)
            return True

    elif cmd.name == 'stack-list-frames':
        if cmd.args == ['--thread-group', 'i1'] or cmd.args == ['--thread', '1'] or cmd.args == ['0', '1000']:
            doneArgs = ((f'stack', gdbMsgFormatStack(state.remote.readRegister(0) // 8, state.llvm, state.exe)),)
            sendReplyDone(cmd, w, dbgFile, doneArgs)
            return True

    elif cmd.name == 'stack-list-arguments':
        if cmd.args == ['0', '0', '0']:
            doneArgs = (('stack-args', '[frame={level="0",args=[]}]'),)
            sendReplyDone(cmd, w, dbgFile, doneArgs)
            return True

    elif cmd.name == 'stack-list-variables':
        if cmd.args == ['0']:
            regs = [f'{{name={gdbMiEscapeStr(r.name)}, value="{0}"}}' for r in state.llvmRegs if r.registerIndex is not None]
            doneArgs = (('variables', f'[{",".join(regs):s}]'),)  # {name="x",value="11"}
            sendReplyDone(cmd, w, dbgFile, doneArgs)
            return True

    elif cmd.name == 'stack-select-frame':
        # https://ftp.gnu.org/old-gnu/Manuals/gdb/html_chapter/gdb_22.html
        if cmd.args == ['--thread', '1', '0']:
            sendReplyDone(cmd, w, dbgFile, ())
            return True
    return False
