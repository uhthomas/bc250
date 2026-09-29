#!/usr/bin/env python3
"""Emulate both branches of the delayed VCN diagnostic PSP hook."""

import argparse
import hashlib
from pathlib import Path

import postload_model as model
import prepare_video_driver_trial as video


DRIVER = 0x984f00
DRIVER_LEN = 0x1a770
POWER = 0x1f810
SCRATCH = 0x1f854
RESET = 0x20180
SAMPLES = {'reset': RESET, 'cache-size0': 0x2010c}
RESULTS = {0x0900c004: 0, 0x1f8a4: 0, RESET: 0,
           **dict.fromkeys(dict(video.EXPECTED_MAP), 0)}
WINDOWS = dict(video.EXPECTED_MAP)
NORMAL_WRITES = ['0x900c004', '0x1f8a4'] + [hex(addr) for addr in WINDOWS] + [hex(RESET)]
DELAYED_WRITES = NORMAL_WRITES[:-1]


def check(driver: bytes, sample: int = RESET) -> int:
    cases = 0
    for scratch_result, scratch_value in ((0, 0), (0, 0x5a13c0de),
                                          (0xffff0007, 0)):
        readbacks = {SCRATCH: (scratch_result, scratch_value),
                     POWER: (0, 0x800), RESET: (0, 0)}
        row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                             loaded_before=1, expected_result=0,
                             readbacks=readbacks,
                             extra_writes={**WINDOWS, RESET: 0},
                             expected_smn_addresses=NORMAL_WRITES)
        reads = [event['address'] for event in row['events']
                 if event.get('stub_svc') == '0x7b']
        assert reads == [hex(POWER), hex(SCRATCH), hex(RESET)], reads
        cases += 1

    row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                         loaded_before=1, expected_result=0,
                         readbacks={POWER: (0, 0x801)},
                         expected_smn_addresses=['0x900c004', '0x1f8a4'])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(POWER)]
    cases += 1

    for sample_value in (0, 8, 0x64000, 0xffffffff):
        row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                             loaded_before=1,
                             expected_result=0x70000000 | (sample_value & 0xfffffff),
                             readbacks={POWER: (0, 0x800),
                                        SCRATCH: (0, 0x5a13c0df),
                                        sample: (0, sample_value)},
                             extra_writes=WINDOWS,
                             expected_smn_addresses=DELAYED_WRITES)
        reads = [event['address'] for event in row['events']
                 if event.get('stub_svc') == '0x7b']
        assert reads == [hex(POWER), hex(SCRATCH), hex(sample)], reads
        cases += 1

    row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                         loaded_before=1, expected_result=0xffff0009,
                         readbacks={POWER: (0, 0x800),
                                    SCRATCH: (0, 0x5a13c0df),
                                    sample: (0xffff0009, 0)},
                         extra_writes=WINDOWS,
                         expected_smn_addresses=DELAYED_WRITES)
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(POWER), hex(SCRATCH), hex(sample)]
    return cases + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--sample', choices=tuple(SAMPLES), default='reset')
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    if len(rom) != 0x1000000:
        raise ValueError('unexpected interposer view size')
    print(f"{check(rom[DRIVER:DRIVER + DRIVER_LEN], SAMPLES[args.sample])} "
          f"PSP-hook {args.sample} cases passed; "
          f"ROM SHA-256 {hashlib.sha256(rom).hexdigest()}")


if __name__ == '__main__':
    main()
