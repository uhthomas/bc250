#!/usr/bin/env python3
"""Execute the real PSP type-13 post-load path with the RAM-only status guard.

Register services and TMR mapping are explicit fixtures. This checks control
flow and error propagation, not whether the BC250 accepts either physical write.
"""
import argparse
import importlib.util
from pathlib import Path


def load_postload_model(path):
    spec = importlib.util.spec_from_file_location('bc250_postload_model', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--model', type=Path, default=Path(__file__).with_name('postload_model.py'))
    args = parser.parse_args()
    model = load_postload_model(args.model)
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    patched_driver = rom[0x984f00:0x984f00+0x1a770]
    cases = 0
    for context in (0xffff, 0, 7):
        for first, second in ((0, 0), (0xffff0000, 0), (0, 0xffff0001)):
            for mapping, auxiliary in ((0, 0), (0xffff0007, 0), (0xffff0007, 1)):
                fail_first = context == 0xffff and first != 0
                failed = fail_first or second != 0
                result = (first if fail_first else second) if failed else (
                    0 if auxiliary else mapping)
                expected_addresses = (['0x900c004'] if fail_first else
                                      (['0x900c004', '0x1f8a4'] if context == 0xffff
                                       else ['0x1f8a4']))
                row = model.run_case(
                    context, {0x0900c004: first, 0x1f8a4: second}, mapping,
                    auxiliary, driver_override=patched_driver,
                    expected_result=result,
                    expected_smn_addresses=expected_addresses)
                assert row['loaded_flag'] == (0 if failed else 1), row
                if failed:
                    assert not any('stub' in event for event in row['events']), row
                cases += 1
    print(f'{cases} real-instruction post-load status cases passed')


if __name__ == '__main__':
    main()
