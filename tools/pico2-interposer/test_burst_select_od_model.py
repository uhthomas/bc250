#!/usr/bin/env python3
"""Digital 64-byte PIO selector replay against synthetic and captured edges."""

import collections
import hashlib
from pathlib import Path
import unittest

from fast_select_model import assemble
from router_model import SM


ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / 'output/waveshare-recovery-20260925/waveshare-restore-20260925T1448Z/control.rom'
CAPTURE_PATH = ROOT / 'output/video-decode-20260922/df-lock-control-20260928/boot-0.snapshot.txt'
CAPTURE_SHA256 = 'e0714c82feb8ec26ca2be33aec4a85f6e5bc717b407999eed7a6be4ade218cd9'
PIOASM = ROOT / 'output/pico2/build-uefi-burst-riscv/pioasm/pioasm'


def snapshot_samples(text):
    lines = text.strip().splitlines()
    assert lines[0].startswith('BURST-SNAPSHOT words=1024') and lines[-1] == 'BURST-END'
    words = [int(token, 16) for token in ' '.join(lines[1:-1]).split()]
    assert len(words) == 1024
    samples = [(word >> (6 * (4 - j))) & 0x3f for word in words for j in range(5)]
    first = next(i for i, sample in enumerate(samples) if not sample & 1)
    end = next(i for i in range(first + 1, len(samples)) if samples[i] & 1)
    return samples[:end+1] + [0x21] * 32


