#!/usr/bin/env python3
"""Check the staged Pico payload against the pinned equal-length ROM."""

import hashlib
from pathlib import Path
import re
import unittest

from prepare_same_length_payload import (
    build, ROM_START, ROM_END, PICO_FLASH_OFFSET, CANDIDATE_SHA256)


ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'output/video-decode-20260922/df-lock-control-20260928'
CANDIDATE = FOLDER / 'UNTESTED-NEVER-flash-df-lock-same-length.rom'
BACKUP = FOLDER / 'pico2-flash-20260928.bin'
PAYLOAD = FOLDER / 'UNTESTED-pico-qspi-payload.bin'
HEADER = FOLDER / 'df_lock_same_length_payload.h'


class SameLengthPayload(unittest.TestCase):
    def test_every_first_word_and_full_payload_match_candidate(self):
        if not all(path.is_file() for path in (CANDIDATE, BACKUP, PAYLOAD, HEADER)):
            self.skipTest('private ROM, Pico backup or payload absent')
        candidate, backup = CANDIDATE.read_bytes(), BACKUP.read_bytes()
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), CANDIDATE_SHA256)
        payload, header, report = build(candidate, backup)
        self.assertEqual(PAYLOAD.read_bytes(), payload)
        self.assertEqual(HEADER.read_text(), header)
        self.assertEqual(payload[:ROM_END - ROM_START], candidate[ROM_START:ROM_END])
        self.assertTrue(all(byte == 0xff for byte in payload[ROM_END - ROM_START:]))
        self.assertEqual(backup[PICO_FLASH_OFFSET:PICO_FLASH_OFFSET + len(payload)],
                         b'\xff' * len(payload))
        words = [int(value, 16) for value in re.findall(r'0x([0-9a-f]{8})u',
                                                   header.split('df_lock_first_words')[1])]
        self.assertEqual(len(words), 20727)
        for i, word in enumerate(words):
            self.assertEqual(word.to_bytes(4, 'big'), payload[i * 64:i * 64 + 4])
        self.assertEqual(report['payload_sha256'],
                         '94693ac43e90236b77e6fc2be64c4ab8e48e18fd88b0ec6c3b95ae9af1e53ef9')
        control = Path(__file__).with_name('df_lock_stream_control.c').read_text()
        match = re.search(r'PAYLOAD_SHA256\[32\] = \{([^}]+)\};', control)
        self.assertIsNotNone(match)
        digest_bytes = bytes(int(value, 16) for value in
                             re.findall(r'0x([0-9a-f]{2})', match.group(1)))
        self.assertEqual(digest_bytes, hashlib.sha256(payload).digest())
        self.assertIn(f'PAYLOAD_BYTES = {len(payload)}u', control)

    def test_rejects_mismatched_backup(self):
        if not CANDIDATE.is_file() or not BACKUP.is_file():
            self.skipTest('private ROM or Pico backup absent')
        backup = bytearray(BACKUP.read_bytes())
        backup[PICO_FLASH_OFFSET] = 0
        with self.assertRaisesRegex(ValueError, 'backup'):
            build(CANDIDATE.read_bytes(), bytes(backup))


if __name__ == '__main__':
    unittest.main()
