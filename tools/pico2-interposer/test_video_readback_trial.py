#!/usr/bin/env python3
"""Exercise the PSP-side reset readback candidate with modeled SVC results."""
import argparse
import importlib.util
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--address', type=lambda value: int(value, 0), default=0x0900c004)
    args = parser.parse_args()
    model_path = Path(__file__).with_name('postload_model.py')
    spec = importlib.util.spec_from_file_location('bc250_readback_model', model_path)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    cases = 0
    for value in (0, 1, 0xffffffff, 0xdeadbeef):
        expected = 0x70000000 | (value & 0x0fffffff)
        row = model.run_case(0xffff, {0x0900c004: 0, 0x1f8a4: 0}, 0, 0,
                             driver_override=driver, expected_result=expected,
                             readback=(0, value), readback_address=args.address)
        assert row['loaded_flag'] == 0
        assert [e['value'] for e in row['events'] if e.get('stub_svc') == '0x7b'] == [hex(value)]
        cases += 1
    for first, second, read_result in ((0xffff0001, 0, None),
                                       (0, 0xffff0002, None),
                                       (0, 0, 0xffff0007)):
        expected = first or second or read_result
        row = model.run_case(0xffff, {0x0900c004: first, 0x1f8a4: second},
                             0, 0, driver_override=driver,
                             expected_result=expected,
                             expected_smn_addresses=(['0x900c004'] if first else
                                                     ['0x900c004', '0x1f8a4']),
                             readback=((read_result, 0) if read_result is not None else None),
                             readback_address=args.address)
        assert row['loaded_flag'] == 0
        assert len([e for e in row['events'] if e.get('stub_svc') == '0x7b']) == (
            1 if read_result is not None else 0)
        cases += 1
    for context in (0, 7):
        row = model.run_case(context, {0x0900c004: 0, 0x1f8a4: 0}, 0, 0,
                             driver_override=driver)
        assert row['loaded_flag'] == 1
        assert not any(e.get('stub_svc') == '0x7b' for e in row['events'])
        cases += 1
    print(f'{cases} real-instruction reset-readback cases passed')


if __name__ == '__main__':
    main()
