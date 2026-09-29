#!/usr/bin/env python3
"""Run the real signed-driver pre-map comparison instructions in Unicorn."""

import argparse
import hashlib
from pathlib import Path

import postload_model as model
import prepare_vcn_psp_bo_fetch_trial as bo_fetch
import prepare_video_driver_trial as video


DRIVER = 0x984f00
DRIVER_LEN = 0x1a770
POWER = 0x1f810
SCRATCH = 0x1f854
RESET = 0x20180
MAP = video.EXPECTED_MAP
WINDOWS = dict(MAP[:16])
RESULTS = {0x0900c004: 0, 0x1f8a4: 0, RESET: 0,
           **dict.fromkeys(dict(MAP), 0)}
NORMAL_WRITES = ['0x900c004', '0x1f8a4'] + [hex(addr) for addr, _ in MAP] + [hex(RESET)]
PREMAP_WRITES = NORMAL_WRITES[:2]
WINDOW_ADDRESSES = list(WINDOWS)


def select_map(pairs: tuple[tuple[int, int], ...]) -> None:
    global MAP, WINDOWS, RESULTS, NORMAL_WRITES, PREMAP_WRITES, WINDOW_ADDRESSES
    MAP = pairs
    WINDOWS = dict(MAP[:16])
    RESULTS = {0x0900c004: 0, 0x1f8a4: 0, RESET: 0,
               **dict.fromkeys(dict(MAP), 0)}
    NORMAL_WRITES = ['0x900c004', '0x1f8a4'] + [hex(addr) for addr, _ in MAP] + [hex(RESET)]
    PREMAP_WRITES = NORMAL_WRITES[:2]
    WINDOW_ADDRESSES = list(WINDOWS)


def run(driver: bytes, values: dict[int, int], expected_result: int,
        expected_reads: list[int]) -> None:
    row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                         loaded_before=1, expected_result=expected_result,
                         readbacks={POWER: (0, 0x800),
                                    SCRATCH: (0, 0x5a13c0df),
                                    **{addr: (0, value) for addr, value in values.items()}},
                         expected_smn_addresses=PREMAP_WRITES)
    reads = [int(event['address'], 16) for event in row['events']
             if event.get('stub_svc') == '0x7b']
    assert reads == [POWER, SCRATCH] + expected_reads, reads
    assert not any(event.get('stub_svc') == '0x7c' and
                   int(event['address'], 16) in WINDOWS for event in row['events'])


def check(driver: bytes) -> int:
    cases = 0
    run(driver, WINDOWS, 0x70000010, WINDOW_ADDRESSES)
    cases += 1

    for index, address in enumerate(WINDOW_ADDRESSES):
        values = dict(WINDOWS)
        values[address] ^= 0x00100001
        observed = values[address]
        result = 0x71000000 | (index << 20) | (observed & 0xfffff)
        run(driver, values, result, WINDOW_ADDRESSES[:index + 1])
        cases += 1

    # A change confined to bits omitted from the diagnostic status must
    # still be detected by the full-width comparison.
    high_only = dict(WINDOWS)
    high_only[WINDOW_ADDRESSES[0]] ^= 0x10000000
    run(driver, high_only,
        0x71000000 | (high_only[WINDOW_ADDRESSES[0]] & 0xfffff),
        WINDOW_ADDRESSES[:1])
    cases += 1

    for failed_index in (0, 15):
        failed_address = WINDOW_ADDRESSES[failed_index]
        readbacks = {POWER: (0, 0x800), SCRATCH: (0, 0x5a13c0df),
                     **{addr: (0, value) for addr, value in WINDOWS.items()}}
        readbacks[failed_address] = (0xffff0009, 0)
        row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                             loaded_before=1, expected_result=0xffff0009,
                             readbacks=readbacks,
                             expected_smn_addresses=PREMAP_WRITES)
        reads = [int(event['address'], 16) for event in row['events']
                 if event.get('stub_svc') == '0x7b']
        assert reads == [POWER, SCRATCH] + WINDOW_ADDRESSES[:failed_index + 1]
        cases += 1

    for scratch_result, scratch_value in ((0, 0), (0xffff0007, 0)):
        row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                             loaded_before=1, expected_result=0,
                             readbacks={POWER: (0, 0x800),
                                        SCRATCH: (scratch_result, scratch_value),
                                        RESET: (0, 0)},
                             extra_writes={**dict(MAP), RESET: 0},
                             expected_smn_addresses=NORMAL_WRITES)
        reads = [int(event['address'], 16) for event in row['events']
                 if event.get('stub_svc') == '0x7b']
        assert reads == [POWER, SCRATCH, RESET]
        cases += 1

    row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                         loaded_before=1, expected_result=0,
                         readbacks={POWER: (0, 0x801)},
                         expected_smn_addresses=PREMAP_WRITES)
    assert [int(event['address'], 16) for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [POWER]
    return cases + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--direct-bo', action='store_true',
                        help='expect the guarded ordinary-BO VCN map')
    args = parser.parse_args()
    select_map(bo_fetch.EXPECTED_BO_MAP if args.direct_bo else video.EXPECTED_MAP)
    rom = args.rom.read_bytes()
    if len(rom) != 0x1000000:
        raise ValueError('unexpected interposer view size')
    print(f'{check(rom[DRIVER:DRIVER + DRIVER_LEN])} '
          f'PSP pre-map comparison cases passed; '
          f'ROM SHA256 {hashlib.sha256(rom).hexdigest()}')


if __name__ == '__main__':
    main()
