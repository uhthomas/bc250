#!/usr/bin/env python3
"""Safety checks for the diagnostic batch cold-cycle ordering."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'iterate_diagnostic', Path(__file__).with_name('iterate_diagnostic.py'))
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


class CycleTest(unittest.TestCase):
    def test_diagnostic_cycle_stops_timer_before_cleanup(self):
        events = []
        new = {'boot_id': 'new', 'kind': 'diagnostic'}
        with patch.object(batch, 'pdu_reboot', side_effect=lambda: events.append('reboot')), \
             patch.object(batch, 'wait_new_boot', return_value=new) as wait, \
             patch.object(batch, 'require_consumed',
                          side_effect=lambda _: events.append('consumed')), \
             patch.object(batch, 'stop_timer',
                          side_effect=lambda _: events.append('stop')), \
             patch.object(batch, 'cleanup_consumed',
                          side_effect=lambda: events.append('cleanup')):
            self.assertEqual(batch.cycle('old', 'diagnostic', 'timer'), new)
        wait.assert_called_once_with('old')
        self.assertEqual(events, ['reboot', 'consumed', 'stop', 'cleanup'])

    def test_unexpected_normal_boot_stops_timer_and_fails(self):
        events = []
        new = {'boot_id': 'new', 'kind': 'normal'}
        with patch.object(batch, 'pdu_reboot', side_effect=lambda: events.append('reboot')), \
             patch.object(batch, 'wait_new_boot', return_value=new), \
             patch.object(batch, 'require_clean_boot',
                          side_effect=lambda *_: events.append('verified')), \
             patch.object(batch, 'stop_timer',
                          side_effect=lambda _: events.append('stop')):
            with self.assertRaisesRegex(RuntimeError, 'expected diagnostic'):
                batch.cycle('old', 'diagnostic', 'timer')
        self.assertEqual(events, ['reboot', 'verified', 'stop'])

    def test_unknown_boot_keeps_recovery_timer_armed(self):
        new = {'boot_id': 'new', 'kind': 'unknown'}
        with patch.object(batch, 'pdu_reboot'), \
             patch.object(batch, 'wait_new_boot', return_value=new), \
             patch.object(batch, 'stop_timer') as stop:
            with self.assertRaises(RuntimeError):
                batch.cycle('old', 'diagnostic', 'timer')
        stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
