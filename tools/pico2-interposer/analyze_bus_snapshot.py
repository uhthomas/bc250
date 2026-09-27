#!/usr/bin/env python3
"""Decode a short Pico 2 GP2..GP7 PIO/DMA snapshot around one READ03 reply."""
import argparse
import json
from pathlib import Path


def analyze(path, expected_command, expected_reply, system_hz=340_000_000):
    text = path.read_text()
    if not text.startswith('SNAPSHOT words=128 samples=640\n'):
        raise ValueError('unexpected snapshot header')
    words = [int(word, 16) for word in text.split()[3:]]
    if len(words) != 128:
        raise ValueError(f'expected 128 words, found {len(words)}')
    samples = [(word >> (6 * (4 - index))) & 0x3f
               for word in words for index in range(5)]
    rises = [index for index in range(1, len(samples))
             if not (samples[index - 1] & 2) and samples[index] & 2
             and not (samples[index] & 1)]
    if len(rises) < 62:
        raise ValueError(f'expected at least 62 SCLK rising edges, found {len(rises)}')
    command_bits = [bool(samples[index] & 4) for index in rises[:32]]
    command = sum(bit << (31 - index) for index, bit in enumerate(command_bits))
    if command != expected_command:
        raise ValueError(f'wrong captured command {command:08x}')
    reply_bits = [bool(samples[index] & 8) for index in rises[32:]]
    expected_bits = [(expected_reply >> (31 - index)) & 1
                     for index in range(len(reply_bits))]
    mismatches = [index + 1 for index, (got, wanted)
                  in enumerate(zip(reply_bits, expected_bits)) if got != wanted]
    miso_changes = [index for index in range(1, len(samples))
                    if bool(samples[index - 1] & 8) != bool(samples[index] & 8)]
    setup_samples = []
    for index in range(1, len(reply_bits)):
        if reply_bits[index] == reply_bits[index - 1]:
            continue
        prior, current = rises[31 + index], rises[32 + index]
        candidates = [edge for edge in miso_changes if prior < edge <= current]
        if len(candidates) != 1:
            raise ValueError(f'reply bit {index + 1}: expected one MISO edge, found {len(candidates)}')
        setup_samples.append(current - candidates[0])
    data_rises = rises[32:]
    periods = [b - a for a, b in zip(rises, rises[1:])]
    return {
        'path': str(path), 'sample_count': len(samples),
        'pio_sample_period_ns': 2e9 / system_hz,
        'command': f'{command:08x}',
        'expected_reply': f'{expected_reply:08x}',
        'captured_reply_bits': len(reply_bits),
        'captured_reply_prefix': ''.join(str(int(bit)) for bit in reply_bits),
        'reply_bit_mismatches': mismatches,
        'sclk_period_samples': sorted(set(periods[2:-2])),
        'miso_transition_setup_samples': setup_samples,
        'minimum_transition_setup_ns': min(setup_samples) * 2e9 / system_hz,
        'flash_cs_high_at_data_rises': sum(bool(samples[index] & 32)
                                            for index in data_rises),
        'flash_cs_low_at_data_rises': sum(not(samples[index] & 32)
                                           for index in data_rises),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshots', type=Path, nargs='+')
    parser.add_argument('--command', type=lambda s: int(s, 0), default=0x039db140)
    parser.add_argument('--reply', type=lambda s: int(s, 0), default=0x3b1e623e)
    args = parser.parse_args()
    print(json.dumps([analyze(path, args.command, args.reply)
                      for path in args.snapshots], indent=2))


if __name__ == '__main__':
    main()
