#!/usr/bin/env python3
"""Exercise full-command-guarded PATCH replies on an isolated Pi 5 bench."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import re
import struct
import time
import zlib

from capture import Serial
from spi_host import transfer, transfer_many


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--spi', default='/dev/spidev0.0')
    parser.add_argument('--speed-hz', type=int, default=1000000)
    parser.add_argument('--transactions', type=int, default=128)
    parser.add_argument('--batch-size', type=int, default=1,
                        help='SPI reads per ioctl; >1 toggles CE0 between transfers')
    parser.add_argument('--route-pattern', choices=('mixed', 'all-pass', 'all-patch'),
                        default='mixed', help='which preselected route words to send')
    parser.add_argument('--gap-us', type=int, default=0,
                        help='extra host delay after each SPI ioctl, for diagnosis')
    parser.add_argument('--peek-before-each', action='store_true',
                        help='read output pad and PIO state while CS is idle before each transfer')
    parser.add_argument('--output-gpio', type=int, choices=(7,), default=7,
                        help='unconnected Pico GPIO used as simulated flash CS; must match firmware')
    parser.add_argument('--corrupt-command-index', type=int,
                        help='isolated negative control: flip one address bit on this SPI command')
    parser.add_argument('--isolated-pi-wiring', action='store_true',
                        help='confirm only Pi/Pico are connected; GP6, GP7, BC250, CH347, and flash are disconnected')
    args = parser.parse_args()
    if not args.isolated_pi_wiring:
        parser.error('--isolated-pi-wiring is required before any SPI device is opened')
    if not 10000 <= args.speed_hz <= 40000000:
        parser.error('bench rate must be 10 kHz..40 MHz')
    if not 8 <= args.transactions <= 1024:
        parser.error('transaction count must be 8..1024')
    if not 1 <= args.batch_size <= 32:
        parser.error('batch size must be 1..32')
    if not 0 <= args.gap_us <= 10000:
        parser.error('extra gap must be 0..10000 microseconds')
    if (args.corrupt_command_index is not None and
            not 0 <= args.corrupt_command_index < args.transactions):
        parser.error('--corrupt-command-index must be a transaction index')
    if args.peek_before_each and args.batch_size != 1:
        parser.error('--peek-before-each requires --batch-size 1')
    model = Path('/proc/device-tree/model')
    if not model.exists() or b'Raspberry Pi 5' not in model.read_bytes():
        parser.error('this wiring/runbook is specifically for Pi 5 SPI0')

    rng = random.Random(250)
    replies = [0, 0xffffffff, 0xaaaaaaaa, 0x55555555]
    replies += [rng.getrandbits(32) for _ in range(args.transactions - len(replies))]
    routes = ([int(index % 4 != 3) for index in range(args.transactions)]
              if args.route_pattern == 'mixed' else
              [int(args.route_pattern == 'all-patch')] * args.transactions)
    if (args.corrupt_command_index is not None and
            (args.corrupt_command_index != args.transactions - 1 or
             routes[-1] != 1)):
        parser.error('negative control must corrupt the final PATCH row')
    commands = [0x03000000 | (0x100000 + 4 * i)
                for i in range(args.transactions)]
    transmitted_commands = commands.copy()
    if args.corrupt_command_index is not None:
        transmitted_commands[args.corrupt_command_index] ^= 1
    words = [word for route, command, reply in zip(routes, commands, replies)
             for word in (route, command, reply)]
    blob = struct.pack(f'<{len(words)}I', *words)
    serial = Serial(args.port)
    spi = None
    try:
        serial.write(b'\nstatus\n')
        deadline = time.monotonic() + 5
        for _ in range(10):
            status = serial.line(deadline)
            if status not in ('', 'ERROR status; load N CRC32; select-isolated TIMEOUT_MS'):
                break
        if (not status.startswith('BC250-PICO2-FAST-GUARD v7 ') or
                'clock_hz=340000000' not in status or
                'outputs=OFF-UNTIL-RUN' not in status or
                f'GP{args.output_gpio}=ISOLATED-OUTPUT' not in status or
                'board_arm=UNAVAILABLE' not in status):
            raise ValueError('wrong Pico firmware or clock: ' + status)
        serial.write(f'load {len(replies)} {zlib.crc32(blob):08x}\n'.encode())
        if serial.line(time.monotonic() + 5) != f'LOAD {len(replies)}':
            raise ValueError('load not accepted')
        serial.write(blob, timeout=30)
        loaded = serial.line(time.monotonic() + 10)
        if loaded != f'LOADED {len(replies)} crc={zlib.crc32(blob):08x}':
            raise ValueError(loaded)

        spi = os.open(args.spi, os.O_RDWR)
        fcntl.ioctl(spi, 0x40016b01, struct.pack('B', 0))
        fcntl.ioctl(spi, 0x40016b03, struct.pack('B', 8))
        fcntl.ioctl(spi, 0x40046b04, struct.pack('I', args.speed_hz))
        serial.write(b'select-isolated 120000\n')
        armed = serial.line(time.monotonic() + 5)
        if (not armed.startswith(f'ARMED FAST-GUARD rows={len(replies)} ') or
                'clock_hz=340000000' not in armed):
            raise ValueError(armed)
        errors = []
        peek_errors = []
        last_peeks = []
        for start in range(0, len(transmitted_commands), args.batch_size):
            end = min(start + args.batch_size, len(transmitted_commands))
            chunk = transmitted_commands[start:end]
            if args.peek_before_each:
                serial.write(b'peek\n')
                peek = serial.line(time.monotonic() + 5)
                peek_match = re.fullmatch(
                    r'PEEK cs=([01]) sclk=([01]) pad=([01]) pio_out=([01]) '
                    r'pio_oe=([01]) pc=(\d+) tx_level=(\d+) fdebug=([0-9a-f]{8}) '
                    r'io_status=([0-9a-f]{8}) io_ctrl=([0-9a-f]{8}) '
                    r'pad_ctrl=([0-9a-f]{8})', peek)
                if peek_match is None:
                    raise ValueError(peek)
                values = [int(peek_match.group(i)) for i in range(1, 8)]
                io_status = int(peek_match.group(9), 16)
                io_ctrl = int(peek_match.group(10), 16)
                pad_ctrl = int(peek_match.group(11), 16)
                record = dict(index=start, wanted=routes[start],
                              cs=values[0], sclk=values[1], pad=values[2],
                              pio_out=values[3], pio_oe=values[4],
                              pc=values[5], tx_level=values[6],
                              fdebug=peek_match.group(8),
                              io_status=f'{io_status:08x}',
                              io_ctrl=f'{io_ctrl:08x}',
                              pad_ctrl=f'{pad_ctrl:08x}',
                              out_to_pad=(io_status >> 9) & 1,
                              oe_to_pad=(io_status >> 13) & 1,
                              in_from_pad=(io_status >> 17) & 1,
                              function=io_ctrl & 31,
                              out_override=(io_ctrl >> 12) & 3,
                              oe_override=(io_ctrl >> 14) & 3,
                              pad_isolated=(pad_ctrl >> 8) & 1,
                              pad_output_disabled=(pad_ctrl >> 7) & 1,
                              pad_input_enabled=(pad_ctrl >> 6) & 1,
                              pad_drive_setting=(pad_ctrl >> 4) & 3,
                              pad_pull_up=(pad_ctrl >> 3) & 1,
                              pad_pull_down=(pad_ctrl >> 2) & 1)
                last_peeks.append(record)
                if len(last_peeks) > 8:
                    last_peeks.pop(0)
                if (record['cs'] != 1 or record['sclk'] != 0 or
                        record['pad'] != record['wanted'] or
                        record['pio_out'] != record['wanted'] or
                        record['pio_oe'] != 1 or
                        record['out_to_pad'] != record['wanted'] or
                        record['oe_to_pad'] != 1 or
                        record['in_from_pad'] != record['wanted'] or
                        record['function'] != 6 or
                        record['out_override'] != 0 or
                        record['oe_override'] != 0 or
                        record['pad_isolated'] != 0 or
                        record['pad_output_disabled'] != 0 or
                        record['pad_input_enabled'] != 1):
                    peek_errors.append(record)
            got_words = ([transfer(spi, chunk[0], args.speed_hz)]
                         if len(chunk) == 1 else transfer_many(spi, chunk, args.speed_hz))
            for index, got in enumerate(got_words, start):
                if (routes[index] and index != args.corrupt_command_index and
                        got != replies[index]):
                    errors.append(dict(index=index, command=f'{commands[index]:08x}',
                                       expected=f'{replies[index]:08x}', actual=f'{got:08x}'))
            if args.gap_us:
                time.sleep(args.gap_us / 1000000)
        serial.write(b'done\n')
        result = serial.line(time.monotonic() + 5)
        match = re.fullmatch(
            r'RESULT (\d+) reply_dma_complete=([01]) select_dma_complete=([01]) '
            r'command_dma_complete=([01]) first_errors=(\d+) second_errors=(\d+) '
            r'bad_rows=(\d+) command_errors=(\d+) fault_irq=([01]) '
            r'miso_pio_oe=([01]) flash_cs_pad=([01]) outputs=OFF', result)
        if match is None or int(match.group(1)) != len(replies):
            raise ValueError(result)
        reply_dma_complete = match.group(2) == '1'
        select_dma_complete = match.group(3) == '1'
        command_dma_complete = match.group(4) == '1'
        first_route_errors = int(match.group(5))
        second_route_errors = int(match.group(6))
        bad_route_rows = int(match.group(7))
        command_errors = int(match.group(8))
        fault_irq = match.group(9) == '1'
        miso_pio_oe = int(match.group(10))
        flash_cs_pad = int(match.group(11))
        route_details = []
        for _ in range(min(bad_route_rows, 16) if select_dma_complete else 0):
            detail = serial.line(time.monotonic() + 5)
            detail_match = re.fullmatch(
                r'BAD (\d+) wanted=([01]) first=([01]) second=([01])', detail)
            if detail_match is None:
                raise ValueError(detail)
            index = int(detail_match.group(1))
            wanted = int(detail_match.group(2))
            first = int(detail_match.group(3))
            second = int(detail_match.group(4))
            if (index >= len(routes) or wanted != routes[index] or
                    (route_details and index <= route_details[-1]['index']) or
                    (first == wanted and second == wanted)):
                raise ValueError('inconsistent route detail: ' + detail)
            route_details.append(dict(index=index, wanted=wanted,
                                      first=first, second=second))
        command_details = []
        for _ in range(min(command_errors, 16) if command_dma_complete else 0):
            detail = serial.line(time.monotonic() + 5)
            detail_match = re.fullmatch(
                r'BADCMD (\d+) expected=([0-9a-f]{8}) observed=([0-9a-f]{8})',
                detail)
            if detail_match is None:
                raise ValueError(detail)
            index = int(detail_match.group(1))
            expected = int(detail_match.group(2), 16)
            observed = int(detail_match.group(3), 16)
            if (index >= len(commands) or expected != commands[index] or
                    observed == expected or observed != transmitted_commands[index] or
                    (command_details and index <= command_details[-1]['index'])):
                raise ValueError('inconsistent command detail: ' + detail)
            command_details.append(dict(index=index, expected=f'{expected:08x}',
                                        observed=f'{observed:08x}'))
        if serial.line(time.monotonic() + 5) != 'END':
            raise ValueError('missing diagnostic end marker')
        expected_command_errors = int(args.corrupt_command_index is not None)
        command_check_passed = (command_dma_complete and
                                command_errors == expected_command_errors and
                                (expected_command_errors == 0 or
                                 (len(command_details) == 1 and
                                  command_details[0]['index'] == args.corrupt_command_index)))
        report = dict(transactions=len(replies), requested_speed_hz=args.speed_hz,
                      batch_size=args.batch_size, route_pattern=args.route_pattern,
                      extra_gap_us=args.gap_us,
                      patch_rows=sum(routes), pass_rows=len(routes)-sum(routes),
                      patch_response_mismatches=len(errors), first_errors=errors[:8],
                      idle_peeks_checked=len(commands) if args.peek_before_each else 0,
                      idle_peek_mismatches=len(peek_errors),
                      first_idle_peek_errors=peek_errors[:8], last_idle_peeks=last_peeks,
                      reply_dma_complete=reply_dma_complete,
                      select_dma_complete=select_dma_complete,
                      command_dma_complete=command_dma_complete,
                      command_errors=command_errors,
                      fault_irq=fault_irq,
                      miso_pio_oe_after_run=miso_pio_oe,
                      flash_cs_pad_after_run=flash_cs_pad,
                      first_command_details=command_details,
                      corrupt_command_index=args.corrupt_command_index,
                      command_check_passed=command_check_passed,
                      first_route_errors=first_route_errors,
                      second_route_errors=second_route_errors,
                      bad_route_rows=bad_route_rows,
                      first_route_details=route_details,
                      output_gpio=args.output_gpio, output_pad_sampled=True,
                      original_flash_connected=False, board_connected=False,
                      board_flash_written=False, speed_physically_measured=False,
                      passed=(not errors and not peek_errors and reply_dma_complete and
                              select_dma_complete and command_check_passed and
                              not bad_route_rows and
                              miso_pio_oe == 0 and flash_cs_pad == 1 and
                              fault_irq == (args.corrupt_command_index is not None)),
                      command_check_timing='PIO before PATCH MISO output')
        print(json.dumps(report, indent=2))
        if not report['passed']:
            raise SystemExit(1)
    finally:
        if spi is not None:
            os.close(spi)
        serial.close()


if __name__ == '__main__':
    main()
