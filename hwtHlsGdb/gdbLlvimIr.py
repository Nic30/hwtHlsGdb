#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This script implements a CLI of GDB and behaves as if it was GDB executable.
Its is supposed to be used as a GDB executable to debugg LLVM IR.
Currently only remote debugging mode is supported and the gdb server must be executed separately.

:attention: Newlines in GDB doc are only illustrative and there are no newlines in GDB/MI messages,
    except for end of the message which is \r\n.
    https://sourceware.org/gdb/download/onlinedocs/gdb.pdf

Potentially useful:
* create pseudo terminal pair: socat -d -d pty,raw,echo=0 pty,raw,echo=0

"""

import argparse
from contextlib import ExitStack
import importlib
import os
from pathlib import Path
from select import select
import sys
from typing import  Optional, IO, Any, List

# :note: imports are checked in order to allow execution of this script directly from downloaded project
# which may be useful as this script is meant for debugging
dirWhereIs_hwtHls = Path(__file__).parent.parent
for libName in ['pyMathBitPrecise', 'ipCorePackager', 'hdlConvertorAst',
                'pyDigitalWaveTools', 'hwtSimApi', 'hwt', 'hwtLib',
                'hwtHls', 'hwtHlsGdb']:
    try:
        importlib.import_module(libName)
    except ImportError:
        sys.path.append(str(dirWhereIs_hwtHls.parent / libName))

from hwtHls.llvm.llvmIr import parseIR, LlvmCompilationBundle, SMDiagnostic
from hwtHlsGdb.gdbCmdHandlerLlvmIr import LLVM_IR_SRC_CODELINE_OFFSET, llvmIrIterRegs
from hwtHlsGdb.gdbLlvimIrCmdBreak import gdbLlvmIrProcessCmdBreak
from hwtHlsGdb.gdbLlvimIrCmdData import gdbLlvmIrProcessCmdData
from hwtHlsGdb.gdbLlvimIrCmdExec import gdbLlvmIrProcessCmdExec
from hwtHlsGdb.gdbLlvimIrCmdStack import gdbLlvmIrProcessCmdStack
from hwtHlsGdb.gdbLlvimIrCmdTarget import gdbLlvmIrProcessCmdTarget
from hwtHlsGdb.gdbLlvimIrCmdThread import gdbLlvmIrProcessCmdThread
from hwtHlsGdb.gdbLlvimIrCmdVar import gdbLlvmIrProcessCmdVar
from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import gdbMiEscapeStr, NL, \
    parseGdbCmd, GdbMiCmd, gdbMsgFormatFrame, sendReplyDone, writeCmdToDebugFile, sendGdbPrompt, \
    format_exception, TeeedFile

VERSION = """\
GNU gdb (Ubuntu 13.1-2ubuntu2) 13.1
Hwt gdbLlvmMir GDB stub"""

USAGE = """
"""


def createArgumentParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--interpreter', dest='interpreter', action='append', default=[])
    parser.add_argument('-ex', dest='ex', action='append', default=[])
    parser.add_argument('--nx', dest='nx', action='store_true')
    parser.add_argument('-q', dest='q', action='store_true')
    parser.add_argument("--tty", dest='tty', action="store")
    parser.add_argument('--version', dest='version', action='store_true')
    return parser


def gdbShowVersion(f):
    for line in (VERSION + USAGE).split("\n"):
        f.write('~')
        f.write(gdbMiEscapeStr(line + "\n"))
        f.write(NL)


def main(argv: Optional[List[str]]=None, dbgFile: Optional[IO[Any]]=None):
    parser = createArgumentParser()
    args = parser.parse_args(args=argv)
    timeout = 0.01
    stdin = TeeedFile(sys.stdin, dbgFile)
    stdout = TeeedFile(sys.stdout, dbgFile)

    if args.version:
        stdout.write(VERSION.replace("\n", NL) + NL)
        return 0
    # else:
    #    print(VERSION + USAGE)
    if dbgFile is not None:
        dbgFile.write(' '.join(sys.argv))
        dbgFile.write('\n')
        dbgFile.flush()
    state = GdbInterpretState(dbgFile)
    with ExitStack() as exitStack:
        state.exitStack = exitStack
        try:
            for interpretIo in args.interpreter:
                if interpretIo == 'mi2' or interpretIo == 'mi':
                    # stdout.write(f'=thread-group-added,id="i1"{NL}')
                    gdbShowVersion(stdout)
                    pass

                elif interpretIo == 'console':
                    stdout.write(VERSION.replace("\n", NL) + NL)
                else:
                    raise NotImplementedError(interpretIo)

            stdout.flush()
            if args.tty is not None:
                state.appTty = (TeeedFile(open(args.tty, 'r'), dbgFile),
                                TeeedFile(open(args.tty, 'w'), dbgFile))
                for _io in state.appTty:
                    assert exitStack.enter_context(_io) is _io
                # exitStack.enter_context(IoRawNonBlocking(appTty[0]))

            state.cmdIos = [(stdin, stdout), ]
            # exitStack.enter_context(IoRawNonBlocking(stdin))
            for ex in args.ex:
                if ex.startswith("new-ui "):
                    _, t, path = ex.split(" ")
                    if t != 'mi':
                        raise NotImplementedError(ex)
                    else:
                        path = path.strip()
                        cmdIo = (TeeedFile(open(path, 'r'), dbgFile),
                                 TeeedFile(open(path, 'w'), dbgFile))
                        for _io in cmdIo:
                            assert exitStack.enter_context(_io) is _io
                        # exitStack.enter_context(IoRawNonBlocking(cmdIo[0]))
                        state.cmdIos[-1][1].write(f"New UI allocated{NL}")
                        state.cmdIos.append(cmdIo)

                elif ex.startswith('set '):
                    # 'set pagination off',
                    pass
                elif ex == 'show version':
                    gdbShowVersion(state.cmdIos[-1][1])
                else:
                    raise NotImplementedError()

            # pollObj = select.poll()
            outputForInput = {}
            for i, o in state.cmdIos:
                # pollObj.register(i, select.POLLIN)
                outputForInput[i] = o
                sendGdbPrompt(o)

            dbgFile.write("initial ready prompt send\n")
            dbgFile.flush()

            # https://mcuoneclipse.com/2016/03/11/solving-launching-configuring-gdb-aborting-configuring-gdb/
            while True:
                gdbExit = False

                if state.remote is not None:
                    state.remote.poolInterrupts()

                if not state.cmdIos:
                    break

                toRead, _, _ = select([i for i, _ in state.cmdIos], [], [], timeout)
                for i, _ in state.cmdIos:
                    if i.hasLineAvailable() and not toRead:
                        toRead.append(i)
                for r in toRead:
                    w = outputForInput[r]
                    # dbgFile.write(f"reading {r} {r.fileno()}\n")
                    # dbgFile.flush()
                    cmdStr = r.readline()
                    if not cmdStr:
                        if r.closed:
                            dbgFile.write(f"closing {r} {r.fileno()}\n")
                            dbgFile.flush()
                            state.cmdIos.remove((r, w))
                        # else:
                        #    sleep(timeout)

                        continue
                    # cmdStr = cmdStr.decode("utf-8")

                    # interpreter-exec mi2 1-list-features
                    # 1^done,features=["frozen-varobjs","pending-breakpoints","thread-info","data-read-memory-bytes","breakpoint-notifications","ada-task-info","language-option","info-gdb-mi-command","undefined-command-error-code","exec-run-start-option","data-disassemble-a-option","python"]
                    cmd = parseGdbCmd(cmdStr)
                    if dbgFile:
                        writeCmdToDebugFile(cmd, dbgFile)

                    # https://sourceware.org/gdb/current/onlinedocs/gdb
                    if cmd is not None and cmd.name == "interpreter-exec":
                        if len(cmd.args) > 3 and cmd.args[0] == '--thread-group' and cmd.args[1] == 'i1' and cmd.args[2] == 'console':
                            icmd = cmd.args[3]
                            if icmd == '"p/x (char)-1"':
                                w.write(f'~”$1 = 0xff\\n”{NL}')
                                sendReplyDone(cmd, w, dbgFile, ())
                                continue
                            elif icmd == '"show endian"':
                                w.write(f'~”The target endianness is set automatically (currently little endian)\\n”{NL}')
                                sendReplyDone(cmd, w, dbgFile, ())
                                continue
                            else:
                                newCmd = cmd.args[3][1:-1].split()
                                cmd = GdbMiCmd(cmd.token, newCmd[0], [], newCmd[1:])
                                if dbgFile:
                                    writeCmdToDebugFile(cmd, dbgFile)
                        elif cmd.args[0] == "console":
                            newCmd = cmd.args[1][1:-1].split()
                            cmd = GdbMiCmd(cmd.token, newCmd[0], [], newCmd[1:])
                            if dbgFile:
                                writeCmdToDebugFile(cmd, dbgFile)

                    if cmd is None:
                        pass
                    elif cmd.name.startswith("break-") and gdbLlvmIrProcessCmdBreak(cmd, r, w, state):
                        continue

                    elif cmd.name.startswith("data-") and gdbLlvmIrProcessCmdData(cmd, r, w, state):
                        continue

                    elif cmd.name == "environment-cd":
                        os.chdir(cmd.args[0])
                        sendReplyDone(cmd, w, dbgFile, ())
                        continue

                    elif cmd.name == 'enable-pretty-printing':
                        sendReplyDone(cmd, w, dbgFile, ())
                        continue

                    elif cmd.name.startswith("exec-") and gdbLlvmIrProcessCmdExec(cmd, r, w, state):
                        continue

                    elif cmd.name == 'gdb-exit' or cmd.name == 'kill':
                        errMsg = f'^exit{NL}'
                        dbgFile.write('<-: ')
                        w.write(errMsg)
                        gdbExit = True
                        break

                    elif cmd.name == "gdb-set":
                        args = cmd.args
                        if args == ["breakpoint", "pending", "on"] or\
                           args == ['detach-on-fork', 'on'] or \
                           args == ['python', 'print-stack', 'none'] or \
                           args == ['print', 'object', 'on'] or \
                           args == ['print', 'sevenbit-strings', 'on'] or \
                           args == ['host-charset', 'UTF-8'] or \
                           args == ['target-charset', 'UTF-8'] or \
                           args == ['target-wide-charset', 'UTF-32'] or \
                           args == ['dprintf-style', 'call'] or \
                           args == ['mi-async', 'on'] or \
                           args == ['record', 'full', 'stop-at-limit', 'off'] or \
                           args == ['auto-solib-add', 'on'] or \
                           args == ['--thread-group', 'i1', 'language', 'c'] or \
                           args == ['--thread-group', 'i1', 'language', 'auto'] or \
                           args[0] == "solib-search-path" or \
                           args == ['stop-on-solib-events', '1']:
                            sendReplyDone(cmd, w, dbgFile, ())
                            continue

                    elif cmd.name == "gdb-show" or cmd.name == 'show':
                        if cmd.args == ['--thread-group', 'i1', 'language']:
                            sendReplyDone(cmd, w, dbgFile, (("value", '"auto"'),))
                            continue
                        elif cmd.args == ['architecture']:
                            print('The target architecture is set to "auto" (currently "i386").', end=NL)
                            sendReplyDone(cmd, w, dbgFile, ())
                            continue

                    elif cmd.name == 'gdb-version':
                        gdbShowVersion(w)
                        sendReplyDone(cmd, w, dbgFile, ())
                        continue

                    elif cmd.name == 'file-exec-and-symbols':
                        state.exe = cmd.args[-1]
                        # exe = os.path.relpath(exe, start=os.getcwd())
                        state.llvm = LlvmCompilationBundle(state.exe, [])
                        Err = SMDiagnostic()
                        with open(state.exe) as irFile:
                            irStr = irFile.read()
                            M = parseIR(irStr, "test", Err, state.llvm.ctx)
                            if M is None:
                                raise AssertionError(Err.str("test", True, True))
                            else:
                                fns = tuple(M)
                                state.llvm.main = fns[0]
                        state.llvmRegs = tuple(llvmIrIterRegs(LLVM_IR_SRC_CODELINE_OFFSET, 1, state.llvm.main, False))
                        state.tmpVariablesIdCntr = max(0 if r.registerIndex is None else r.registerIndex for r in state.llvmRegs)
                        sendReplyDone(cmd, w, dbgFile, ())
                        continue

                    elif cmd.name == 'list-features':
                        features = ["frozen-varobjs", "pending-breakpoints", "thread-info",
                                    "data-read-memory-bytes", "breakpoint-notifications", "ada-task-info",
                                    "language-option", "info-gdb-mi-command", "undefined-command-error-code",
                                    "exec-run-start-option", "data-disassemble-a-option", "python"]
                        sendReplyDone(cmd, w, dbgFile, (("features", features),))
                        continue
                        # 1^done,features=["frozen-varobjs","pending-breakpoints","thread-info","data-read-memory-bytes","breakpoint-notifications","ada-task-info","language-option","info-gdb-mi-command","undefined-command-error-code","exec-run-start-option","data-disassemble-a-option","python"]

                    elif cmd.name == 'list-thread-groups':
                        # https://www.zeuthen.desy.de/dv/documentation/unixguide/infohtml/gdb/GDB_002fMI-Miscellaneous-Commands.html
                        if cmd.args == []:
                            sendReplyDone(cmd, w, dbgFile, (("groups", f'[{{id="i1",type="process",pid="1",executable="target:{"/" if state.exe is None else state.exe:s}",cores=["0"]}}]'),))
                            continue
                        elif cmd.args == ['i1']:
                            frame = gdbMsgFormatFrame(0 if state.remote is None else state.remote.readRegister(0) // 8, state.llvm, state.exe)
                            doneArgs = (("threads", f'[{{id="1",target-id="Thread 0.0",name="{state.llvm.main.getName().str():s}",frame={frame},state="stopped",core="3"}}]'),)
                            sendReplyDone(cmd, w, dbgFile, doneArgs)
                            continue

                    elif cmd.name == "set":
                        if cmd.args == ["pagination", 'off']:
                            sendReplyDone(cmd, w, dbgFile, ())
                            continue

                    elif cmd.name == 'source':
                        if cmd.args == ['.gdbinit']:
                            sendReplyDone(cmd, w, dbgFile, ())
                            continue

                    elif cmd.name.startswith('stack-') and gdbLlvmIrProcessCmdStack(cmd, r, w, state):
                        continue

                    elif cmd.name == 'symbol-list-lines':
                        if len(cmd.args) == 1:
                            f = cmd.args[0]
                            if f == state.exe:
                                regs = [f'{{pc="0x{r.codeline*8:x}",line="{r.codeline}"}}' for r in state.llvmRegs]
                                doneArgs = (('lines', f'[{",".join(regs):s}]'),)  # {name="x",value="11"}
                                sendReplyDone(cmd, w, dbgFile, doneArgs)

                    elif cmd.name.startswith('thread-') and gdbLlvmIrProcessCmdThread(cmd, r, w, state):
                        continue
                    elif cmd.name.startswith("target-") and gdbLlvmIrProcessCmdTarget(cmd, r, w, state):
                        continue
                    elif cmd.name == 'trace-status':
                        if cmd.args == []:
                            doneArgs = (('supported', '"1"'), ('running', '"0"'),
                                        ('frames', '"0"'), ('frames-created', '"0"'),
                                        ('buffer-size', '"5242880"'), ('buffer-free', '"5242880"'),
                                        ('disconnected', '"0"'), ('circular', '"0"'),
                                        ('user-name', '""'), ('notes', '""'),
                                        ('start-time', '"0.000000"'), ('stop-time', '"0.000000"'))
                            sendReplyDone(cmd, w, dbgFile, doneArgs)
                            continue

                    elif cmd.name.startswith("var-") and gdbLlvmIrProcessCmdVar(cmd, r, w, state):
                        continue

                    errMsg = f'^error,msg={gdbMiEscapeStr(cmdStr):s}{NL}'
                    dbgFile.write('<-: ')
                    w.write(errMsg)
                    sendGdbPrompt(w)

                if gdbExit:
                    break

            dbgFile.write('finished successfully\n')
            dbgFile.flush()
        except Exception as e:
            dbgFile.write(format_exception(e))
            dbgFile.flush()
            raise


if __name__ == "__main__":
    with open("gdb_out.txt", "w") as dbgFile:
        try:
            main(dbgFile=dbgFile)
        except Exception as e:
            print(format_exception(e))
            sys.exit(1)
