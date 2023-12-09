import os
from pathlib import Path
import re
import sys
import traceback
from typing import Optional, List, Tuple, IO, Any, Deque

from hwtHls.llvm.llvmIr import LlvmCompilationBundle
from collections import deque

NL = '\r\n'
# NL = '\n'


# class IoRawNonBlocking(object):
#
#    def __init__(self, stream):
#        self.stream = stream
#        self.fd = self.stream.fileno()
#
#    def __enter__(self):
#        # set to raw
#        self.original_stty = termios.tcgetattr(self.stream)
#        tty.setcbreak(self.stream)
#        # set to non blocking
#        self.orig_fl = fcntl.fcntl(self.fd, fcntl.F_GETFL)
#        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl | os.O_NONBLOCK)
#        return self
#
#    def __exit__(self, type, value, traceback):
#        # undo non blocking
#        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl)
#        # undo raw
#        termios.tcsetattr(self.stream, termios.TCSANOW, self.original_stty)
#
#
class TeeedFile():
    RE_LINE = '\n'

    def __init__(self, mainFile: IO[Any], dupFile: IO[Any]):
        self.mainFile = mainFile
        self.dupFile = dupFile
        self.buff: Deque[str] = deque()

    def __enter__(self):
        self.mainFile = self.mainFile.__enter__()
        return self

    def __exit__(self, t, value, traceback):
        self.mainFile.__exit__(t, value, traceback)

    @property
    def closed(self):
        return self.mainFile.closed

    def fileno(self):
        return self.mainFile.fileno()

    def hasLineAvailable(self):
        return len(self.buff) > 1  # "\n".split('\n') == ['', ''] so if there was line there must be at least 2 items

    def readline(self):
        # use os.read directly to avoid
        buff = self.buff
        if len(buff) > 1:
            d = self.buff.popleft() + '\n'
        else:
            d = os.read(self.mainFile.fileno(), 1024).decode()
            if buff:
                last = buff.pop()
                d = last + d
            buff.extend(d.split('\n'))
            if len(buff) > 1:
                d = buff.popleft() + '\n'
            else:
                d = ""

        self.dupFile.write(d)
        return d

    def write(self, d):
        self.dupFile.write(d)
        self.mainFile.write(d)

    def flush(self):
        self.dupFile.flush()
        self.mainFile.flush()

    def __repr__(self):
        return f"<{self.__class__.__name__:s} {self.mainFile} {self.dupFile}>"


class GdbMiCmd():

    def __init__(self, token: Optional[int], name: str, params: List[Tuple[str, List[str]]], args: List[str]):
        self.token = token
        self.name = name
        self.params = params
        self.args = args

    def __repr__(self):
        t = self.token
        cmd = f'{self.token if t is not None else ""}-{self.name}'
        if self.params:
            params = ",".join(f"{aName}={aVal}" for aName, aVal in self.params)
            cmd = cmd + "," + params
        return f"<{self.__class__.__name__} {' '.join((cmd, *self.args))}>"


def gdbMiEscapeStrChar(c: str, quoter: Optional[str], sevenbit_strings:bool):
    """
    :based on gdb ui_file::printchar
    """
    _c = ord(c)
    assert _c <= 0xFF, (c, "ASCII only")
    if (_c < 0x20 or  # Low control chars
            (_c >= 0x7F and _c < 0xA0) or  # DEL, High controls
            (sevenbit_strings and _c >= 0x80)):
        # high order bit set
        yield '\\'

        if c == '\n':
            yield 'n';
        elif c == '\b':
            yield 'b'
        elif c == '\t':
            yield 't';
        elif c == '\f':
            yield 'f';
        elif c == '\r':
            yield 'r';
        elif c == '\033':
            yield 'e';
        elif c == '\007':
            yield 'a';
        else:
            yield chr(ord('0') + ((_c >> 6) & 0x7));
            yield chr(ord('0') + ((_c >> 3) & 0x7));
            yield chr(ord('0') + ((_c >> 0) & 0x7));
    else:
        if (quoter is not None and (c == '\\' or c == quoter)):
            yield '\\'
        yield c


