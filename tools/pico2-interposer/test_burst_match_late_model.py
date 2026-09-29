#!/usr/bin/env python3
"""Replay direct-address 64-byte handoff on physical and synthetic SPI edges."""

import collections
import unittest

from fast_select_model import assemble
from router_model import SM
from test_burst_select_od_model import (CAPTURE_PATH, CAPTURE_SHA256,
                                         PIOASM, ROM_PATH, snapshot_samples,
                                         synthetic_samples)
import hashlib


def replay(program, frames, target, reply, *, sync_cycles=2, phase_cycles=0):
    words = [int.from_bytes(reply[i:i+4], 'big') for i in range(0, 64, 4)]
    fifo = collections.deque([target >> 1])
    sm = SM(program, fifo, jmp_pin=4, out_autopull=True, out_threshold=32)
    pipe = collections.deque([4] * sync_cycles)
    irqs = set()
    state = dict(flash_cs=1, oe=0, data=0)
    for _ in range(20):
        state.update(sm.step(4, irqs))
    assert sm.x == target >> 1 and not fifo
    fifo.append(words[0])
    dma = collections.deque(words[1:])
    for _ in range(20):
        if dma and len(fifo) < 8:
            fifo.append(dma.popleft())
        state.update(sm.step(4, irqs))
    rises = [[] for _ in frames]
    transaction = -1
    previous_cs, previous_clk = 1, 0
    release_cycle = handoff_release = drive_cycle = first_data_rise = None
    cycle = 0
    for sample_index, sample in enumerate([0x21] * 20 +
                                          [x for frame in frames for x in frame]):
        cs, clk = sample & 1, (sample >> 1) & 1
        if previous_cs and not cs:
            transaction += 1
        if not cs and clk and not previous_clk:
            if len(rises[transaction]) == 32 and state['oe'] and first_data_rise is None:
                first_data_rise = cycle
            rises[transaction].append((state['flash_cs'], state['oe'], state['data']))
        previous_cs, previous_clk = cs, clk
        steps = 2 - (sample_index == 0 and phase_cycles == 1)
        for _ in range(steps):
            if dma and len(fifo) < 8:
                fifo.append(dma.popleft())
            old = state.copy()
            pipe.append((sample & 7) << 2)
            state.update(sm.step(pipe.popleft(), irqs))
            if transaction >= 0:
                if old['flash_cs'] == 0 and state['flash_cs'] == 1:
                    release_cycle = cycle
                if old['oe'] == 0 and state['oe'] == 1:
                    handoff_release = release_cycle
                    drive_cycle = cycle
            cycle += 1
    sm.dma_left = len(dma)
    return (rises, state, irqs, list(fifo), sm, handoff_release,
            drive_cycle, first_data_rise)


class LateMatchBurst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = assemble(str(PIOASM), 'burst_match_late_od.pio')
        cls.rom = ROM_PATH.read_bytes()
        cls.target = 0x03ae0140
        cls.reply = cls.rom[0xae0140:0xae0180]

    def check_route(self, commands):
        frames = [synthetic_samples(c, self.rom[c & 0xffffff:(c & 0xffffff) + 64])
                  for c in commands]
        target_at = commands.index(self.target)
        for phase in (0, 1):
            with self.subTest(commands=commands, phase=phase):
                rises, state, irqs, fifo, sm, release, drive, data_rise = replay(
                    self.program, frames, self.target, self.reply,
                    phase_cycles=phase)
                self.assertEqual(irqs, {1})
                self.assertEqual([len(x) for x in rises], [544] * len(frames))
                self.assertTrue(all(cs == 0 and oe == 0
                                    for frame in rises[:target_at]
                                    for cs, oe, _ in frame))
                self.assertTrue(all(cs == 0 and oe == 0
                                    for cs, oe, _ in rises[target_at][:31]))
                self.assertEqual(rises[target_at][31][:2], (1, 0))
                self.assertTrue(all(cs == 1 and oe == 1
                                    for cs, oe, _ in rises[target_at][32:]))
                bits = [(byte >> bit) & 1 for byte in self.reply
                        for bit in range(7, -1, -1)]
                self.assertEqual([b for _, _, b in rises[target_at][32:]], bits)
                self.assertIsNotNone(release)
                self.assertIsNotNone(drive)
                self.assertGreaterEqual(drive - release, 4)
                self.assertGreaterEqual(data_rise - drive, 2)
                self.assertEqual(fifo, [])
                self.assertEqual(sm.dma_left, 0)
                self.assertEqual(sm.x, 0xffffffff)
                self.assertEqual(state['oe'], 0)
                self.assertTrue(all(cs == 0 and oe == 0
                                    for frame in rises[target_at+1:]
                                    for cs, oe, _ in frame))

    def test_target_immediately_after_trigger(self):
        self.check_route((0x03ae0100, self.target, self.target))

    def test_target_after_intermediate_read(self):
        self.check_route((0x03ae0100, 0x03ae00c0, self.target, self.target))

    def test_odd_address_with_target_prefix_fails_before_miso(self):
        odd = self.target | 1
        frames = [synthetic_samples(odd, self.reply)]
        rises, state, irqs, _, _, _, _, _ = replay(
            self.program, frames, self.target, self.reply)
        self.assertIn(0, irqs)
        self.assertTrue(all(oe == 0 for _, oe, _ in rises[0]))
        self.assertEqual(state['oe'], 0)

    def test_physical_64_byte_read_if_available(self):
        if not CAPTURE_PATH.is_file():
            self.skipTest('private physical edge capture absent')
        raw = CAPTURE_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CAPTURE_SHA256)
        target = 0x03ae0180
        reply = self.rom[0xae0180:0xae01c0]
        rises, state, irqs, fifo, sm, release, drive, data_rise = replay(
            self.program, [snapshot_samples(raw.decode())], target, reply)
        self.assertEqual(len(rises[0]), 544)
        self.assertEqual(irqs, {1})
        self.assertEqual(fifo, [])
        self.assertEqual(sm.dma_left, 0)
        self.assertEqual(sm.x, 0xffffffff)
        self.assertEqual(state['oe'], 0)
        self.assertGreaterEqual(drive - release, 4)
        self.assertGreaterEqual(data_rise - drive, 2)
        bits = [(byte >> bit) & 1 for byte in reply
                for bit in range(7, -1, -1)]
        self.assertEqual([b for _, _, b in rises[0][32:]], bits)

    def test_physical_non_target_stays_on_original_flash(self):
        if not CAPTURE_PATH.is_file():
            self.skipTest('private physical edge capture absent')
        raw = CAPTURE_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CAPTURE_SHA256)
        rises, state, irqs, fifo, _, release, drive, _ = replay(
            self.program, [snapshot_samples(raw.decode())], self.target,
            self.reply)
        self.assertEqual(len(rises[0]), 544)
        self.assertEqual(irqs, set())
        self.assertTrue(all(cs == 0 and oe == 0 for cs, oe, _ in rises[0]))
        self.assertIsNone(drive)
        self.assertIsNone(release)
        self.assertEqual(state['oe'], 0)
        self.assertTrue(fifo)


if __name__ == '__main__':
    unittest.main()
