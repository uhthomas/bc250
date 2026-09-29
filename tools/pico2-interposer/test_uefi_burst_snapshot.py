#!/usr/bin/env python3
"""Exercise 64-byte burst framing and ROM-MISO comparison with synthetic samples."""

from pathlib import Path

from analyze_uefi_burst_snapshot import analyze, EXPECTED_COMMAND


ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / 'output/waveshare-recovery-20260925/waveshare-restore-20260925T1448Z/control.rom'


def make_snapshot(rom, corrupt=False):
    reply = rom[EXPECTED_COMMAND & 0xffffff:(EXPECTED_COMMAND & 0xffffff) + 64]
    data = EXPECTED_COMMAND.to_bytes(4, 'big') + reply
    samples = [0x21] * 8  # idle CS high, original-flash CS high
    for bit in range(8 * len(data)):
        value = (data[bit // 8] >> (7 - bit % 8)) & 1
        mosi = value if bit < 32 else 0
        miso = value if bit >= 32 else 0
        if corrupt and bit == 41:
            miso ^= 1
        pad = (mosi << 2) | (miso << 3)
        samples.extend([pad] * 2 + [pad | 2] * 3)
    samples.extend([0x21] * (5120 - len(samples)))
    assert len(samples) == 5120
    words = [sum(samples[5*i+j] << (6 * (4-j)) for j in range(5))
             for i in range(1024)]
    return ('BURST-SNAPSHOT words=1024 samples=5120 trigger=03ae00c0 expected=03ae0100\n'
            + ''.join(' '.join(f'{word:08x}' for word in words[i:i+8]) + '\n'
                      for i in range(0, len(words), 8)) + 'BURST-END\n')


def main():
    rom = ROM.read_bytes()
    passing = analyze(make_snapshot(rom), rom)
    assert passing['command_match']
    assert passing['reply_bits'] == 512
    assert passing['reply_bytes'] == 64
    assert passing['reply_matches_working_rom']
    assert passing['flash_cs_low_at_reply_edges'] == 512
    failing = analyze(make_snapshot(rom, corrupt=True), rom)
    assert failing['reply_mismatch_count'] == 1
    assert failing['first_reply_mismatch_bit'] == 9
    print('PASS: 64-byte MISO match and single-bit negative control')


if __name__ == '__main__':
    main()