def synthetic_samples(command, reply):
    data = command.to_bytes(4, 'big') + reply
    samples = [0x21] * 16
    for bit in range(len(data) * 8):
        val = (data[bit // 8] >> (7 - bit % 8)) & 1
        pad = ((val << 2) if bit < 32 else (val << 3))
        samples.extend([pad] * 2 + [pad | 2] * 3)
    return samples + [0x21] * 32


def replay(program, samples, command, reply, *, wrong_command=False, sync_cycles=2,
           phase_cycles=0, system_hz=340_000_000):
    words = [int.from_bytes(reply[i:i+4], 'big') for i in range(0, 64, 4)]
    fifo = collections.deque([1, command ^ int(wrong_command), 510, *words])
    sm = SM(program, fifo, out_autopull=True, out_threshold=32)
    # The active tuple is queued only after many default PASS transactions.
    # Those leave the selector with a full, zero-valued OSR.  Starting with
    # the RP2350's reset-empty OSR and a preloaded tuple would race autopull
    # before the first transaction, which is not this control's schedule.
    sm.osr = 0
    sm.out_bits = 0
    pipe = collections.deque([4] * sync_cycles)
    irqs = set()
    state = dict(flash_cs=1, oe=0, data=0)
    rise_state = []
    previous_clk = 0
    for sample_index, sample in enumerate([0x21] * 20 + samples):
        pins = (sample & 7) << 2
        steps = (((sample_index + 1) * system_hz) // 170_000_000
                 - (sample_index * system_hz) // 170_000_000)
        if sample_index == 0 and phase_cycles:
            steps -= 1
        for sub in range(steps):
            cs, clk = bool(sample & 1), bool(sample & 2)
            if not cs and clk and not previous_clk and sub == 0:
                rise_state.append((state['flash_cs'], state['oe'], state['data']))
            pipe.append(pins)
            state.update(sm.step(pipe.popleft(), irqs))
            if sub == 0:
                previous_clk = clk
    return rise_state, state, irqs, list(fifo)


class BurstSelectModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PIOASM.is_file():
            raise unittest.SkipTest('PIO assembler not present in local build')
        cls.program = assemble(str(PIOASM), 'burst_select_od.pio')
        cls.rom = ROM_PATH.read_bytes()
        cls.command = 0x03ae0180
        cls.reply = cls.rom[cls.command & 0xffffff:(cls.command & 0xffffff) + 64]

    def test_program_fits_and_only_changes_cs_direction(self):
        instructions = [int(row['hex'], 16) for row in self.program['instructions']]
        self.assertLessEqual(len(instructions), 32)
        destinations = [(ins >> 5) & 7 for ins in instructions if ins >> 13 == 7]
        self.assertNotIn(0, destinations)
        self.assertIn(4, destinations)

    def check_trace(self, samples):
        for phase in (0, 1):
            with self.subTest(sync=2, phase=phase):
                rises, state, irqs, remaining = replay(
                    self.program, samples, self.command, self.reply,
                    sync_cycles=2, phase_cycles=phase)
                self.assertEqual(len(rises), 544)
                self.assertEqual(irqs, set())
                self.assertEqual(remaining, [])
                self.assertTrue(all(flash_cs == 1 and oe == 0
                                    for flash_cs, oe, _ in rises[:32]))
                expected_bits = [(byte >> bit) & 1
                                 for byte in self.reply for bit in range(7, -1, -1)]
                self.assertEqual([data for _, _, data in rises[32:]], expected_bits)
                self.assertTrue(all(flash_cs == 1 and oe == 1
                                    for flash_cs, oe, _ in rises[32:]))
                self.assertEqual(state['oe'], 0)

    def test_synthetic_64_byte_read(self):
        self.check_trace(synthetic_samples(self.command, self.reply))

    def test_captured_64_byte_read_if_available(self):
        if not CAPTURE_PATH.is_file():
            self.skipTest('private input-only board capture absent')
        raw = CAPTURE_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CAPTURE_SHA256)
        self.check_trace(snapshot_samples(raw.decode()))

    def test_wrong_command_faults_before_data(self):
        rises, _, irqs, _ = replay(self.program,
                                   synthetic_samples(self.command, self.reply),
                                   self.command, self.reply, wrong_command=True)
        self.assertEqual(len(rises), 544)
        self.assertIn(0, irqs)
        self.assertTrue(all(oe == 0 for _, oe, _ in rises))

    def test_live_trigger_then_pass_then_target_schedule(self):
        # Start at RP2350 reset with no FIFO data. Queue the five-word tuple
        # during the trigger read, just as core1 does on the actual board.
        commands = (0x03ae0100, 0x03ae00c0, 0x03ae0140)
        replies = [self.rom[c & 0xffffff:(c & 0xffffff) + 64]
                   for c in commands]
        target_words = [int.from_bytes(replies[2][i:i+4], 'big')
                        for i in range(0, 64, 4)]
        fifo = collections.deque()
        sm = SM(self.program, fifo, out_autopull=True, out_threshold=32)
        pipe = collections.deque([4] * 2)
        irqs = set()
        state = dict(flash_cs=1, oe=0, data=0)
        seen = [[] for _ in commands]
        scheduled = False
        dma = iter(target_words[1:])
        pending_word = None
        transaction = -1
        clocks = 0
        previous_cs, previous_clk = 1, 0
        samples = ([0x21] * 20 +
                   [sample for c, r in zip(commands, replies)
                    for sample in synthetic_samples(c, r)])
        for sample in samples:
            cs, clk = sample & 1, (sample >> 1) & 1
            if previous_cs and not cs:
                transaction += 1
                clocks = 0
            if not cs and clk and not previous_clk:
                clocks += 1
                seen[transaction].append((state['flash_cs'], state['oe'], state['data']))
                if transaction == 0 and clocks == 32:
                    fifo.extend((0, 1, commands[2], 510, target_words[0]))
                    scheduled = True
            previous_cs, previous_clk = cs, clk
            for _ in range(2):
                if scheduled and pending_word is None:
                    pending_word = next(dma, None)
                if pending_word is not None and len(fifo) < 8:
                    fifo.append(pending_word)
                    pending_word = None
                pipe.append((sample & 7) << 2)
                state.update(sm.step(pipe.popleft(), irqs))
        self.assertEqual(irqs, set())
        self.assertEqual([len(row) for row in seen], [544] * 3)
        self.assertTrue(all(cs == 0 and oe == 0
                            for row in seen[:2] for cs, oe, _ in row))
        self.assertTrue(all(cs == 1 and oe == 0 for cs, oe, _ in seen[2][:32]))
        self.assertTrue(all(cs == 1 and oe == 1 for cs, oe, _ in seen[2][32:]))
        expected = [(byte >> bit) & 1 for byte in replies[2]
                    for bit in range(7, -1, -1)]
        self.assertEqual([bit for _, _, bit in seen[2][32:]], expected)
        self.assertEqual(list(fifo), [])
        self.assertIsNone(pending_word)
        self.assertIsNone(next(dma, None))

    def test_three_cycle_input_delay_is_not_qualified(self):
        rises, _, irqs, _ = replay(self.program,
                                   synthetic_samples(self.command, self.reply),
                                   self.command, self.reply, sync_cycles=3)
        expected = [(byte >> bit) & 1 for byte in self.reply for bit in range(7, -1, -1)]
        self.assertEqual(len(rises), 544)
        self.assertEqual(irqs, set())
        self.assertNotEqual([data for _, _, data in rises[32:]], expected)


if __name__ == '__main__':
    unittest.main()
