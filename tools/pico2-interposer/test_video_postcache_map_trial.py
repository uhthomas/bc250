#!/usr/bin/env python3
"""Execute the pinned PSP post-load hook with the 17 VCN window writes."""

import argparse
import importlib.util
from pathlib import Path
import struct


POWER = 0x1f810
RESET = 0x0900c004
SECOND_RESET = 0x1f8a4
UVD_RESET = 0x20180
UVD_RESET2 = 0x1ff98
CACHE_LOW = 0x2107c
GFX_CONFIG = 0x1f928
TABLE_OFFSET = 0x99df10


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--count', type=int, default=17)
    parser.add_argument('--diagnostic', action='store_true')
    parser.add_argument('--rx-table', action='store_true')
    parser.add_argument('--verify-all', action='store_true')
    parser.add_argument('--verify-cache-windows', action='store_true')
    parser.add_argument('--gfx-readback', action='store_true')
    parser.add_argument('--release-soft-reset', action='store_true')
    parser.add_argument('--release-uvd-soft-reset', action='store_true')
    parser.add_argument('--report-uvd-reset-status', action='store_true')
    parser.add_argument('--report-uvd-reset-before-write', action='store_true')
    parser.add_argument('--report-uvd-reset2-before-write', action='store_true')
    parser.add_argument('--report-uvd-reset-stability', action='store_true')
    parser.add_argument('--report-after-uvd-release', type=lambda s: int(s, 0))
    parser.add_argument('--direct-bo', action='store_true',
                        help='Expect the guarded ordinary-firmware-BO PSP map')
    args = parser.parse_args()
    assert 1 <= args.count <= 17
    verify_count = 16 if args.verify_cache_windows else 17 if args.verify_all else 0
    assert sum((args.verify_all, args.verify_cache_windows, args.gfx_readback,
                args.release_soft_reset, args.release_uvd_soft_reset,
                args.report_uvd_reset_status,
                args.report_uvd_reset_before_write,
                args.report_uvd_reset2_before_write,
                args.report_uvd_reset_stability,
                args.report_after_uvd_release is not None)) <= 1
    assert not verify_count or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.gfx_readback or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.release_soft_reset or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.release_uvd_soft_reset or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.report_uvd_reset_status or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.report_uvd_reset_before_write or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.report_uvd_reset2_before_write or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert not args.report_uvd_reset_stability or (args.rx_table and args.count == 17 and not args.diagnostic)
    assert args.report_after_uvd_release is None or (args.rx_table and args.count == 17 and not args.diagnostic)
    report_mode = (args.report_uvd_reset_status or args.report_uvd_reset_before_write or
                   args.report_uvd_reset2_before_write or
                   args.report_uvd_reset_stability or
                   args.report_after_uvd_release is not None)
    report_target = (args.report_after_uvd_release if args.report_after_uvd_release is not None
                     else UVD_RESET2 if args.report_uvd_reset2_before_write else UVD_RESET)
    report_value = (0 if args.report_uvd_reset_stability else
                    0x6003000 if args.report_after_uvd_release is not None else
                    0x30000 if args.report_uvd_reset2_before_write else 0x80000)
    model = load_module('postload_model')
    builder = load_module('prepare_video_driver_trial')
    direct_bo = load_module('prepare_vcn_psp_bo_fetch_trial') if args.direct_bo else None
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    if args.rx_table:
        addrs = struct.unpack_from('<17I', rom, 0x99cc98)
        vals = struct.unpack_from('<17I', rom, 0x99ceb8)
        table = list(zip(addrs, vals))
    else:
        table = [struct.unpack_from('<II', rom, TABLE_OFFSET + i * 8) for i in range(17)]
    assert tuple(table) == (direct_bo.EXPECTED_BO_MAP if direct_bo else builder.EXPECTED_MAP)
    values = dict(table)
    addresses = [hex(RESET), hex(SECOND_RESET)] + [hex(address) for address, _ in table]
    results = {RESET: 0, SECOND_RESET: 0, UVD_RESET: 0, **dict.fromkeys(values, 0)}
    release_target = (UVD_RESET if (args.release_uvd_soft_reset or report_mode) and
                      not (args.report_uvd_reset_before_write or args.report_uvd_reset2_before_write)
                      else SECOND_RESET
                      if args.release_soft_reset else None)
    release_kwargs = {'extra_write': (release_target, 0)} if release_target else {}
    full_write_addresses = addresses[:2 + args.count] + ([hex(SECOND_RESET)]
                                                         if args.release_soft_reset else
                                                         [hex(UVD_RESET)] if release_target == UVD_RESET else [])
    cases = 0

    row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                         expected_result=0, readbacks={POWER: (0, 0x801)},
                         extra_writes=values,
                         expected_smn_addresses=addresses[:2])
    assert row['loaded_flag'] == 1
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(POWER)]
    cases += 1

    verification_order = ([address for address, _ in reversed(table[:verify_count])]
                          if verify_count else [GFX_CONFIG] if args.gfx_readback else
                          [report_target] if report_mode else
                          [release_target] if release_target else [CACHE_LOW])
    readback_values = {POWER: (0, 0x800)}
    readback_values.update({address: (0, report_value if report_mode else 0
                                      if address == release_target else values[address])
                            for address in verification_order})
    if args.report_uvd_reset_stability:
        readback_values[UVD_RESET] = [(0, 0)] * 128
    row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                         expected_result=(0x70000000 | report_value if report_mode else
                                          0x70000000 | (values[GFX_CONFIG] & 0x0fffffff)
                                          if args.gfx_readback else
                                          0x6d000000 | args.count if args.diagnostic else 0),
                         loaded_before=1,
                         readbacks=readback_values,
                         extra_writes=values,
                         expected_smn_addresses=full_write_addresses,
                         **release_kwargs)
    assert row['loaded_flag'] == 1
    expected_reads = ([hex(POWER)] + [hex(UVD_RESET)] * 128
                      if args.report_uvd_reset_stability else
                      [hex(POWER)] + [hex(a) for a in verification_order])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == expected_reads
    cases += 1

    for index, (address, _) in enumerate(table[:args.count]):
        failed = dict(results)
        failed[address] = 0xffff0007
        row = model.run_case(0xffff, failed, 0, 0, driver_override=driver,
                             expected_result=0x6a000000 | (args.count - index),
                             loaded_before=1,
                             readbacks={POWER: (0, 0x800)},
                             extra_writes=values,
                             expected_smn_addresses=addresses[:3 + index],
                             **release_kwargs)
        assert row['loaded_flag'] == 1
        cases += 1

    for index, address in enumerate(verification_order):
        if args.gfx_readback:
            for value in (0, 0xffffffff):
                diagnostic_readbacks = dict(readback_values)
                diagnostic_readbacks[address] = (0, value)
                row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                                     expected_result=0x70000000 | (value & 0x0fffffff),
                                     loaded_before=1, readbacks=diagnostic_readbacks,
                                     extra_writes=values,
                                     expected_smn_addresses=addresses[:2 + args.count])
                assert row['loaded_flag'] == 1
                cases += 1
            failed_readbacks = dict(readback_values)
            failed_readbacks[address] = (0xffff0009, 0)
            row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                                 expected_result=0xffff0009, loaded_before=1,
                                 readbacks=failed_readbacks, extra_writes=values,
                                 expected_smn_addresses=addresses[:2 + args.count])
            assert row['loaded_flag'] == 1
            cases += 1
            continue
        if release_target or report_mode:
            if report_mode:
                for value in (0, report_value, 0x80008, 0xffffffff):
                    report_readbacks = dict(readback_values)
                    report_readbacks[address] = ([(0, 0)] * 127 + [(0, value)]
                                                 if args.report_uvd_reset_stability else
                                                 (0, value))
                    row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                                         expected_result=0x70000000 | (value & 0x0fffffff),
                                         loaded_before=1, readbacks=report_readbacks,
                                         extra_writes=values,
                                         expected_smn_addresses=full_write_addresses,
                                         **release_kwargs)
                    assert row['loaded_flag'] == 1
                    cases += 1
                failed_readbacks = dict(readback_values)
                failed_readbacks[address] = (0xffff0009, 0)
                row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                                     expected_result=0xffff0009, loaded_before=1,
                                     readbacks=failed_readbacks, extra_writes=values,
                                     expected_smn_addresses=full_write_addresses,
                                     **release_kwargs)
                assert row['loaded_flag'] == 1
                cases += 1
                if args.report_uvd_reset_stability:
                    failed_readbacks[address] = [(0, 0)] * 63 + [(0xffff000a, 0)]
                    row = model.run_case(0xffff, results, 0, 0,
                                         driver_override=driver,
                                         expected_result=0xffff000a,
                                         loaded_before=1,
                                         readbacks=failed_readbacks,
                                         extra_writes=values,
                                         expected_smn_addresses=full_write_addresses,
                                         **release_kwargs)
                    assert row['loaded_flag'] == 1
                    cases += 1
                continue
            for readback, expected in (((0xffff0009, 0), 0xffff0009),
                                       ((0, 0x200d), 0x6b000000)):
                failed_readbacks = dict(readback_values)
                failed_readbacks[address] = readback
                row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                                     expected_result=expected, loaded_before=1,
                                     readbacks=failed_readbacks, extra_writes=values,
                                     expected_smn_addresses=full_write_addresses,
                                     **release_kwargs)
                assert row['loaded_flag'] == 1
                cases += 1
            if release_target:
                failed_release = model.run_case(
                    0xffff, results, 0, 0, driver_override=driver,
                    expected_result=0xffff0010, loaded_before=1,
                    readbacks={POWER: (0, 0x800)}, extra_writes=values,
                    extra_results={(release_target, 0): 0xffff0010},
                    expected_smn_addresses=full_write_addresses, **release_kwargs)
                assert failed_release['loaded_flag'] == 1
                cases += 1
            continue
        for readback, expected in (((0xffff0009, 0), 0xffff0009),
                                   ((0, values[address] ^ 1),
                                    0x6b000000 | (verify_count - index) if verify_count else 0x6b000000)):
            failed_readbacks = dict(readback_values)
            failed_readbacks[address] = readback
            row = model.run_case(0xffff, results, 0, 0, driver_override=driver,
                                 expected_result=expected, loaded_before=1,
                                 readbacks=failed_readbacks,
                                 extra_writes=values,
                                 expected_smn_addresses=full_write_addresses,
                                 **release_kwargs)
            assert row['loaded_flag'] == 1
            assert [event['address'] for event in row['events']
                    if event.get('stub_svc') == '0x7b'] == [hex(POWER)] + [hex(a) for a in verification_order[:index + 1]]
            cases += 1

    for first, second in ((0xffff0001, 0), (0, 0xffff0002)):
        failed = dict(results)
        failed[RESET], failed[SECOND_RESET] = first, second
        expected = first or second
        row = model.run_case(0xffff, failed, 0, 0, driver_override=driver,
                             expected_result=expected,
                             readbacks={POWER: (0, 0x800)}, extra_writes=values,
                             expected_smn_addresses=addresses[:1 if first else 2])
        assert row['loaded_flag'] == 0
        cases += 1

    for context in (0, 7):
        row = model.run_case(context, results, 0, 0, driver_override=driver,
                             extra_writes=values,
                             expected_smn_addresses=[hex(SECOND_RESET)])
        assert row['return'] == '0x0' and row['loaded_flag'] == 1
        cases += 1

    print(f'{cases} native post-cache VCN map cases passed')


if __name__ == '__main__':
    main()
