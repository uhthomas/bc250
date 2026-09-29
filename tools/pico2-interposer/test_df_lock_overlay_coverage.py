#!/usr/bin/env python3
"""Pin the changed-header and changed-tail coverage in both boot captures."""

import json
from pathlib import Path
import unittest

from analyze_df_lock_overlay_coverage import (
    coverage, find_scans, pinned_rom, WORKING_SHA256, CANDIDATE_SHA256)
from analyze_full_cs_stream import expand


ROOT = Path(__file__).resolve().parents[2]
WORKING = ROOT / 'output/waveshare-recovery-20260925/waveshare-restore-20260925T1448Z/control.rom'
FOLDER = ROOT / 'output/video-decode-20260922/df-lock-control-20260928'
CANDIDATE = FOLDER / 'UNTESTED-NEVER-flash-df-lock-control.rom'
TRACES = (ROOT / 'output/pico2/boot-rle-20260927.bin', FOLDER / 'boot-20260928.bin')


class DfLockOverlayCoverage(unittest.TestCase):
    def test_full_captures_expose_short_scan_and_unobserved_tail(self):
        if not all(path.is_file() for path in (WORKING, CANDIDATE, *TRACES)):
            self.skipTest('private ROM or full-command capture absent')
        working = pinned_rom(WORKING, WORKING_SHA256)
        candidate = pinned_rom(CANDIDATE, CANDIDATE_SHA256)
        for path in TRACES:
            with self.subTest(path=path):
                commands = expand(path.read_bytes(), json.loads(path.with_suffix('.json').read_text()))
                result = coverage(commands, working, candidate)
                self.assertEqual(result['changed_short_word_addresses'],
                                 ['ae0088', 'ae008c', 'ae0090'])
                self.assertEqual(result['observed_long_run_end_exclusive'], 'c31c40')
                self.assertEqual(result['changed_bytes_after_observed_long_run'], 788)
                self.assertEqual(result['last_changed_byte_after_observed_long_run'], 'c31f57')
                self.assertEqual(len(result['passes']), 2)
                self.assertTrue(all(p['long_run_reads'] == 21612 for p in result['passes']))
                self.assertTrue(all(p['changed_long_reads'] == 21607 for p in result['passes']))

    def test_short_scan_requires_all_48_commands(self):
        command = 0x03AE0000
        stream = [command + 4 * i for i in range(48)]
        self.assertEqual(find_scans(stream), [0])
        stream[34] += 4
        self.assertEqual(find_scans(stream), [])

    def test_rejects_unpinned_rom(self):
        with self.assertRaises(ValueError):
            pinned_rom(Path(__file__), WORKING_SHA256)


if __name__ == '__main__':
    unittest.main()
