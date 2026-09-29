#!/usr/bin/env python3
"""Execute the signed map-and-reset PSP hook in the native ARM model."""

import argparse
import hashlib
from pathlib import Path

import postload_model as model
import prepare_vcn_psp_bo_fetch_trial as bo_fetch
import prepare_vcn_psp_tmr_reset_trial as tmr
import test_delayed_vcn_map_premap_trial as prior


def check(driver: bytes, use_tmr: bool = False) -> int:
    prior.select_map(tmr.TMR_MAP if use_tmr else bo_fetch.EXPECTED_BO_MAP)
    cases = 0
    for reset in (0, 8, 0x80008):
        row = model.run_case(
            0xffff, prior.RESULTS, 0, 0, driver_override=driver,
            loaded_before=1, expected_result=0x73000000 | reset,
            readbacks={prior.POWER: (0, 0x800),
                       prior.SCRATCH: (0, 0x5a13c0df),
                       **{addr: (0, value) for addr, value in prior.WINDOWS.items()},
                       prior.RESET: (0, reset)},
            expected_smn_addresses=prior.PREMAP_WRITES)
        reads = [int(event['address'], 16) for event in row['events']
                 if event.get('stub_svc') == '0x7b']
        assert reads == [prior.POWER, prior.SCRATCH] + \
            prior.WINDOW_ADDRESSES + [prior.RESET], reads
        assert not any(event.get('stub_svc') == '0x7c' and
                       int(event['address'], 16) in
                       (*prior.WINDOW_ADDRESSES, prior.RESET)
                       for event in row['events'])
        cases += 1

    index = 3
    addr = prior.WINDOW_ADDRESSES[index]
    altered = dict(prior.WINDOWS)
    altered[addr] ^= 0x100001
    prior.run(driver, altered,
              0x71000000 | (index << 20) | (altered[addr] & 0xfffff),
              prior.WINDOW_ADDRESSES[:index + 1])
    cases += 1

    row = model.run_case(
        0xffff, prior.RESULTS, 0, 0, driver_override=driver,
        loaded_before=1, expected_result=0xffff0009,
        readbacks={prior.POWER: (0, 0x800),
                   prior.SCRATCH: (0, 0x5a13c0df),
                   **{addr: (0, value) for addr, value in prior.WINDOWS.items()},
                   prior.RESET: (0xffff0009, 0)},
        expected_smn_addresses=prior.PREMAP_WRITES)
    reads = [int(event['address'], 16) for event in row['events']
             if event.get('stub_svc') == '0x7b']
    assert reads == [prior.POWER, prior.SCRATCH] + \
        prior.WINDOW_ADDRESSES + [prior.RESET], reads
    cases += 1

    for scratch_result, scratch_value in ((0, 0), (0xffff0007, 0)):
        row = model.run_case(
            0xffff, prior.RESULTS, 0, 0, driver_override=driver,
            loaded_before=1, expected_result=0,
            readbacks={prior.POWER: (0, 0x800),
                       prior.SCRATCH: (scratch_result, scratch_value),
                       prior.RESET: (0, 0)},
            extra_writes={**dict(prior.MAP), prior.RESET: 0},
            expected_smn_addresses=prior.NORMAL_WRITES)
        reads = [int(event['address'], 16) for event in row['events']
                 if event.get('stub_svc') == '0x7b']
        assert reads == [prior.POWER, prior.SCRATCH, prior.RESET], reads
        cases += 1
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--tmr', action='store_true')
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    if len(rom) != 0x1000000:
        raise ValueError('unexpected interposer view size')
    print(f'{check(rom[prior.DRIVER:prior.DRIVER + prior.DRIVER_LEN], args.tmr)} '
          f'PSP map/reset cases passed; ROM SHA256 '
          f'{hashlib.sha256(rom).hexdigest()}')


if __name__ == '__main__':
    main()
