import ast
import re
from typing import Any, IO

from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import GdbMiCmd, filterArgs, sendReplyDone


def gdbLlvmIrProcessCmdVar(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    if cmd.name == 'var-create':
        args = filterArgs(cmd.args, [['--thread', '1'], ['--frame', '0']])
        if len(args) == 3 and args[0] == '-' and args[1] == '*':
            # If ‘-’ is specified, the varobj system will generate a string “varNNNNNN” automatically.
            # A ‘*’ indicates that the current frame should be used.
            varName = args[2]
            if varName.startswith('"') and varName.endswith('"'):
                varName = ast.literal_eval(varName)
            foundReg = None
            for r in state.llvmRegs:
                if r.name == varName:
                    foundReg = r
                    break
            if foundReg is not None:
                name = f'"var{foundReg.registerIndex:d}"'
                value = f'"0x{state.remote.readRegister(foundReg.registerIndex):x}"'
                dtypeName = f'"{foundReg.dtypeName:s}"'
            else:
                cur = state.tmpVariables.get(varName, None)
                value = '""'
                dtypeName = "unknown"
                if cur is not None:
                    name = cur
                else:
                    name = f'"var{state.tmpVariablesIdCntr:d}"'
                    state.tmpVariables[varName] = name
                    state.tmpVariablesIdCntr += 1

            doneArgs = (('name', name),
                        ('value', value),
                        ('numchild', '"0"'), ('type', dtypeName),
                        ('thread-id', '"1"'), ('has_more', '"0"'))
            sendReplyDone(cmd, w, state.dbgFile, doneArgs)
            return True

    elif cmd.name == 'var-delete':
        if len(cmd.args) == 1:
            varName = cmd.args[0]
            if varName.startswith('"') and varName.endswith('"'):
                varName = ast.literal_eval(varName)
            m = re.match("^var(\d+)$", varName)
            if m:
                regIndex = int(m.group(1))
                assert regIndex > 0 and regIndex < len(state.llvmRegs), (varName, len(len(state.llvmRegs)))
                sendReplyDone(cmd, w, state.dbgFile, ())
                return True

    elif cmd.name == 'var-update':
        if len(cmd.args) == 2 and cmd.args[0] == '1':
            varName = cmd.args[1]
            if varName == "*":
                raise NotImplementedError()
            m = re.match("^var(\d+)$", varName)
            value = ""
            if m:
                regIndex = int(m.group(1))
                if regIndex < len(state.llvmRegs):
                    value = f'"0x{state.remote.readRegister(regIndex):x}"'
            changelist = f'[{{name="{varName:s}",value="{value}",in_scope="true",type_changed="false"}}]'
            doneArgs = (('changelist', changelist),)
            sendReplyDone(cmd, w, state.dbgFile, doneArgs)
            return True
    return False
