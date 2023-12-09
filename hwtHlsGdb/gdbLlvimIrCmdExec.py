from typing import Any, IO

from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import GdbMiCmd, filterArgs, sendReplyDone, \
    sendReplyRunning, sendInterruptRunning, NL


def gdbLlvmIrProcessCmdExec(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    dbgFile = state.dbgFile
    if cmd.name == 'exec-continue':
        # https://getdocs.org/Gdb/docs/latest/gdb/GDB_002fMI-Program-Execution
        if cmd.args == [] or cmd.args == ['--thread-group', 'i1'] or cmd.args == ['--thread', '1']:
            state.remote.sendContinue()
            sendReplyRunning(cmd, w, dbgFile, ())
            sendInterruptRunning(w, dbgFile, (('thread-id', '"1"'),))
            return True

    elif cmd.name == 'exec-interrupt':
        args = filterArgs(cmd.args, [['--thread', '1'], ['--thread-group', '1']])
        if args == []:
            state.remote.sendInterrupt()
            sendReplyDone(cmd, w, dbgFile, ())
            return True

    elif cmd.name == 'exec-next' or cmd.name == 'exec-step':
        args = filterArgs(cmd.args, [['--thread', '1'], ['--thread-group', '1']])
        if args == ['1'] or cmd.args == []:
            state.remote.sendStep()
            sendReplyRunning(cmd, w, dbgFile, ())
            sendInterruptRunning(w, dbgFile, (('thread-id', '"1"'),))
            return True

    elif cmd.name == 'exec-run':
        if cmd.args == []:
            w.write(f'=thread-group-started,id="i1",pid="1"{NL}')
            w.write(f'=thread-created,id="1",group-id="i1"{NL}')
            state.remote.sendContinue()

            sendReplyRunning(cmd, w, dbgFile, ())
            sendInterruptRunning(w, dbgFile, (('thread-id', '"1"'),))
            return True
    return False