def gdbMiEscapeStr(text: str, sevenbit_strings:bool=True):
    """
    MI-mode escapes are similar to standard Python escapes but:
    * "\\e" is a valid escape.
    * "\\NNN" escapes use numbers represented in octal format.
      For instance, "\\040" encodes character 0o40, that is character 32 in decimal,
      that is a space.
    
    :based on gdb ui_file::printchar
    
    :param sevenbit_strings:True means that strings with character values >0x7F should be printed
       as octal escapes.  False means just print the value (e.g. it's an
       international character, and the terminal or window can cope.)
    """
    buff = []
    for c in text:
        buff.extend(gdbMiEscapeStrChar(c, '"', sevenbit_strings))
    _text = ''.join(buff)
    return f'"{_text:s}"'


def parseGdbCmd(gdbCmdStr: str):
    m = re.match('^(\d*)(-?)(.+)\n', gdbCmdStr)  # gdb/mi cmd
    if m is None:
        return None
    if m.group(1):
        token = int(m.group(1))
    else:
        token = None

    cmd = None
    args = []
    # id or string with escapes
    for gId, gStr, _  in re.findall(r'([a-zA-Z0-9/_\-\*\.:]+)|("[^"\\]*(\\.[^"\\]*)*")', m.group(3)):
        if cmd is None:
            cmd = gId
        elif gId:
            assert cmd is not None, gdbCmdStr
            args.append(gId)
        else:
            args.append(gStr)

    params = cmd.split(",")  # todo
    cmd = params[0]
    params = params[1:]

    return GdbMiCmd(token, cmd, params, args)


def gdbCmdResRunning(token: Optional[int], args:List[Tuple[str, List[str]]]):
    parts = [f"{token}^running" if token is not None else f"^running"]
    parts.extend(_gdbCmdFormatArgs(args))
    return ",".join(parts)


def gdbCmdInterruptRunning(args:List[Tuple[str, List[str]]]):
    parts = [f"*running"]
    parts.extend(_gdbCmdFormatArgs(args))
    return ",".join(parts)


def sendReplyConnected(cmd: GdbMiCmd, w: IO[Any], dbgFile: IO[Any], args:List[Tuple[str, List[str]]]):
    parts = [f"{cmd.token}^connected" if cmd.token is not None else f"^connected"]
    parts.extend(_gdbCmdFormatArgs(args))
    resp = ",".join(parts)
    dbgFile.write("<-: ")
    w.write(resp)
    w.write(NL)
    sendGdbPrompt(w)


def sendReplyDone(cmd: GdbMiCmd, w: IO[Any], dbgFile: IO[Any], args: Tuple):
    resp = gdbCmdResDone(cmd.token, args)
    if dbgFile:
        dbgFile.write("<-: ")
    w.write(resp)
    w.write(NL)
    sendGdbPrompt(w)


def sendReplyRunning(cmd: GdbMiCmd, w: IO[Any], dbgFile: IO[Any], args: Tuple):
    resp = gdbCmdResRunning(cmd.token, args)
    if dbgFile:
        dbgFile.write("<-: ")
    w.write(resp)
    w.write(NL)
    sendGdbPrompt(w)


def sendInterruptRunning(w: IO[Any], dbgFile: IO[Any], args: Tuple):
    resp = gdbCmdInterruptRunning(args)
    if dbgFile:
        dbgFile.write("<-: ")
    w.write(resp)
    w.write(NL)
    w.flush()


def _gdbCmdFormatArgs(args:List[Tuple[str, List[str]]]):
    for argName, argVal in args:
        if isinstance(argVal, (list, tuple)):
            argVal = f"[{','.join(gdbMiEscapeStr(a) for a in argVal)}]"
        yield f"{argName}={argVal}"


def gdbCmdResDone(token: Optional[int], args:List[Tuple[str, List[str]]]):
    parts = [f"{token}^done" if token is not None else f"^done"]
    parts.extend(_gdbCmdFormatArgs(args))
    return ",".join(parts)


