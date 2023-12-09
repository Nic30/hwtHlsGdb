import logging
import re
from select import select
import socket

from hwtHlsGdb.gdbCmdHandler import GdbCmdHandler
from hwtHlsGdb.gdbRemoteMessages import gdbReplyError, gdbReplyOk, \
    gdbReplyUnsupported, gdbPacketReply, gdbParserReply, gdbReplyStopped, \
    GdbTargetSignal


logging.basicConfig(level=logging.DEBUG)
debug = logging.getLogger('gss:gdb-server-stub').debug
trace = logging.getLogger('gss:gdb-server-stub:trace').debug


class GDBServerStub():
    """
    GDB Server Stub is a GDB server for remote debugging.
    It translates low level operations fro GDB remote protocol and passes them to target (in this case to simulator).
    
    Based on https://github.com/nomtats/gdbserver-stub
    """

    def __init__(self, handler: GdbCmdHandler):
        self.handler = handler
        self.noAckMode = False
        self.timeout = 0.001
        self.exeStopped = True
        self.COMMON_QUERIES = (
            (re.compile("^qTStatus"), handler.handle_qTStatus),
            (re.compile('^qfThreadInfo'), handler.handleThreadInfo),
            (re.compile('^qsThreadInfo'), lambda : gdbReplyOk('l')), # l indicates the end of the list.
            (re.compile('^qTfV'), handler.handle_qTfV),
            (re.compile("^qTsV"), handler.handle_qTsV),
            (re.compile('^qC'), self.handler.handleCurrentThread),
        )

