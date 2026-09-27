#!/usr/bin/env python3
"""Execute the transient PSP VCN cache-register write/readback hook offline."""
import argparse
import importlib.util
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        'bc250_postload_model', Path(__file__).with_name('postload_model.py'))
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    target, written = 0x2107c, 0x1fa00000
    address_order = ['0x900c004', '0x1f8a4', '0x2107c']
    cases = 0

    for value in (0, written, 0xffffffff, 0xdeadbeef):
        row = model.run_case(
            0xffff, {0x0900c004: 0, 0x1f8a4: 0, target: 0}, 0, 0,
            driver_override=driver, expected_result=0x70000000 | (value & 0x0fffffff),
            expected_smn_addresses=address_order,
            readback=(0, value), readback_address=target,
            extra_write=(target, written))
        assert row['loaded_flag'] == 0
        assert row['events'][2]['value'] == written
        cases += 1

    for failing_address, expected_order in (
            (0x0900c004, address_order[:1]),
            (0x1f8a4, address_order[:2]),
            (target, address_order)):
        error = 0xffff0013
        results = {0x0900c004: 0, 0x1f8a4: 0, target: 0}
        results[failing_address] = error
        row = model.run_case(
            0xffff, results, 0, 0, driver_override=driver,
            expected_result=error, expected_smn_addresses=expected_order,
            readback_address=target, extra_write=(target, written))
        assert row['loaded_flag'] == 0
        assert not any(e.get('stub_svc') == '0x7b' for e in row['events'])
        cases += 1

    row = model.run_case(
        0xffff, {0x0900c004: 0, 0x1f8a4: 0, target: 0}, 0, 0,
        driver_override=driver, expected_result=0xffff0014,
        expected_smn_addresses=address_order,
        readback=(0xffff0014, 0), readback_address=target,
        extra_write=(target, written))
    assert row['loaded_flag'] == 0
    cases += 1

    for context in (0, 7):
        row = model.run_case(
            context, {0x1f8a4: 0}, 0, 0, driver_override=driver,
            expected_smn_addresses=['0x1f8a4'], extra_write=(target, written))
        assert row['loaded_flag'] == 1
        assert not any(e.get('address') == hex(target) for e in row['events'])
        cases += 1
    print(f'{cases} real-instruction VCN cache-write cases passed')


if __name__ == '__main__':
    main()
