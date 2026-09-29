#!/usr/bin/env python3
"""Check that the VCN request is staged before the periodic SMU trigger."""

import importlib.util
from pathlib import Path
import struct
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent.parent / 'output/video-decode-20260922/results/smu-sram.bin'
TRIAL_SCRIPT = ROOT / 'trial_smu_clock_walker.py'
CALLBACK_SCRIPT = ROOT / 'trial_smu_clock_callback_once.py'
spec = importlib.util.spec_from_file_location('trial_smu_clock_walker', TRIAL_SCRIPT)
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)
import sys
sys.modules['trial_smu_clock_walker'] = clock
spec = importlib.util.spec_from_file_location('clock_callback_once', CALLBACK_SCRIPT)
callback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(callback)


class SchedulerFake:
    def __init__(self, image):
        self.ram = bytearray(image)
        self.hardware = 0
        self.events = []

    def alive(self):
        return True

    def _get_smu_version(self):
        return 1, 0x00580600

    def smu_read(self, address, words=1):
        return bytes(self.ram[address:address+words*4])

    def smu_write32(self, address, value):
        struct.pack_into('<I', self.ram, address, value)
        if address == clock.BASE+4 and value == 1:
            self.events.append('generation_trigger')
            requested = clock.u32(self.ram, clock.BASE+0x14c+15*12)
            expected = struct.unpack('<I', struct.pack('<f', 1250.0))[0]
            assert requested == expected
            for index in clock.ZERO_INDICES:
                assert clock.u32(self.ram,
                                 clock.BASE+0x14c+(index-1)*12) == clock.SENTINEL
            for index in range(1, 21):
                desired = clock.u32(self.ram,
                                    clock.BASE+0x14c+(index-1)*12)
                struct.pack_into('<I', self.ram,
                                 clock.BASE+0x5c+(index-1)*12, desired)
            struct.pack_into('<I', self.ram, clock.BASE, 1)
            self.ram[clock.SLOT_RECORD+2] = 16
            self.ram[clock.SLOT_RECORD+6] = 16
            self.hardware = 16

    def sec_smn_read32(self, address):
        return 1, {clock.CLOCK_SMN: self.hardware,
                   clock.ENABLE_SMN: 0,
                   clock.CONTROL_SMN: 2}[address]

    def send_message(self, queue, message, args, check_status):
        assert (queue, message, check_status) == (3, 0x1d, False)
        assert args == [clock.ARG_1250]
        assert clock.u32(self.ram, clock.BASE) == 0
        assert clock.u32(self.ram, clock.BASE+4) == 0
        self.events.append('target_message')
        struct.pack_into('<I', self.ram, clock.BASE+0x14c+15*12,
                         struct.unpack('<I', struct.pack('<f', 1250.0))[0])
        return 1, clock.ARG_1250


class CallbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = SOURCE.read_bytes()

    def test_requested_before_scheduler_trigger(self):
        fake = SchedulerFake(self.image)
        events = []
        with mock.patch.object(clock, 'metrics',
                               side_effect=lambda: {
                                   'vclk_mhz': 1250 if fake.hardware else 0,
                                   'dclk_mhz': 1111}):
            trial = clock.Trial(fake, self.image,
                                lambda name, data: events.append((name, data)))
            trial.preflight()
            result = callback.callback_once(
                trial, lambda name, data: events.append((name, data)))
        self.assertEqual(fake.events, ['target_message', 'generation_trigger'])
        self.assertEqual(result['generation'], [1, 1])
        self.assertEqual(result['hardware_code'], 16)
        self.assertEqual(result['metrics']['vclk_mhz'], 1250)
        self.assertIn('callback_completed', [name for name, _ in events])

    def test_unexpected_callback_refuses_before_writes(self):
        fake = SchedulerFake(self.image)
        struct.pack_into('<I', fake.ram, 0xc760, 0)
        with mock.patch.object(clock, 'metrics',
                               return_value={'vclk_mhz': 0, 'dclk_mhz': 1111}):
            trial = clock.Trial(fake, self.image, lambda name, data: None)
            trial.preflight()
            with self.assertRaisesRegex(RuntimeError, 'callback differs'):
                callback.callback_once(trial, lambda name, data: None)
        self.assertEqual(fake.events, [])

    def test_diagnostic_boot_without_drm_metrics(self):
        fake = SchedulerFake(self.image)
        trial = clock.Trial(fake, self.image, lambda name, data: None,
                            require_gpu_metrics=False)
        trial.preflight()
        result = callback.callback_once(trial, lambda name, data: None)
        self.assertEqual(fake.events, ['target_message', 'generation_trigger'])
        self.assertEqual(result['hardware_code'], 16)
        self.assertIsNone(result['metrics'])


if __name__ == '__main__':
    unittest.main()
