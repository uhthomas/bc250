#!/usr/bin/env python3
"""Exercise the 200 MHz reply engine with Pi 5 SPI0, completely off the BC250."""
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
from spi_host import transfer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--spi', default='/dev/spidev0.0')
    parser.add_argument('--speed-hz', type=int, default=1000000)
    parser.add_argument('--transactions', type=int, default=128)
    parser.add_argument('--isolated-pi-wiring', action='store_true',
                        help='confirm only Pi/Pico are connected; no BC250, CH347, or flash')
    args = parser.parse_args()
    if not args.isolated_pi_wiring:
        parser.error('--isolated-pi-wiring is required before any SPI device is opened')
    if not 10000 <= args.speed_hz <= 40000000:
        parser.error('bench rate must be 10 kHz..40 MHz')
    if not 8 <= args.transactions <= 1024:
        parser.error('transaction count must be 8..1024')
    model = Path('/proc/device-tree/model')
    if not model.exists() or b'Raspberry Pi 5' not in model.read_bytes():
        parser.error('this wiring/runbook is specifically for Pi 5 SPI0')

    rng = random.Random(250)
    replies = [0, 0xffffffff, 0xaaaaaaaa, 0x55555555]
    replies += [rng.getrandbits(32) for _ in range(args.transactions - len(replies))]
    commands = [0x03000000 | (0x100000 + 4 * i)
                for i in range(args.transactions)]
    blob = struct.pack(f'<{len(replies)}I', *replies)
    serial = Serial(args.port)
    spi = None
    try:
        serial.write(b'\nstatus\n')
        deadline = time.monotonic() + 5
        for _ in range(10):
            status = serial.line(deadline)
            if status not in ('', 'ERROR status; load N CRC32; bench-isolated TIMEOUT_MS'):
                break
        if (not status.startswith('BC250-PICO2-FAST-BENCH v1 ') or
                'clock_hz=200000000' not in status or
                'outputs=OFF-UNTIL-RUN' not in status or 'GP6=INPUT' not in status):
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
        serial.write(b'bench-isolated 120000\n')
        armed = serial.line(time.monotonic() + 5)
        if (not armed.startswith(f'ARMED FAST-BENCH replies={len(replies)} ') or
                'clock_hz=200000000' not in armed):
            raise ValueError(armed)
        errors = []
        for index, (command, wanted) in enumerate(zip(commands, replies)):
            got = transfer(spi, command, args.speed_hz)
            if got != wanted:
                errors.append(dict(index=index, command=f'{command:08x}',
                                   expected=f'{wanted:08x}', actual=f'{got:08x}'))
        serial.write(b'done\n')
        result = serial.line(time.monotonic() + 5)
        match = re.fullmatch(r'RESULT (\d+) dma_complete=([01]) outputs=OFF', result)
        if match is None or int(match.group(1)) != len(replies):
            raise ValueError(result)
        dma_complete = match.group(2) == '1'
        report = dict(transactions=len(replies), requested_speed_hz=args.speed_hz,
                      response_mismatches=len(errors), first_errors=errors[:8],
                      dma_complete=dma_complete, board_connected=False,
                      board_flash_written=False, passed=not errors and dma_complete,
                      speed_physically_measured=False)
        print(json.dumps(report, indent=2))
        if errors or not dma_complete:
            raise SystemExit(1)
    finally:
        if spi is not None:
            os.close(spi)
        serial.close()


if __name__ == '__main__':
    main()
