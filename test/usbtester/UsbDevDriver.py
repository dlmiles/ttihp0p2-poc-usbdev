#
#
#
#  SpinalHDL UsbDevice bus transaction helper
#
#
# SPDX-FileCopyrightText: Copyright 2023 Darryl Miles
# SPDX-License-Identifier: Apache2.0
#
#
import os
from cocotb.triggers import ClockCycles

from usbtester import *
from .cocotbutil import *


# This is used as detection of gatelevel testing, with a flattened HDL,
#  we can only inspect the external module signals and disable internal signal inspection.
GL_TEST = ('GL_TEST' in os.environ and os.environ['GL_TEST'] != 'false') or ('GATES' in os.environ and os.environ['GATES'] != 'no')


class UsbDevDriver():
    # SIM_SUPPORTS_X is True for 4 state simulation supporting 'X' state
    def __init__(self, dut, bus, SIM_SUPPORTS_X: bool = True):
        assert(dut is not None)
        assert(bus is not None)
        self._dut = dut
        self._bus = bus
        self.SIM_SUPPORTS_X = SIM_SUPPORTS_X
        return None


    async def halt(self, endp: int, can_raise: bool = True) -> bool:
        assert endp & ~0xf == 0, f"endp is not valid {endp} for a 4-bit value"

        await self._bus.wb_write(REG_HALT, reg_halt(endp=endp, enable=True), regwr)
        DELAY = 16

        rv = False
        # wait for effective enable bit set ? after issuing enable=True
        for i in range(0, 256):
            data = await self._bus.wb_read(REG_HALT, regrd)
            if extract_bit(data, 5):	# effective_enable is bit5
                rv = True
                break
            await ClockCycles(dut.clk, DELAY)
        
        if not rv and can_raise:
            raise Exception("halt failed for endp={} after {} cycles".format(endp, i*DELAY))
        if i > 0:
            self._dut._log.info("halt(endp={}) took {} cycles".format(endp, i*DELAY))
        return rv


    async def unhalt(self, endp: int) -> bool:
        assert endp & ~0xf == 0, f"endp is not valid {endp} for a 4-bit value"

        await self._bus.wb_write(REG_HALT, reg_halt(endp=endp, enable=False), regwr)

        return True


    async def poweron(self) -> None:
        # FIXME if there was a global enable we'd do it here
        # This is an issue for ASIC ?
        await self._bus.wb_write(REG_CONFIG, 0x80000008, regwr)	# globalEnable=off interrupts=off

        await self.do_endp_shutdown_all()


    async def do_endp_shutdown_all(self) -> None:
        for endp in range(0, EP_COUNT):
            await self.halt(endp=endp)
            await self._bus.wb_write(REG_EP(endp), reg_endp(enable=False), regwr)	# disable
            await self.unhalt(endp=endp)


    async def do_config_global_enable(self, value: bool) -> None:
        if value:
            data = 0x40000000	# on
        else:
            data = 0x80000000	# off
        await self._bus.wb_write(REG_CONFIG, data, regwr)


    async def clear_pending(self, which: int = reg_interrupt(all=True)) -> None:
        await self._bus.wb_write(REG_INTERRUPT, which, regwr)


    async def dump_regs(self) -> None:
        # role call on registers
        data = await self._bus.wb_read(REG_FRAME, regrd)

        data = await self._bus.wb_read(REG_ADDRESS, regrd)

        data = await self._bus.wb_read(REG_INTERRUPT, regrd)

        data = await self._bus.wb_read(REG_HALT, regrd)

        data = await self._bus.wb_read(REG_CONFIG, regrd)

        data = await self._bus.wb_read(REG_INFO, regrd)


    async def dump_endp(self) -> None:
        for endp in range(0, EP_COUNT):
            data = await self._bus.wb_read(REG_EP(i), regrd)


    async def dump_setup(self, which: int = None) -> None:
        if which is None or which == 0:
            data = await self._bus.wb_read(REG_SETUP0, regrd)
        if which is None or which == 1:
            data = await self._bus.wb_read(REG_SETUP1, regrd)


    async def dump_membuf(self) -> None:
        await self._bus.wb_dump(REG_EP0, BUF_END)


    async def initialize_hardware(self) -> None:
        await self.dump_regs()

        await self.dump_membuf()

        await self._bus.wb_write(REG_ADDRESS, reg_address(address=0, enable=False, trigger=False), regwr)

        # ENDPOINT#0
        await self.halt(endp=0)	# HALT EP=0

        buf_ep0_desc = BUF_DESC0_20
        buf_ep0_length = 8 # 20 # FIXME this appears to be 12+8 (for 8)
        buf_ep0_eod = buf_ep0_desc + 12 + buf_ep0_length
        await self._bus.wb_write(buf_ep0_desc+0, desc0(code=DESC0_INPROGRESS), regwr)
        await self._bus.wb_write(buf_ep0_desc+4, desc1(length=buf_ep0_length), regwr)
        await self._bus.wb_write(buf_ep0_desc+8, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True), regwr)
        await self._bus.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(buf_ep0_desc), max_packet_size=buf_ep0_length), regwr) #

        await self.unhalt(endp=0)


        # ENDPOINT#1
        await self.halt(endp=1) # HALT EP=1

        buf_ep1_desc = BUF_DESC0_20 + 12 + 20  # 0x0040
        buf_ep1_length = 8
        buf_ep1_eod = buf_ep1_desc + 12 + buf_ep1_length
        if ADDRESS_LENGTH >= buf_ep1_eod:
            assert buf_ep1_eod <= BUF_END, f"EP1 configuration puts end-of-data beyond end-of-buffer ({buf_ep1_eod} > {BUF_END})"
            await self._bus.wb_write(buf_ep1_desc+0, desc0(code=DESC0_INPROGRESS), regwr)
            await self._bus.wb_write(buf_ep1_desc+4, desc1(length=buf_ep1_length), regwr)  # length=8
            await self._bus.wb_write(buf_ep1_desc+8, desc2(direction=DESC2_IN, interrupt=True), regwr)  # dir=IN, interrupt=true
            await self._bus.wb_write(REG_EP1, reg_endp(enable=True, head=addr_to_head(buf_ep1_desc), max_packet_size=buf_ep1_length), regwr) #

        await self.unhalt(endp=1)


        # ENDPOINT#2
        await self.halt(endp=2) # HALT EP=2

        # ENDPOINT#3
        await self.halt(endp=3) # HALT EP=3


        data = await self._bus.wb_read(REG_INTERRUPT, regrd)
        # FIXME commented this out for now, maybe it is not a real problem if you read the register before clearing it after powerup ?
        #   GL_TEST has surious x states for suspend/resume
        #   WB_READ  @ff08 = b00000000 0000xx00 00000000 00000000  NOT-RESOLVABLE
        #assert data == 0, f"REG_INTERRUPT expecting it to be clear already"
        # CLEAR INTERRUPTS (just before we enable them)
        await self._bus.wb_write(REG_INTERRUPT, reg_interrupt(all=True), regwr)


    async def do_config_interrupt_enable(self, value: bool) -> int:
        if value:
            data = reg_config(interrupt_enable_set=True)        # ENABLE GLOBAL INTERRUPTS
        else:
            data = reg_config(interrupt_enable_clear=True)
        await self._bus.wb_write(REG_CONFIG, data, regwr)
        return data


    async def do_config_pullup(self, value: bool) -> None:
        if not GL_TEST:
            # FIXME confirm this is a good power-on default electrically, it feels better to float until the driver actives
            # before pullup it set, check the output is as expected
            assert self._dut.dut.usb_dp_writeEnable,    f"self._dut.dut.usb_dp_writeEnable = {str(self._dut.dut.usb_dp_writeEnable.value)}"
            assert self._dut.dut.usb_dp_write == False, f"self._dut.dut.usb_dp_write = {str(self._dut.dut.usb_dp_write.value)}"

            assert self._dut.dut.usb_dm_writeEnable,    f"self._dut.dut.usb_dm_writeEnable = {str(self._dut.dut.usb_dm_writeEnable.value)}"
            assert self._dut.dut.usb_dm_write == False, f"self._dut.dut.usb_dm_write = {str(self._dut.dut.usb_dm_write.value)}"

        if value:
            data = reg_config(pullup_set=True)
        else:
            data = reg_config(pullup_clear=True)

        await self._bus.wb_write(REG_CONFIG, data, regwr) # FIXME is this FS=True?

        # HS=14 cycles @192MHz
        await ClockCycles(self._dut.clk, 28+4)	# need some ticks to observe update (clock-domain-crossing and back)

        if not GL_TEST:
            assert self._dut.dut.usb_dp_writeEnable == False,               f"self._dut.dut.usb_dp_writeEnable = {str(self._dut.dut.usb_dp_writeEnable.value)}"
            #if self.SIM_SUPPORTS_X:
            #    assert self._dut.dut.usb_dp_write.value.is_resolvable == False, f"self._dut.dut.usb_dp_write = {str(self._dut.dut.usb_dp_write.value)}"
            assert self._dut.dut.usb_dp_write.value.is_resolvable, f"self._dut.dut.usb_dp_write = {str(self._dut.dut.usb_dp_write.value)}"

            assert self._dut.dut.usb_dm_writeEnable == False, f"self._dut.dut.usb_dm_writeEnable = {str(self._dut.dut.usb_dm_writeEnable.value)}"
            #if self.SIM_SUPPORTS_X:
            #    assert self._dut.dut.usb_dm_write.value.is_resolvable == False,   f"self._dut.dut.usb_dm_write = {str(self._dut.dut.usb_dm_write.value)}"
            assert self._dut.dut.usb_dm_write.value.is_resolvable, f"self._dut.dut.usb_dm_write = {str(self._dut.dut.usb_dm_write.value)}"


    INTERRUPTS_BITID = 2

    def signal_interrupts(self) -> bool:
        return extract_bit(self._dut.uio_out, INTERRUPTS_BITID)

    # There is a better version for testing in test_usbdev.py maybe move it here?
    async def wait_for_interrupt(self, cycles: int = None) -> int:
        if cycles is None:
            cycles = 1000000

        bf = self.signal_interrupts()
        for i in range(0, cycles):
            if bf:
                break
            await ClockCycles(self._dut.clk, 1)
            bf = self.signal_interrupts()

        if not bf:
            return None

        value = await self._bus.wb_read(REG_INTERRUPT, regrd)
        s = dump_reg_interrupt(value)
        self._dut._log.info("{}".format(s))

        return value


__all__ = [
    'UsbDevDriver'
]
