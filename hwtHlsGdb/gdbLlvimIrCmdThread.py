from hwtHlsGdb.gdbMiMessages import GdbMiCmd, sendReplyDone, \
    gdbMsgFormatFrame
from typing import Any, IO
from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState


def gdbLlvmIrProcessCmdThread(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    if cmd.name == 'thread-info':
        if cmd.args == [] or cmd.args == ['1']:
            mainName = "nomain" if state.llvm is None else state.llvm.main.getName().str()
            frame = gdbMsgFormatFrame(state.remote.readRegister(0) // 8, state.llvm, state.exe)
            doneArgs = (('threads',
                f'[{{id="1",target-id="Thread 0",name="{mainName:s}",'
                f'frame={frame:s},state="stopped",core="0"}}],'
                f'current-thread-id="1"'
            ),)
            sendReplyDone(cmd, w, state.dbgFile, doneArgs)
            return True

    elif cmd.name == 'thread-list-ids':
        if cmd.args == []:
            doneArgs = (("thread-ids", '{thread-id="1"}'), ("number-of-threads", "1"))
            sendReplyDone(cmd, w, state.dbgFile, doneArgs)
            return True

    elif cmd.name == 'thread-select':
        # https://sourceware.org/gdb/onlinedocs/gdb/GDB_002fMI-Thread-Commands.html
        if cmd.args == ['1']:
            doneArgs = (("new-thread-id", '"1"'), ('frame', gdbMsgFormatFrame(state.remote.readRegister(0) // 8, state.llvm, state.exe)))
            sendReplyDone(cmd, w, state.dbgFile, doneArgs)
            return True

    return False
