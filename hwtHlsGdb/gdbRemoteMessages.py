import binascii
import re
from typing import Sequence, Union

from hwt.pyUtils.arrayQuery import grouper

ERROR_BAD_ACCESS_SIZE_FOR_ADDRESS = 0x34
# https://sourceware.org/gdb/onlinedocs/gdb/Remote-Protocol.html#Remote-Protocol



class GdbRemotePktAck():

    def __init__(self):
        raise AssertionError("This class should be used only as a constant")


class GdbRemotePktStopped():

    def __init__(self, reason: int):
        self.reason = reason

class GdbTargetSignal:
    """
    include/gdb/signals.h
    """
    INT = 2
    TRAP = 5
    SIGKILL = 9

class GdbBreakPointType:
    SOFTWARE = 0
    HARDWARE = 1
    WRITE_WATCHPOINT = 2
    READ_WATCHPOINT = 3
    ACCESS_WATCHPOINT = 4


def _uint32ToBytes(value: int):
    if value < 0:
        value = -value + 1
    return value.to_bytes(4, byteorder="little")


def _uint32ArrayToBytes(values):
    databytes = []
    for v in values:
        databytes.append(_uint32ToBytes(v))

    return b''.join(databytes)


def _bytesToUint32(databytes):
    # Always end with a >>> 0 so that the number is treated as unsigned int.
    return int.from_bytes(databytes, 'little')


def _bytesToInt32Array(databytes):
    for i32 in grouper(4, databytes, padvalue=b'\x00'):
        yield int.from_bytes(i32, 'little')


def _makeCharEscape(char: str):
    assert len(char) == 1, char
    return '}' + chr(ord(char) ^ 0x20)


def gdbMessageEscape(text: str):
    return text.translate({'}': _makeCharEscape('}'),
                           '#': _makeCharEscape('#'),
                           '$': _makeCharEscape('$'),
                           '*': _makeCharEscape('*'),
                           })


def gdbReplyOk(value):
    """
    Generates a valid reply.
    @param {number|string|object|undefined} value The content of the reply.
        - Number means the 
    """
    if value is None:
        return 'OK'
    elif isinstance(value, str):
        return gdbMessageEscape(value)
    elif isinstance(value, bytes):
        return binascii.hexlify(value).decode('ascii')
    else:
        raise AssertionError("Unkown value type", value)


def gdbReplyThreadIds(ids: Sequence[int]):
    return ('m' + ','.join([hex(i) for i in ids])).encode()


def gdbReplyCurrentThreadId(threadId: int):
    return f'QC{threadId:x}'.encode()


def gdbReplyStopped(reason: int):
    """
    Generates a reply with a stop reason.
    https://sourceware.org/gdb/onlinedocs/gdb/Stop-Reply-Packets.html#Stop-Reply-Packets
    
    @param {number} reason The stop reason.
    """
    return f'S{reason:02x}'.encode()


def gdbReplyError(number: int):
    """
    Generates an Error reply with an Error No.
    @param {number} number The error number.
    """
    return f"E{number:02x}".encode()


def gdbReplyUnsupported():
    """
    Generates an unsupported reply.
    """
    return ''.encode()


def gdbReplyComputeChecksum(packet:str):
    checksum = 0
    for b in packet:
        checksum += ord(b)
        checksum &= 0xff
    return checksum


def gdbPacketReply(packet:Union[str, bytes]) -> bytes:
    if isinstance(packet, bytes):
        packet = packet.decode()
    checksum = gdbReplyComputeChecksum(packet)
    return f'${packet:s}#{checksum:02x}'.encode()


_GDB_PACKET_REPLY = re.compile('^\$([^#]*)#([0-9a-zA-Z]{2})')


def gdbParserReply(packet:str):
    m = _GDB_PACKET_REPLY.match(packet)
    if m is not None:
        packet = m[1]
        checksum = int(m[2], 16)
        expected = gdbReplyComputeChecksum(packet)
        if checksum == expected:
            return m, packet
        else:
            raise AssertionError(f"Invalid checksum of reply packet, {packet} {expected:02x}")
    return None  # packet is not reply packet