def gdbMsgFormatFrame(codeline: int, llvm: Optional[LlvmCompilationBundle], exeName: Optional[str]):
    return (f'{{level="0",addr="0x{codeline*8:016x}",func="{llvm.main.getName().str() if llvm else "invalid":s}",'
            f'file="{Path(exeName).name if exeName else "invalid":s}",fullname="{exeName if exeName else "invalid":s}",line="{codeline:d}",'
            f'arch="i386:x86-64"}}')


def gdbMsgFormatStack(codeline: int, llvm: LlvmCompilationBundle, exeName: str):
    return (f'[frame={gdbMsgFormatFrame(codeline, llvm, exeName):s}]')


def gdbMsgFormatBreakpoint(llvm: LlvmCompilationBundle, exeName: str, codeline:int, number:int, addr:int):
    return (
        f'{{number="{number:d}",type="breakpoint",disp="keep",enabled="y",addr="0x{addr:x}",'
        f'func="{llvm.main.getName().str():s}",file="{Path(exeName).name:s}",fullname="{exeName:s}",line="{codeline:d}",'
        'thread-groups=["i1"],times="0"}'
    )


def gdbMsgFormatStopped(codeline: int, llvm: LlvmCompilationBundle, exeName: str):
#     https://sourceware.org/gdb/onlinedocs/gdb/GDB_002fMI-Async-Records.html#GDB_002fMI-Async-Records
    # https://sourceware.org/gdb/onlinedocs/gdb/GDB_002fMI-Program-Execution.html
    # return f'*stopped,reason="end-stepping-range",thread-id="1",frame={{file="{Path(exeName).name:s}",fullname="{exeName:s}",line="{codeline:d}",arch="i386:x86_64"}}'
    return f'*stopped,reason="end-stepping-range",frame={gdbMsgFormatFrame(codeline, llvm, exeName)},thread-id="1",stopped-threads="all",core="0"'


def gdbMsgFormatStoppedByInterrupt(codeline: int, llvm: LlvmCompilationBundle, exeName: str):
    return f'*stopped,signal-name="SIGINT",signal-meaning="Interrupt",frame={gdbMsgFormatFrame(codeline, llvm, exeName)},thread-id="1",stopped-threads="all",core="0"'
# reason="breakpoint-hit",disp="keep",bkptno="2",frame={
# func="foo",args=[],file="hello.c",fullname="/home/foo/bar/hello.c",
# line="13",arch="i386:x86_64"}


def format_exception(e):
    exceptionList = traceback.format_stack()
    exceptionList = exceptionList[:-2]
    exceptionList.extend(traceback.format_tb(sys.exc_info()[2]))
    exceptionList.extend(traceback.format_exception_only(sys.exc_info()[0], sys.exc_info()[1]))

    exceptionStr = "Traceback (most recent call last):\n"
    exceptionStr += "".join(exceptionList)
    # Removing the last \n
    exceptionStr = exceptionStr[:-1]

    return exceptionStr


def sendGdbPrompt(w: IO[Any]):
    w.write(f"(gdb) {NL}")
    w.flush()


def writeCmdToDebugFile(cmd: GdbMiCmd, dbgFile: IO[Any]):
    dbgFile.write(repr(cmd))
    if cmd is not None:
        dbgFile.write("    ")
        dbgFile.write(repr(cmd.args))
    dbgFile.write('\n')
    dbgFile.flush()


def filterArgs(args: List[str], ignoredArgs: List[List[str]]) -> List[str]:
    res = []
    argLen = len(args)
    longestPattern = 0
    for argI, a in enumerate(args):
        if longestPattern != 0:
            longestPattern -= 1
            continue

        for ignorePattern in ignoredArgs:
            prnLen = len(ignorePattern)
            if a == ignorePattern[0] and prnLen + argI <= argLen:
                longestPattern = max(longestPattern, prnLen)

        if longestPattern == 0:
            res.append(a)
        else:
            longestPattern -= 1

    return res
