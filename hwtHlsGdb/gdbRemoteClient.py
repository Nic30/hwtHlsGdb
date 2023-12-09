import binascii
import re
from select import select
import socket
from typing import Optional, Dict, Union, Literal, Callable, IO, Any

from hwtHlsGdb.gdbRemoteMessages import GdbRemotePktAck, gdbParserReply, \
    gdbPacketReply, GdbBreakPointType, GdbRemotePktStopped


class GdbRemoteClient():

    def __init__(self, host: str, port: int, interuptHandler: Callable[["GdbRemoteClient", GdbRemotePktStopped], None], dbgFile: Optional[IO[Any]]):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.noAckMode = False
        self.receiveBuffer = ""
        self._receivedPkt = None  # temporary to support push back of the packet during processing
        self.stubSupported: Dict[str, bool] = {}
        self.timeout = 0.001
        self._onInterrupt = interuptHandler
        self._dbgFile = dbgFile

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.socket is not None:
            self._close()

    def receiveAck(self):
        pkt = self.receivePkt()
        assert pkt is GdbRemotePktAck, ("expected ack", pkt)

    def receivePktUndo(self, pkt):
        assert self._receivedPkt is None
        self._receivedPkt = pkt

    def sendAck(self):
        return self.socket.send(b'+')

    def poolInterrupts(self):
        pkt = self.receivePkt(False)
        if pkt is not None:
            self.receivePktUndo(pkt)

    def receivePkt(self, blocking: bool=True) -> Union[None, str, Literal[GdbRemotePktAck]]:
        pkt = self._receivedPkt
        if pkt is not None:
            self._receivedPkt = None
            return pkt

        buff = self.receiveBuffer
        if not buff:
            if blocking:
                buff = self.receiveBuffer = self.socket.recv(1024).decode()
            else:
                toRead, _, _ = select((self.socket,), (), (), self.timeout)
                if toRead:
                    buff = self.receiveBuffer = self.socket.recv(1024).decode()
                else:
                    return None

        assert buff

        if buff[0] == '+':
            self.receiveBuffer = buff[1:]
            return GdbRemotePktAck

        replyPkt = gdbParserReply(buff)
        if replyPkt is not None:
            m, replyPkt = replyPkt
            buff = self.receiveBuffer = buff[len(m.group(0)):]
            self._dbgFile.write("remote -> ")
            self._dbgFile.write(replyPkt)
            self._dbgFile.write('\n')
            intrM = re.match("^S([0-9a-fA-F]{2})", replyPkt)
            if intrM:
                self._onInterrupt(self, GdbRemotePktStopped(int(intrM.group(1), 16)))
                return self.receivePkt(blocking)

            return replyPkt  # return regular packet
        else:
            raise AssertionError("Invalid packet")

    def sendContinue(self):
        self.socket.send(gdbPacketReply('c'))
        okReply = self.receivePkt()
        assert okReply == "OK", okReply

    def sendStep(self):
        self.socket.send(gdbPacketReply('s'))
        okReply = self.receivePkt()
        assert okReply == "OK", okReply

    def sendInterrupt(self):
        self.socket.send(gdbPacketReply("vCtrlC"))
        okReply = self.receivePkt()
        assert okReply == "OK", okReply

    # def execRun(self):
    #    return self.sendContinue()

    def breakInsert(self, addr: int):
        self.socket.send(gdbPacketReply(f"Z{GdbBreakPointType.HARDWARE:d},{addr:x},0"))
        okReply = self.receivePkt()
        assert okReply == "OK", okReply
    
    def breakDelete(self, addr):
        self.socket.send(gdbPacketReply(f"z{GdbBreakPointType.HARDWARE:d},{addr:x},0"))
        okReply = self.receivePkt()
        assert okReply == "OK", okReply

    def readRegister(self, regIndex: int):
        self.socket.send(gdbPacketReply(f"p{regIndex:x}"))
        reply = self.receivePkt()
        try:
            return int.from_bytes(binascii.unhexlify(reply), 'little')
        except:
            raise ValueError(reply)

    def _connect(self):
        soc = self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        soc.connect((self.host, self.port))
        """
        +
        $qSupported:...#77
        +
        $...#48
        +
        $vMustReplyEmpty#3a
        +
        $#00
        +
        $QStartNoAckMode#b0
        +
        $OK#9a
        +
        """
        soc.send(gdbPacketReply('qSupported:multiprocess+;swbreak+;hwbreak+'))
        self.receiveAck()
        supported = self.receivePkt()
        for feature in supported.split(";"):
            isSupported = feature[-1]
            feature = feature[:-1]
            if isSupported == '+':
                isSupported = True
            elif isSupported == '+':
                isSupported = True
            else:
                raise ValueError("Unknonw spec for feature from stub", feature, isSupported)
            self.stubSupported[feature] = isSupported

        soc.send(gdbPacketReply('vMustReplyEmpty'))
        self.receiveAck()
        emptyReply = self.receivePkt()
        assert emptyReply == '', emptyReply
        self.sendAck()

        soc.send(gdbPacketReply('QStartNoAckMode'))
        self.receiveAck()
        self.noAckMode = False
        okReply = self.receivePkt()
        assert okReply == "OK", okReply
        self.sendAck()

    def _close(self):
        if self.socket is not None:
            self.socket.close()

