from typing import Any, IO

from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import GdbMiCmd, filterArgs, sendReplyDone


def gdbLlvmIrProcessCmdData(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    dbgFile = state.dbgFile
    if cmd.name == 'data-evaluate-expression':
        args = filterArgs(cmd.args, [['--thread', '1'], ['--frame', '0'], ['--thread-group', 'i1']])
        if args == ['"sizeof (void*)"']:
            sendReplyDone(cmd, w, state.dbgFile, (("value", '"8"'),))
            return True
        elif len(args) == 1:
            expr = cmd.args[0]
            if not expr.startswith('"'):
                raise NotImplementedError()
            for r in state.llvmRegs:
                if r.name == expr:
                    regI = r.registerIndex
                    if regI is not None:
                        v = state.remote.readRegister(regI)
                        sendReplyDone(cmd, w, dbgFile, (('value', f'"0x{v:x}"')))
                        return True

    elif cmd.name == 'data-list-register-names':
        if cmd.args == [] or cmd.args == ['--thread-group', 'i1']:
            sendReplyDone(cmd, w, dbgFile, (('register-names', '[]'),))
            return True

    elif cmd.name == 'data-list-register-values':
        formatChar = cmd.args[0]
        if len(cmd.args) == 1:
            if formatChar == 'x':
                regValues = []
                for r in state.llvmRegs:
                    regI = r.registerIndex
                    if regI is not None:
                        v = state.remote.readRegister(regI)
                        regValues.append(f'{{number="{regI:d}",value="0x{v:x}"}}')
                regValues = str(regValues).replace("'", '"')
                sendReplyDone(cmd, w, dbgFile, (('register-values', regValues),))
                return True

    return False
