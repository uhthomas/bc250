import os
from pathlib import Path
import unittest
from router_model import Bus, assemble, encode, NativePolicy, BoundaryMonitor


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe = os.environ.get('PIOASM')
        if not exe:
            raise unittest.SkipTest('set PIOASM to test assembled router')
        cls.p = assemble(exe)
        cls.policy = NativePolicy()

    @classmethod
    def tearDownClass(cls):
        cls.policy.close()

    def make(self, rows, **kwargs):
        bus = Bus(self.p, rows, lambda cmd: (cmd * 0x1234567) & 0xffffffff, **kwargs)
        bus.tick(4, 600)
        return bus

    def test_script_patch_pass_and_eof_passthrough(self):
        rows = [(0x039db140, True, 0xa501fe80), (0x039db144, True, 0xffffffff),
                (0x039db140, False, 0), (0x038f0800, True, 0),
                (0x03984f00, False, 0)]
        # Supported digital-model envelope: 150 MHz PIO, SPI through 5 MHz.
        for half in (300, 75, 30, 15):
            for sync in (2, 3):
                for feed in (12, 64, 128):
                    with self.subTest(half=half, sync=sync, feed=feed):
                        bus = self.make(rows, sync_cycles=sync, feed_cycles=feed)
                        for command, patch, value in rows:
                            got = bus.data(bus.transaction(command, half))
                            self.assertEqual(got, value if patch else bus.rom_word(command))
                        got = bus.data(bus.transaction(0x030abc00, half))
                        self.assertEqual(got, bus.rom_word(0x030abc00))
                        self.assertFalse(bus.contentions)
                        self.assertNotIn(0, bus.irqs)
                        self.assertEqual(bus.state['oe'], 0)
                        self.assertEqual(bus.counter.rx, [64] * (len(rows) + 1))

    def test_short_cs_setup_at_modeled_limit(self):
        rows = [(0x039db140, True, 0xa501fe80), (0x039db144, False, 0)]
        for sync in (2, 3):
            bus = self.make(rows, sync_cycles=sync)
            for command, patch, word in rows:
                got = bus.data(bus.transaction(command, half_cycles=15, setup_cycles=0))
                self.assertEqual(got, word if patch else bus.rom_word(command))
            self.assertFalse(bus.contentions)

    def test_unexpected_command_latches_fault_before_patch(self):
        for wrong in (0x039db144, 0x039db141, 0x029db140, 0x0b9db140):
            with self.subTest(command=hex(wrong)):
                bus = self.make([(0x039db140, True, 0xdeadbeef)])
                samples = bus.transaction(wrong)
                self.assertIn(0, bus.irqs)
                if wrong >> 24 == 3:
                    self.assertEqual(bus.data(samples), bus.rom_word(wrong))
                else:
                    self.assertTrue(all(drivers == 0 for drivers, _ in samples[32:]))
                self.assertEqual(bus.data(bus.transaction(0x039db140)), bus.rom_word(0x039db140))
                self.assertFalse(bus.contentions)

    def test_copy_then_check_same_address(self):
        command = 0x039db140
        bus = self.make([(command, True, 0x12345678), (command, False, 0)])
        self.assertEqual(bus.data(bus.transaction(command)), 0x12345678)
        self.assertEqual(bus.data(bus.transaction(command)), bus.rom_word(command))
        self.assertEqual(bus.data(bus.transaction(command)), bus.rom_word(command))

    def test_cs_abort_releases_outputs_at_every_bit(self):
        for clocks in range(1, 64):
            bus = self.make([(0x039db140, True, 0x55aa55aa)])
            bus.transaction(0x039db140, clocks=clocks)
            self.assertEqual(bus.state['oe'], 0, clocks)
            self.assertEqual(bus.state['flash_cs'], 1, clocks)
            self.assertFalse(bus.contentions)
            self.assertEqual(bus.counter.rx, [clocks])
            # Rearming after a short transfer is deliberately not modeled as
            # valid. Firmware must latch a fault before the next transaction.

    def test_unsupported_speed_is_not_mistaken_for_success(self):
        bus = self.make([(0x039db140, True, 0xffffffff)])
        samples = bus.transaction(0x039db140, half_cycles=3)
        with self.assertRaises(AssertionError):
            self.assertEqual(bus.data(samples), 0xffffffff)

    def test_overlong_transaction_is_detected(self):
        bus = self.make([(0x039db140, True, 0x55aa55aa)])
        bus.transaction(0x039db140, clocks=80)
        self.assertEqual(bus.counter.rx, [80])
        self.assertEqual(bus.state['oe'], 0)

    def test_retained_signed_payload_every_changed_word(self):
        path = os.environ.get('BC250_OVERLAY_MANIFEST')
        if not path:
            self.skipTest('set BC250_OVERLAY_MANIFEST to replay the retained signed pair')
        from prepare_router_profile import prepare, load_pair
        plan = prepare(Path(path))
        _, clean, _ = load_pair(Path(path))
        rows = [(r['command'], r['patch'], r['word']) for r in plan['rows']]
        def original(command):
            addr = command & 0xffffff
            return int.from_bytes(clean[addr:addr+4], 'big')
        bus = Bus(self.p, rows, original, sync_cycles=3, feed_cycles=128)
        bus.tick(4, 600)
        for command, patch, word in rows:
            self.assertEqual(bus.data(bus.transaction(command)), word if patch else original(command))
        self.assertFalse(bus.contentions)
        self.assertNotIn(0, bus.irqs)
        self.assertEqual(bus.counter.rx, [64] * len(rows))

    def monitored(self, latency=32):
        rows = [(0x03000100, False, 0), (0x03000104, False, 0),
                (0x039db140, True, 0xa501fe80), (0x039db140, False, 0)]
        monitor = BoundaryMonitor(self.policy, rows, latency)
        return rows, monitor, self.make(rows, monitor=monitor)

    def test_search_preamble_then_strict_patch_sequence(self):
        for latency in (8, 32, 80):
            with self.subTest(monitor_latency=latency):
                rows, monitor, bus = self.monitored(latency)
                for command, clocks in ((0x9f000000,8), (0x039da000,64),
                                        (0x03000100,24), (0x039db140,64)):
                    bus.transaction(command,clocks=clocks)
                    self.assertEqual(monitor.mode,'seeking')
                self.assertEqual(monitor.skipped,4)
                self.assertEqual(bus.pico_drive_cycles,0)
                for command, patch, word in rows:
                    self.assertEqual(bus.data(bus.transaction(command)),word if patch else bus.rom_word(command))
                self.assertEqual(monitor.mode,'complete')
                self.assertEqual(monitor.boundaries,len(rows))
                self.assertFalse(bus.contentions)

    def test_anchor_match_with_bad_length_is_terminal(self):
        for clocks in (32,40,63,65,80):
            _, monitor, bus = self.monitored()
            bus.transaction(0x03000100,clocks=clocks)
            self.assertEqual(monitor.mode,'length_fault')
            self.assertEqual(bus.pico_drive_cycles,0)

    def test_wrong_guard_after_anchor_never_patches(self):
        _, monitor, bus = self.monitored()
        bus.transaction(0x03000100)
        bus.transaction(0x03000108)
        self.assertEqual(monitor.mode,'address_fault')
        bus.transaction(0x039db140)
        self.assertEqual(bus.pico_drive_cycles,0)

    def test_short_patch_then_next_read_stays_with_original(self):
        for clocks in range(1,64):
            rows,monitor,bus=self.monitored()
            for command,_,_ in rows[:2]: bus.transaction(command)
            bus.transaction(0x039db140,clocks=clocks)
            self.assertEqual(monitor.mode,'length_fault',clocks)
            self.assertEqual(bus.data(bus.transaction(0x039db140)),bus.rom_word(0x039db140))
            self.assertFalse(bus.contentions)

    def test_insufficient_gap_is_rejected_by_monitor(self):
        _,monitor,bus=self.monitored(latency=80)
        bus.transaction(0x9f000000,clocks=8,high_cycles=10)
        bus.transaction(0x03000100)
        self.assertEqual(monitor.mode,'boundary_fault')
        self.assertEqual(bus.pico_drive_cycles,0)

    def test_native_stream_mixed_pass_and_patch_runs(self):
        from prepare_router_profile import compress
        rows=[dict(command=0x03001000+4*i,patch=i%5==0,word=(i*0x1234567)&0xffffffff)
              for i in range(100)]
        rows+=list(reversed(rows))
        runs,payload=compress(rows)
        expected=encode([(r['command'],r['patch'],r['word']) for r in rows],self.p[0]['publicLabels'])
        self.assertEqual(self.policy.expand(runs,payload,self.p[0]['publicLabels']),expected)

    def test_complete_firmware_sequences_fit_compressed_sram(self):
        path=os.environ.get('BC250_OVERLAY_MANIFEST')
        if not path:
            self.skipTest('set BC250_OVERLAY_MANIFEST for full-object stress')
        from prepare_router_profile import prepare,compress
        plan=prepare(Path(path),full_objects=True)
        self.assertGreater(plan['expanded_bytes'],384*1024)
        self.assertLess(plan['compressed_bytes'],384*1024)
        self.assertEqual(len(plan['rows']),97354)
        runs,payload=compress(plan['rows'])
        expected=encode([(r['command'],r['patch'],r['word']) for r in plan['rows']],self.p[0]['publicLabels'])
        self.assertEqual(self.policy.expand(runs,payload,self.p[0]['publicLabels']),expected)


if __name__ == '__main__':
    unittest.main()
