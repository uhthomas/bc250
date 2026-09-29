#!/usr/bin/env python3
"""Exercise the volatile clock trial's guards and exact rollback offline."""

import importlib.util
from pathlib import Path
import struct
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
TRIAL = ROOT / 'trial_smu_clock_walker.py'
SOURCE = ROOT.parent.parent / 'output/video-decode-20260922/results/smu-sram.bin'
spec = importlib.util.spec_from_file_location('clock_trial', TRIAL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeSmu:
    def __init__(self, source, fail_at=None):
        self.ram = bytearray(source)
        self.hardware = 0
        self.fail_at = fail_at

    def alive(self):
        return True

    def _get_smu_version(self):
        return 1, 0x00580600

    def smu_read(self, address, words=1):
        return bytes(self.ram[address:address+words*4])

    def smu_write32(self, address, value):
        if address == self.fail_at:
            raise OSError('injected store failure')
        if address == module.CLOCK:
            self.hardware = value
        else:
            struct.pack_into('<I', self.ram, address, value)

    def sec_smn_read32(self, address):
        return 1, {module.CLOCK_SMN: self.hardware,
                   module.ENABLE_SMN: 0,
                   module.CONTROL_SMN: 2}[address]

    def send_message(self, queue, message, args, check_status):
        assert (queue, message, check_status) == (3, 0x1d, False)
        arg = args[0]
        if arg == module.ARG_1250:
            assert module.u32(self.ram, module.BASE+4) == 1
            for index in module.ZERO_INDICES:
                assert module.u32(self.ram, module.BASE+0x14c+(index-1)*12) == module.SENTINEL
            target = struct.unpack('<I', struct.pack('<f', 1250.0))[0]
            struct.pack_into('<I', self.ram, module.BASE+0x14c+15*12, target)
            for index in range(1, 21):
                applied = module.BASE+0x5c+(index-1)*12
                desired = module.BASE+0x14c+(index-1)*12
                struct.pack_into('<I', self.ram, applied,
                                 module.u32(self.ram, desired))
            struct.pack_into('<I', self.ram, module.BASE, 1)
            self.hardware = 16
            self.ram[module.SLOT_RECORD+2] = 16
            self.ram[module.SLOT_RECORD+6] = 16
        return 1, arg


class ClockTrialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()

    def build(self, fail_at=None):
        smu = FakeSmu(self.source, fail_at)
        events = []
        trial = module.Trial(smu, self.source,
                             lambda name, data: events.append((name, data)))
        trial.preflight()
        return smu, trial, events

    def test_handler_noop_keeps_state(self):
        with mock.patch.object(module, 'metrics', return_value={'vclk_mhz': 0,
                                                                  'dclk_mhz': 1111}):
            smu, trial, _ = self.build()
            before = bytes(smu.ram)
            trial.noop()
            trial.restore()
            self.assertEqual(bytes(smu.ram), before)

    def test_native_path_restores_table_record_and_hardware(self):
        with mock.patch.object(module, 'metrics', return_value={'vclk_mhz': 0,
                                                                  'dclk_mhz': 1111}):
            smu, trial, events = self.build()
            before = bytes(smu.ram)
            trial.native()
            self.assertEqual(smu.hardware, 16)
            trial.restore()
            self.assertEqual(smu.hardware, 0)
            self.assertEqual(bytes(smu.ram), before)
            self.assertIn('restored', [event for event, _ in events])

    def test_partial_patch_restores_without_sending_message(self):
        fail_at = module.BASE+0x14c+(6-1)*12
        with mock.patch.object(module, 'metrics', return_value={'vclk_mhz': 0,
                                                                  'dclk_mhz': 1111}):
            smu, trial, events = self.build(fail_at)
            before = bytes(smu.ram)
            with self.assertRaises(OSError):
                trial.native()
            trial.restore()
            self.assertEqual(bytes(smu.ram), before)
            self.assertNotIn('native_message_intent', [event for event, _ in events])


if __name__ == '__main__':
    unittest.main()
