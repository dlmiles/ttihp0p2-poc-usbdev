#
#
#  TODO there are 2 layers to this one class, split them
#	low level bit banger
#	higher level USB packet/structure
#
#
# SPDX-FileCopyrightText: Copyright 2023 Darryl Miles
# SPDX-License-Identifier: Apache2.0
#
#

from cocotb.triggers import ClockCycles

from .Payload import *



# NRZI - 0 = transition
# NRZI - 1 = no transition
# NRZI - stuff 0 after 6 111111s
class UsbBitbang():
    # This class managed bit stream level matters concerning USB
    # It manages low-speed/high-speed difference, NRZI encoding, bit stuffing

    DP = 0x01
    DM = 0x02
    MASK = DP|DM

    SE0 = 0x00		# !D+ bit0 !D- bit1 = SE0
    LS_J = DM		# !D+ bit0  D- bit1 = J   LS  IDLE
    FS_J = DP		#  D+ bit0 !D- bit1 = J   FS  IDLE
    LS_K = DP		#  D+ bit0 !D- bit1 = K   LS
    FS_K = DM		# !D+ bit0  D- bit1 = K   FS

    def __init__(self, dut, TICKS_PER_BIT: int, LOW_SPEED: bool = False):
        self._dut = dut
        assert(TICKS_PER_BIT >= 0 and type(TICKS_PER_BIT) is int)
        self._TICKS_PER_BIT = TICKS_PER_BIT
        self._LOW_SPEED = LOW_SPEED
        self.reset()

        self._crc5 = 0
        self._crc16 = 0

        self._addr = 0
        self._endp = 0
        self._data1 = False

        return None

    def reset(self, last: str = None) -> None:
        self._nrzi_one_count = 0
        self._nrzi_last = last

    async def nrzi(self, whoami: str):
        assert(whoami == 'J' or whoami == 'K')
        if(self._nrzi_last != whoami):
            self._nrzi_one_count = 0
        else:
            self._nrzi_one_count += 1
        #elif not self._LOW_SPEED and whoami == 'J':
        #    self._nrzi_one_count += 1 # only stuff 1's
        #elif self._LOW_SPEED and whoami == 'K':
        #    self._nrzi_one_count += 1 # only stuff 1's
        self._nrzi_last = whoami
        if self._nrzi_one_count >= 6:	# 0 to 5 provides the 6
            print("nrzi_bitstuff_insert_transition whoami={} sending !{}".format(whoami, whoami))
            if whoami == 'J':
                await self.send_K()
            else:
                await self.send_J()
            # This is reentrant, so it ends up calling itself again,
            #  which will self._nrzi_one_count = 0
            #  the inserted bit doesn't count towards the next total
            assert self._nrzi_one_count == 0

    async def update(self, or_mask: int, ticks: int = None) -> int:
        v = self._dut.uio_in.value
        nv = (v & ~self.MASK) | or_mask
        self._dut.uio_in.value = nv

        if ticks is None:
            ticks = self._TICKS_PER_BIT
        if ticks > 0:
            await ClockCycles(self._dut.clk, ticks)

        return nv

    async def send_SE0(self) -> int:
        return await self.update(self.SE0)

    async def send_J(self, only_when_k: bool = False) -> bool:
        if only_when_k:
            if self._nrzi_last == 'J':
                return False
        if self._LOW_SPEED:
            await self.update(self.LS_J)
        else:
            await self.update(self.FS_J)
        await self.nrzi('J')
        return True

    async def send_K(self) -> None:
        if self._LOW_SPEED:
            await self.update(self.LS_K)
        else:
            await self.update(self.FS_K)
        await self.nrzi('K')

    async def send_0(self) -> None:
        if self._nrzi_last == 'K':
            await self.send_J()
        elif self._nrzi_last == 'J':
            await self.send_K()
        else:
            assert False, f"use send_idle() first"

    async def send_1(self) -> None:
        if self._nrzi_last == 'K':
            await self.send_K()
        elif self._nrzi_last == 'J':
            await self.send_J()
        else:
            assert False, f"use send_idle() first"

    # Used to generate stuffingError by maintaining line state
    async def send_same(self, count: int = 1) -> None:
        nv = self._dut.uio_in.value & self.MASK	# current state
        for i in range(count):
            await self.update(nv)
            # no call to self.nrzi() to update bitstuffer

    async def send_bf(self, bit: bool) -> None:
        if bit:
            await self.send_1()
        else:
            await self.send_0()

    async def send_idle(self, ticks: int = None) -> None:
        if self._LOW_SPEED:
            await self.update(self.LS_J, ticks)	# aka IDLE
        else:
            await self.update(self.FS_J, ticks)	# aka IDLE
        self.reset('J')

    # Use ticks=0 to set_idle(), does not insert wait itself
    async def set_idle(self) -> None:
        await self.send_idle(0)

    async def send_data(self, data: int, bits: int = 32, msg: str = None) -> None:
        assert(bits >= 0 and bits <= 32)
        msg = '[' + msg + ']' if(msg) else ''
        print("send_data(data=0x{:08x} {:11d}, bits={}) {}".format(data, data, bits, msg))
        for i in range(0, bits):	# LSB first
            bv = data & (1 << i)
            bf = bv != 0
            await self.send_bf(bf)
            self.crc5_add(bf)
            self.crc16_add(bf)

    OUT		= 0x1
    ACK		= 0x2
    DATA0	= 0x3
    PING	= 0x4
    SOF		= 0x5
    NYET	= 0x6
    DATA2	= 0x7
    IN		= 0x9
    NAK		= 0xa
    DATA1	= 0xb
    PRE		= 0xc
    SETUP	= 0xd
    STALL	= 0xe
    MDATA	= 0xf

    SYNC = 0x80

    # FIXME move these out of this class, into data layer API class
    # This class manages low level packet structure
    # SYNC+EOF and CRC5/CRC16 generation
    async def send_sync(self) -> None:
        # Can't use send_data() here, due to bit stuffing
        #  that is the whole point SYNC is not subject to bit stuffing
        self.reset(self._nrzi_last)	# reset bitstuffer, but keep state
        msg = "SYNC"
        # For testing purposes maybe we should insert a J state to achieve IDLE state
        if await self.send_J(only_when_k=True):
            msg = "inserted extra J state before SYNC"
        print("send_sync(0x{:02x}) [{}]".format(self.SYNC, msg))
        await self.send_0()	# LSB0
        await self.send_0()
        await self.send_0()
        await self.send_0()
        await self.send_0()
        await self.send_0()
        await self.send_0()
        await self.send_1()	# MSB7 for 0x80

    async def send_eop(self) -> None:
        print("send_eop() = [SE0, SE0, J]")
        await self.send_SE0()
        await self.send_SE0()
        await self.send_J()

    def crc5_reset(self) -> None:
        self._crc5 = 0x1f

    def crc5_add(self, bit: bool) -> None:
        crc5 = self._crc5
        # 1bit input, right shifting
        lsb = (crc5 & 1) != 0
        crc5 = crc5 >> 1
        if bit != lsb:
            crc5 ^= 0x14	# b10100
        self._crc5 = crc5

    def crc5_valid(self) -> bool:
        return ~self._crc5 == 0x0c


    def crc16_reset(self) -> None:
        self._crc16 = 0xffff

    def crc16_add(self, bit: bool) -> None:
        crc16 = self._crc16
        # 1bit input, right shifting
        lsb = (crc16 & 1) != 0
        crc16 = crc16 >> 1
        if bit != lsb:
            crc16 ^= 0xa001	# b10100000 00000001
        self._crc16 = crc16

    def crc16_valid(self) -> bool:
        return ~self._crc16 == 0x800d


    async def send_crc5(self) -> int:
        crc5_inverted = ~self._crc5 & 0x1f
        await self.send_data(crc5_inverted, 5, "CRC5")
        return self._crc5

    async def send_crc16(self) -> int:
        crc16_inverted = ~self._crc16 & 0xffff
        await self.send_data(crc16_inverted, 16, "CRC16")
        return self._crc16

    def validate_pid(self, pid: int) -> None:
        assert pid & ~0xff == 0, f"pid = {pid} is out of 8-bit range"
        assert (~pid >> 4 & 0xf) == pid & 0xf, f"pid = {pid} is out of 8-bit range"

    def validate_token(self, token: int) -> None:
        assert token & ~0xf == 0, f"token = {token} is out of 4-bit range"

    def validate_frame(self, frame: int) -> None:
        assert frame & ~0x7ff == 0, f"frame = {frame} is out of 11-bit range"

    def validate_addr(self, addr: int) -> None:
        assert addr & ~0x7f == 0, f"addr = {addr} is out of 7-bit range"

    def validate_endp(self, endp: int) -> None:
        assert endp & ~0xf == 0, f"endp = {endp} is out of 4-bit range"

    def validate_addr_endp(self, addr: int, endp: int) -> None:
        self.validate_addr(addr)
        self.validate_endp(endp)

    def resolve_addr(self, addr: int = None) -> int:
        if addr is None:
            print("resolve_addr({}) = {}".format(addr, self._addr))
            return self._addr
        self.validate_addr(addr)
        return addr

    def resolve_endp(self, endp: int = None) -> int:
        if endp is None:
            print("resolve_endp({}) = {}".format(endp, self._endp))
            return self._endp
        self.validate_endp(endp)
        return endp

    def token_to_string(self, token_or_pid: int) -> str:
        value = token_or_pid & 0xf
        if value == self.OUT:
            desc = "OUT"
        elif value == self.ACK:
            desc = "ACK"
        elif value == self.DATA0:
            desc = "DATA0"
        elif value == self.PING:
            desc = "PING"
        elif value == self.SOF:
            desc = "SOF"
        elif value == self.NYET:
            desc = "NYET"
        elif value == self.DATA2:
            desc = "DATA2"
        elif value == self.IN:
            desc = "IN"
        elif value == self.NAK:
            desc = "NAK"
        elif value == self.DATA1:
            desc = "DATA1"
        elif value == self.PRE:
            desc = "PRE"
        elif value == self.SETUP:
            desc = "SETUP"
        elif value == self.STALL:
            desc = "STALL"
        elif value == self.MDATA:
            desc = "MDATA"
        else:
            desc = ""
        return "{}[0x{:02x}]".format(desc, value)

    # validate is to let us generate invalid data
    async def send_pid(self, pid: int = None, token: int = None, allow_invalid: bool = False) -> None:
        if pid is None:
            if not allow_invalid:
                self.validate_token(token)
            pid = ((~token << 4) & 0xf0) | token
            #print("send_pid(token=0x{:x}) computed PID = 0x{:02x} d{} from token".format(token, pid, pid))

        if not allow_invalid:
            self.validate_pid(pid)
        await self.send_data(pid, 8, "PID={} 0x{:x} d{}".format(self.token_to_string(pid), pid, pid))

        # Should be equivalent to
        #await self.send_data(token, 4)
        #await self.send_data(~token, 4)

    async def send_crc5_payload(self, token: int, data: int, crc5: int = None) -> None:
        self.validate_token(token)
        assert data & ~0x7ff == 0, f"data = {data:x} is out of 11-bit range"

        await self.send_sync()
        await self.send_pid(token=token)
        self.crc5_reset()
        await self.send_data(data, 11, "DATA11")
        if crc5 is None:
            await self.send_crc5()
        else:
            crc5_inverted = ~self._crc5 & 0x1f
            if crc5 != crc5_inverted:
                self._dut._log.warning(f"crc5 mismatch (provided) {crc5:02x} != {crc5_inverted:02x} (computed) {self._crc5:02x} (actual)")
            assert crc5 & ~0x1f == 0, f"crc5 = {crc5:02x} is out of 5-bit range"
            await self.send_data(crc5, 5, "CRC5")	# we send the one provided in argument
        await self.send_eop()

    async def send_token(self, token: int, addr: int = None, endp: int = None, crc5: int = None) -> None:
        addr = self.resolve_addr(addr)
        endp = self.resolve_endp(endp)
        data = endp << 7 | addr
        await self.send_crc5_payload(token, data, crc5)

    async def send_handshake(self, token: int) -> None:
        self.validate_token(token)
        assert token == self.ACK or token == self.NAK or token == self.STALL, f"send_handshake(token={token}) is not ACK, NAK or STALL type"
        await self.send_sync()
        await self.send_pid(token=token)
        await self.send_eop()

    async def send_sof(self, frame: int, crc5: int = None) -> None:
        self.validate_frame(frame)
        await self.send_crc5_payload(self.SOF, frame, crc5)

    async def send_crc16_payload(self, token: int, payload: Payload, crc16: int = None) -> None:
        self.validate_token(token)
        await self.send_sync()
        await self.send_pid(token=token)
        self.crc16_reset()
        await self.send_payload(payload)
        if crc16 is None:
            await self.send_crc16()
        else:
            crc16_inverted = ~self._crc16 & 0xffff
            if crc16 != crc16_inverted:
                self._dut._log.warning(f"crc16 mismatch (provided) {crc16:04x} != {crc16_inverted:04x} (computed) {self._crc16:04x} (actual)")
            assert crc16 & ~0xffff == 0, f"crc16 = {crc16:04x} is out of 16-bit range"
            await self.send_data(crc16, 16, "CRC16")	# we send the one provided in argument
        await self.send_eop()

    async def send_payload(self, payload: Payload) -> int:
        for v in payload:
            await self.send_data(v, 8)
        return len(payload)

    async def send_out_data0(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        await self.send_token(self.OUT, addr, endp)
        await self.send_crc16_payload(self.DATA0, payload, crc16)
        self._data1 = True

    async def send_out_data1(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        await self.send_token(self.OUT, addr, endp)
        await self.send_crc16_payload(self.DATA1, payload, crc16)
        self._data1 = False

    async def send_out_data(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        if self._data1:
            await self.send_out_data1(payload, addr, endp, crc16)
        else:
            await self.send_out_data0(payload, addr, endp, crc16)

    async def send_in_data0(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        await self.send_token(self.IN, addr, endp)
        await self.send_crc16_payload(self.DATA0, payload, crc16)

    async def send_in_data1(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        await self.send_token(self.IN, addr, endp)
        await self.send_crc16_payload(self.DATA1, payload, crc16)

    async def send_in_data(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        if self._data1:
            await self.send_in_data1(payload, addr, endp, crc16)
        else:
            await self.send_in_data0(payload, addr, endp, crc16)


__all__ = [
    'UsbBitbang'
]