#    def __enter__(self, host:str="127.0.0.1", port:int=10000):
#        try:
#            self.start(host, port)
#        except:
#            self.stop()
#            raise
#        return self
#
#    def __exit__(self, exc_type, exc_value, traceback):
#        self.stop()

    def start(self, host:str="127.0.0.1", port:int=10000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            debug(f"GDBServerStub started at {(host, port)}")
            s.listen()
            conn, addr = s.accept()
            with conn:
                debug(f"Connection accepted: {addr}")

                while True:
                    toRead, _, _ = select((conn,), (), (), self.timeout)
                    if toRead:
                        data = conn.recv(1024)
                        self.onData(conn, data)

                    if not self.exeStopped:
                        try:
                            print("running: ", self.handler.instr)
                            breakAddr = self.handler.runCurrentInstr()
                        except:
                            conn.send(gdbPacketReply(gdbReplyStopped(GdbTargetSignal.SIGKILL)))
                            self.exeStopped = True
                            break

                        if breakAddr is not None:
                            conn.send(gdbPacketReply(gdbReplyStopped(GdbTargetSignal.TRAP)))
                            self.exeStopped = True

            debug("Connection closed")

        debug("Server shutdown")

    def onData(self, soc: socket.socket, data: bytes):
        """
        Process all packets in data
        """
        inp = data.decode()
        err = False
        while inp:
            while True:
                m = re.match('^\+', inp)
                if m is not None:
                    # ack
                    trace(f"<-:{m.group(0)}")
                    break
                replyPkt = gdbParserReply(inp)
                if replyPkt is not None:
                    trace(f'<-:{replyPkt}')
                    m, replyPkt = replyPkt
                    self.handlePacket(soc, replyPkt)
                    break
                else:
                    trace(f'<-:{input}')
                    debug(f'Unkown incoming message: {input}')
                    # Ignore the rest of the data.
                    err = True
                    break
            if err:
                break
            inp = inp[len(m.group(0)):]

    def handlePacket(self, soc: socket.socket, packet: str):
        if not self.noAckMode:
            # Reply with an acknowledgement first.
            trace("->:+")
            soc.send(b"+")

        while True:  # while True to flatten elifs
            if packet == "?":
                reply = self.handler.handleHaltReason()
                break

            elif packet == "g":
                reply = self.handler.handleReadRegisters()
                break

            elif packet == 'vCtrlC':
                self.exeStopped = True
                reply = self.handler.handleInterruption()
                message = gdbPacketReply(reply)
                trace(f'->:{message}')
                soc.send(message)
                reply = gdbReplyStopped(GdbTargetSignal.INT)
                break

            m = re.match('^G([0-9a-zA-Z]+)', packet)
            if m is not None:
                values = int(m.group(1), 16)
                reply = self.handler.handleWriteRegisters(values)
                break

            m = re.match('^m([0-9a-zA-Z]+),([0-9a-zA-Z]+)', packet)
            if m is not None:
                address = int(m.group(1), 16)
                length = int(m.group(2), 16)
                reply = self.handler.handleReadMemory(address, length)
                break

            m = re.match('^M([0-9a-zA-Z]+),([0-9a-zA-Z]+):([0-9a-zA-Z]+)', packet)
            if m is not None:
                address = int(m.group(1), 16)
                length = int(m.group(2), 16)
                dataBytes = int(m.group(3), 16)
                if length != len(dataBytes):
                    # The spec doesn't specify what should happen when the length parameter doesn't
                    # match the incoming data. We just reply with error 1 here.
                    reply = gdbReplyError(0)
                else:
                    reply = self.handler.handleWriteMemory(address, dataBytes)
                break

            m = re.match('^s([0-9a-zA-Z]+)?', packet)
            if m is not None:
                address = None
                if m.group(1) is not None:
                    address = int(m.group(1), 16)
                reply = self.handler.handleStep(address)
                self.exeStopped = False
                break

            m = re.match('^c([0-9a-zA-Z]+)?', packet)
            if m is not None:
                address = None
                if m.group(1) is not None:
                    address = int(m.group(1), 16)
                reply = self.handler.handleContinue(address)
                self.exeStopped = False
                break

            m = re.match('^qSupported:(.*)', packet)
            if m is not None:
                features = []
                for x in m.group(1).split(';'):
                    key = x
                    value = None
                    if x.endswith('+'):
                        key = x[:len(x) - 1]
                        value = True
                    elif x.endswith('-'):
                        key = x.substr[:len(x) - 1]
                        value = False
                    elif '=' in x:
                        key, value = x.split('=')
                    obj = {}
                    obj[key] = value
                    features.append(obj)
                reply = self.handler.handleQSupported(features)
                break

            m = re.match('^QStartNoAckMode', packet)
            if m is not None:
                reply = gdbReplyOk(None)
                self.noAckMode = True
                break
            
            for regex, handler in self.COMMON_QUERIES:
                m = regex.match(packet)
                if m is not None:
                    reply = handler()
                    break
            if m is not None:
                break
            
            m = re.match('^H([cgm])(-?[0-9]+)', packet)
            if m is not None:
                threadId = int(m.group(2), 16)
                cmd = m.group(1)
                if cmd == 'c':
                    reply = self.handler.handleSelectExecutionThread(threadId)
                elif cmd == 'm':
                    reply = self.handler.handleSelectMemoryThread(threadId)
                elif cmd == 'g':
                    reply = self.handler.handleSelectRegisterThread(threadId)
                else:
                    reply = gdbReplyUnsupported()
                break

            m = re.match('^([zZ])([0-4]),([0-9a-zA-Z]+),([0-9a-zA-Z]+)', packet)
            if m is not None:
                dtype = int(m.group(2))
                addr = int(m.group(3), 16)
                kind = int(m.group(4), 16)
                if m.group(1) == 'z':
                    reply = self.handler.handleRemoveBreakpoint(dtype, addr, kind)
                elif m.group(1) == 'Z':
                    reply = self.handler.handleAddBreakpoint(dtype, addr, kind)
                break

            m = re.match('^qHostInfo', packet)
            if m is not None:
                reply = self.handler.handleHostInfo()
                break

            m = re.match('^qProcessInfo', packet)
            if m is not None:
                reply = gdbReplyOk('pid:1;endian:little;')
                break

            m = re.match('^qRegisterInfo([0-9a-zA-Z]+)', packet)
            if m is not None:
                registerIndex = int(m.group(1), 16)
                reply = self.handler.handleRegisterInfo(registerIndex)
                break

            m = re.match('^qMemoryRegionInfo:([0-9a-zA-Z]+)', packet)
            if m is not None:
                address = int(m.group(1), 16)
                reply = self.handler.handleMemoryRegionInfo(address)
                break
            m = re.match('^p([0-9a-zA-Z]+)', packet)
            if m is not None:
                registerIndex = int(m.group(1), 16)
                reply = self.handler.handleReadRegister(registerIndex)
                break

            m = re.match('^vMustReplyEmpty', packet)
            if m is not None:
                reply = gdbReplyOk('')
                break
            else:
                reply = gdbReplyUnsupported()
                break

        if reply is not None:
            message = gdbPacketReply(reply)
            trace(f'->:{message}')
            soc.send(message)

