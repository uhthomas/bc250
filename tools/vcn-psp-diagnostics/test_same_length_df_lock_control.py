#!/usr/bin/env python3
"""Verify equal-length recompression affects only the compressed stream."""

import hashlib
import lzma
from pathlib import Path
import unittest

from prepare_same_length_df_lock_control import (
    build, FILE_START, STREAM_START, WORKING_SHA256, CANDIDATE_SHA256,
    verify_outer_headers)


ROOT = Path(__file__).resolve().parents[2]
WORKING = ROOT / 'output/waveshare-recovery-20260925/waveshare-restore-20260925T1448Z/control.rom'
FOLDER = ROOT / 'output/video-decode-20260922/df-lock-control-20260928'
CANDIDATE = FOLDER / 'UNTESTED-NEVER-flash-df-lock-control.rom'


class SameLengthDfLock(unittest.TestCase):
    def test_pinned_rebuild_preserves_headers_and_length(self):
        if not WORKING.is_file() or not CANDIDATE.is_file():
            self.skipTest('private ROM inputs absent')
        working, candidate = WORKING.read_bytes(), CANDIDATE.read_bytes()
        image, report = build(working, candidate)
        self.assertEqual(hashlib.sha256(working).hexdigest(), WORKING_SHA256)
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), CANDIDATE_SHA256)
        self.assertEqual(report['image_sha256'],
                         'ae9145cfa521107ebb7e553c39877a89f822ea1960e16f83a38485b9b5fe2331')
        self.assertEqual(report['trailing_padding_bytes'], 243)
        self.assertEqual(report['first_changed_spi_offset'], 'aede82')
        self.assertEqual(image[FILE_START:STREAM_START], working[FILE_START:STREAM_START])
        self.assertEqual(image[0xAE0000:0xAE0140], working[0xAE0000:0xAE0140])
        self.assertEqual(report['new_ffs_file_size'], report['original_ffs_file_size'])
        verify_outer_headers(image)
        self.assertEqual(image[FILE_START + 17], 0xaa)
        self.assertEqual(image[FILE_START + 19] & 0x40, 0)
        stream = image[STREAM_START:FILE_START + report['new_ffs_file_size']]
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        decoder.decompress(stream)
        self.assertTrue(decoder.eof)
        self.assertEqual(decoder.unused_data, b'\xff' * 243)

    def test_rejects_wrong_prior_candidate(self):
        if not WORKING.is_file():
            self.skipTest('private working ROM absent')
        working = WORKING.read_bytes()
        with self.assertRaisesRegex(ValueError, 'candidate'):
            build(working, working)


if __name__ == '__main__':
    unittest.main()
