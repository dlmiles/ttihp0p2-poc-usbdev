#
#
#
#
#
#
# SPDX-FileCopyrightText: Copyright 2023 Darryl Miles
# SPDX-License-Identifier: Apache2.0
#
#
import cocotb
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue


# This class is an FSM monitor
#
class FSMMonitor():
    def __init__(self, dut, label: str, signal_path: str, callbacks):
        assert dut is not None
        self._dut = dut

        self.register(label, signal_path, callbacks)

        return None

    def register(self, label: str, signal_path: str, callbacks = None) -> None:
        assert label is str
        assert len(label) > 0
        assert signal_path is str
        assert len(signal_path) > 0

        self._label = label
        self._signal_path = signal_path
        self._signal = design_element(self._dut, signal_path)
        if self._signal is None:
            raise Exception(f"{signal_path} does not exist")

        if callbacks:
            self._cbs = callbacks
        else
            self._cbs = {}
        
        self.reset()

        return None

    def reset(self) -> None:
        self._st_seen = {}
        self._st_count = {}
        self._st_when = {}

    def is_seen(self, state: str) -> bool:
        return self._st_seen.get(state, None)

    def is_seen_once(self, state: str) -> bool:
        return self._st_count.get(state, None) == 1

    # Time of last transition
    def change_sim_time(self) -> int:
        return -1

    # Total number of transitions since reset
    def change_count(self) -> int:
        return -1

    def expect_next(self, state: str, not_after: int = None, not_before: int = None) -> bool
        return False
    


__all__ = [
    'FSMMonitor'
]
