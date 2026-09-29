#!/usr/bin/env python3
"""Decode the input-only UEFI SPI burst snapshot and compare with working ROM."""

import argparse
import hashlib
import json
from pathlib import Path
import re


ROM_SHA256 = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
EXPECTED_COMMAND = 0x03ae0100
MAX_CAPTURE_COMMAND = EXPECTED_COMMAND + 0x100
SAMPLE_HZ = 340_000_000 // 2


def analyze(snapshot: str, rom: bytes) -> dict:
    if hashlib.sha256(rom).hexdigest() != ROM_SHA256:
        raise ValueError('ROM is not pinned working control')
    lines = snapshot.strip().splitlines()
    expected_header = 'BURST-SNAPSHOT words=1024 samples=5120 trigger=03ae00c0 expected=03ae0100'
    if not lines or lines[0] != expected_header or lines[-1] != 'BURST-END':
        raise ValueError('bad or incomplete snapshot framing')
    payload = ' '.join(lines[1:-1]).split()
    if len(payload) != 1024 or any(not re.fullmatch('[0-9a-f]{8}', item) for item in payload):
        raise ValueError('snapshot word count or hex encoding invalid')
    words = [int(item, 16) for item in payload]
    samples = [(word >> (6 * (4 - index))) & 0x3f
               for word in words for index in range(5)]
    first = next((i for i, sample in enumerate(samples) if not sample & 1), None)
    if first is None:
        raise ValueError('no host CS-low interval captured')
    end = next((i for i in range(first + 1, len(samples)) if samples[i] & 1), None)
    if end is None:
        raise ValueError('host CS did not rise before sample buffer ended')
    rises = [i for i in range(first + 1, end)
             if not samples[i - 1] & 2 and samples[i] & 2]
    if len(rises) < 32:
        raise ValueError(f'only {len(rises)} SCLK rises in capture')
    command = sum(bool(samples[i] & 4) << (31 - bit)
                  for bit, i in enumerate(rises[:32]))
    reply_bits = [bool(samples[i] & 8) for i in rises[32:]]
    command_in_window = (EXPECTED_COMMAND <= command <= MAX_CAPTURE_COMMAND and
                         (command - EXPECTED_COMMAND) % 0x40 == 0)
    expected = rom[command & 0xffffff:] if command_in_window else b''
    expected_bits = [(expected[i // 8] >> (7 - i % 8)) & 1
                     for i in range(min(len(reply_bits), len(expected) * 8))]
    errors = [i for i, (got, want) in enumerate(zip(reply_bits, expected_bits))
              if got != want]
    periods = [b - a for a, b in zip(rises, rises[1:])]
    return {
        'captured_command': f'0x{command:08x}',
        'expected_command': f'0x{EXPECTED_COMMAND:08x}',
        'command_match': command_in_window,
        'bursts_after_nominal_target': (command - EXPECTED_COMMAND) // 0x40 if command_in_window else None,
        'spi_clock_edges': len(rises),
        'reply_bits': len(reply_bits),
        'reply_bytes': len(reply_bits) // 8,
        'reply_matches_working_rom': not errors and len(reply_bits) % 8 == 0,
        'reply_mismatch_count': len(errors),
        'first_reply_mismatch_bit': errors[0] if errors else None,
        'flash_cs_low_at_reply_edges': sum(not samples[i] & 32 for i in rises[32:]),
        'flash_cs_high_at_reply_edges': sum(bool(samples[i] & 32) for i in rises[32:]),
        'host_cs_low_samples': end - first,
        'sample_period_ns': 1e9 / SAMPLE_HZ,
        'sclk_period_ns_min': min(periods) * 1e9 / SAMPLE_HZ if periods else None,
        'sclk_period_ns_max': max(periods) * 1e9 / SAMPLE_HZ if periods else None,
        'approx_spi_clock_hz': SAMPLE_HZ / (sum(periods) / len(periods)) if periods else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshot', type=Path, required=True)
    ap.add_argument('--rom', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = analyze(args.snapshot.read_text(), args.rom.read_bytes())
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result['command_match'] or not result['reply_matches_working_rom']:
        raise SystemExit('capture did not match pinned original ROM')


if __name__ == '__main__':
    main()
