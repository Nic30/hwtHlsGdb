from math import inf
from typing import Union, Optional, Dict, Literal

from hwtHlsGdb.gdbRemoteMessages import GdbBreakPointType, \
    gdbReplyUnsupported

class CycleLimitReached:
    pass

class GdbCmdHandler():
    """
    A handler handles the incoming GDB commands via GDBServerStub.
    This class replies to all messages as "gdbReplyUnsupported".
    One must extend this class and implement the handling functions to use it.
    """

    def __init__(self):
        self.cycleLimit: Union[int, Literal[inf]] = 0

    def runCurrentInstr(self) -> Union[int, CycleLimitReached, None]:
        """
        :returns: optional address of breakpoint if any breakpoint meet
        """
        raise NotImplementedError()

    def handleHaltReason(self):
        """
        Handles ? command that queries the reason of the half.
        :returns: the reason of the halt. e.g. "S05" for SIG_TRAP
        """
        return gdbReplyUnsupported()

    def handleStep(self, address: Union[int, None]):
        """
        Handles step execution. It executes one instruction and stops.
        :param address: The address at which the handler executes.
           If undefined, the current address should be used.
        """
        return gdbReplyUnsupported()

    def handleContinue(self, address: Union[int, None]):
        """
        Handles continue execution. It executes until the next break point.
        :param address: The address at which the handler executes.
           If undefined, the current address should be used.
        """
        return gdbReplyUnsupported()

    def handleReadMemory(self, address: int, length: int):
        """
        Handles read of the memory content.
        :param address: The address to start reading.
        :param length: The number of units (usually bytes) to be read.
        """
        return gdbReplyUnsupported()

    def handleWriteMemory(self, address: int, values: bytes):
        """
        Handles write to the memory.
        @param address: The address to start writing.
        @param values: The values to be written.
        """
        return gdbReplyUnsupported()

    def handleReadRegisters(self, threadId: Union[int, None]):
        """
        Handles read of all register values.
        :param threadId: The target thread's ID.
        """
        return gdbReplyUnsupported()

    def handleWriteRegisters(self, bytes_: bytes):
        """
        Handles write to all register values.
        """
        return gdbReplyUnsupported()

    def handleReadRegister(self, index: Optional[int]):
        """
        Handles read the value of the register at the index.
        :param index: The index of the target register.
        """
        return gdbReplyUnsupported()

    def handleQSupported(self, features: Dict[str, bool]):
        """
        Handles querying of supported features. Tell the remote stub about features supported by GDB, and query the stub for features it supports
        :param features: The features that GDB supports.
        """
        return gdbReplyUnsupported()

    def handleThreadInfo(self):
        """
        Handles querying of thread info. Returns a list of Thread IDs.
        """
        return gdbReplyUnsupported()

    def handleCurrentThread(self):
        """
        Handles querying of the current Thread ID.
        """
        return gdbReplyUnsupported()

    def handleRegisterInfo(self, index: int):
        """
        Handles querying of information of the register at the index.
        :param index: The register's index
        """
        return gdbReplyUnsupported()

    def handleHostInfo(self):
        """
        Handles querying of the GDB host information.
        e.g.: 'triple:6d697073656c2d756e6b6e6f776e2d6c696e75782d676e75;endian:little;ptrsize:4'
        """
        return gdbReplyUnsupported()

    def handleMemoryRegionInfo(self, address: int):
        """
        Gets information about the address range that contains address.
        e.g. 'start:2;size:fffffffe;permissions:rwx;';
        """
        return gdbReplyUnsupported()

    def handleSelectExecutionThread(self, threadId: int):
        """
        Selects the thread for step and continue execution.
        :param threadId: The selected Thread ID
        """
        return gdbReplyUnsupported()

    def handleSelectRegisterThread(self, threadId: int):
        """
        Selects the thread for read/write registers.
        :param threadId: The selected Thread ID
        """
        return gdbReplyUnsupported()

    def handleSelectMemoryThread(self, threadId: int):
        """
        Selects the thread for read/write memory.
        :param threadId: The selected Thread ID
        """
        return gdbReplyUnsupported()

    def handleAddBreakpoint(self, btype:GdbBreakPointType, address: int, kind: int):
        """
        Handles addding a breakpoint.
        :param address: The address of the breakpoint
        :param kind: Target specific. Usually the breakpoint size in bytes
        """
        return gdbReplyUnsupported()

    def handleRemoveBreakpoint(self, btype: GdbBreakPointType, address: int, kind: int):
        """
        Handles removing a breakpoint.
        :param address: The address of the breakpoint
        :param kind: Target specific. Usually the breakpoint size in bytes
        """
        return gdbReplyUnsupported()
