from typing import Any, IO

from hwtHlsGdb.gdbLlvimIrInterpretState import GdbInterpretState
from hwtHlsGdb.gdbMiMessages import GdbMiCmd, \
    NL, sendReplyConnected, format_exception, \
    sendGdbPrompt, gdbMiEscapeStr, gdbMsgFormatStopped, \
    gdbMsgFormatStoppedByInterrupt, sendReplyDone
from hwtHlsGdb.gdbRemoteClient import GdbRemoteClient
from hwtHlsGdb.gdbRemoteMessages import GdbRemotePktStopped, \
    GdbTargetSignal


def gdbLlvmIrProcessCmdTarget(cmd: GdbMiCmd, r: IO[Any], w: IO[Any], state: GdbInterpretState):
    dbgFile = state.dbgFile
    if cmd.name == 'target-select':
        if cmd.args[0] == 'remote':
            assert len(cmd.args) == 2, cmd.args
            targetHost, targetPort = cmd.args[1].split(":")

            def interuptHandler(remote:GdbRemoteClient, pkt):
                if isinstance(pkt, GdbRemotePktStopped):
                    codeline = remote.readRegister(0) // 8
                    if pkt.reason == GdbTargetSignal.TRAP:
                        msg = gdbMsgFormatStopped(codeline, state.llvm, state.exe)
                    elif pkt.reason == GdbTargetSignal.INT:
                        msg = gdbMsgFormatStoppedByInterrupt(codeline, state.llvm, state.exe)
                    elif pkt.reason == GdbTargetSignal.SIGKILL:
                        msg = gdbMsgFormatStoppedByInterrupt(codeline, state.llvm, state.exe)
                    else:
                        raise NotImplementedError(pkt.reason)

                    w.write(msg)
                    w.write(NL)
                    w.flush()
                    # sendGdbPrompt(w)
                else:
                    raise NotImplementedError(pkt)

            state.remote = GdbRemoteClient(targetHost, int(targetPort), interuptHandler, dbgFile)
            w.write(f'=tsv-created,name="trace_timestamp",initial="0"{NL}')
            w.flush()
            # sendGdbPrompt(w)
            w.write(f'=thread-group-started,id="i1",pid="0"{NL}')
            # sendGdbPrompt(w)
            w.flush()
            w.write(f'=thread-created,id="1",group-id="i1"{NL}')
            # sendGdbPrompt(w)
            w.flush()
            try:
                _remote = state.exitStack.enter_context(state.remote)
                assert _remote is state.remote
                assert state.remote.socket is not None
                # for _, _w in cmdIos:
                # w.write('~"\\nThis GDB supports auto-downloading debuginfo from the following URLs:\\n"' + NL)
                # w.write('~"  <https://debuginfod.ubuntu.com>\\n"' + NL)
                # w.write('~"Enable debuginfod for this session? (y or [n]) "' + NL)
                # w.write(gdbMsgFormatStopped(LLVM_IR_SRC_CODELINE_OFFSET, llvm, exe))
                # w.write(NL)
                # _w.write('*stopped,frame={addr="0x000000",func="_start",args=[],'
                #        'from="target:/lib64/ld-linux-x86-64.so.2",arch="i386:x86-64"},'
                #        'thread-id="1",stopped-threads="all",core="10"' + NL)
                #sendReplyConnected(cmd, w, dbgFile, ())

                # w.write('*stopped,frame={addr="0x00007ffff7fe4da0",func="_start",args=[],from="target:/lib64/ld-linux-x86-64.so.2",arch="i386:x86-64"},thread-id="1",stopped-threads="all",core="0"' + NL)
                # vscode requires done instead connected
                sendReplyDone(cmd, w, dbgFile, ())
            except Exception as e:
                dbgFile.write(format_exception(e))
                dbgFile.write('\n')
                errMsg = f'^error,msg={gdbMiEscapeStr(repr(e))}{NL}'
                w.write(errMsg)
                sendGdbPrompt(w)
                state.remote = None
            return True
    return False
