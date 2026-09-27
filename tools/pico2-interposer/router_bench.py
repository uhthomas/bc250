#!/usr/bin/env python3
"""Run the signed-word router replay with only Pi SPI0 and Pico connected.

GP6 must remain disconnected. Without an original flash the pass-through rows
have no driven MISO value, so only their state/length is checked on this bench.
Original-flash data and CS exclusion are checked in the separate digital model.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import struct
import time
from spi_host import transfer
from capture import Serial


def short_transfer(fd, payload, speed):
    tx=ctypes.create_string_buffer(payload,len(payload))
    rx=ctypes.create_string_buffer(len(payload))
    descriptor=struct.pack('=QQIIHBBBBBB',ctypes.addressof(tx),ctypes.addressof(rx),
                           len(payload),speed,0,8,0,0,0,0,0)
    fcntl.ioctl(fd,0x40206b00,descriptor)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--spi', default='/dev/spidev0.0')
    p.add_argument('--speed-hz', type=int, default=250000)
    p.add_argument('--isolated-pi-wiring', action='store_true')
    p.add_argument('--wrong-address-after-anchor', action='store_true', help='negative test, fresh reset required')
    args = p.parse_args()
    if not args.isolated_pi_wiring:
        p.error('--isolated-pi-wiring required; BC250/CH347 and GP6 must be disconnected')
    if not 10000 <= args.speed_hz <= 5000000:
        p.error('isolated candidate range is 10 kHz..5 MHz; start at 250 kHz')
    model = Path('/proc/device-tree/model')
    if not model.exists() or b'Raspberry Pi 5' not in model.read_bytes():
        p.error('runner and wiring are specifically for Pi 5 SPI0')
    profile = json.loads(args.profile.read_text())
    rows = profile['rows']
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (profile['schema']!=3 or not profile['seek_anchor'] or
            digest != profile['row_sha256'] or profile['physical_trace'] or profile['board_arm']):
        raise ValueError('expected intact SYNTHETIC isolated profile')
    serial, spi = Serial(args.port), None
    try:
        serial.write(b'status\n')
        status = serial.line(time.monotonic() + 5)
        if not status.startswith('BC250-PICO2-ROUTER v2 '):
            raise ValueError('wrong firmware; expected router candidate')
        fields = dict(x.split('=', 1) for x in status.split()[2:])
        if fields['profile'] != profile['name'] or fields['state'] != '0':
            raise ValueError('profile mismatch or not idle; disconnect target and reset Pico')
        spi = os.open(args.spi, os.O_RDWR)
        fcntl.ioctl(spi, 0x40016b01, struct.pack('B', 0))
        fcntl.ioctl(spi, 0x40016b03, struct.pack('B', 8))
        fcntl.ioctl(spi, 0x40046b04, struct.pack('I', args.speed_hz))
        serial.write(b'arm-isolated\n')
        armed = serial.line(time.monotonic() + 5)
        if not armed.startswith('ARMED ISOLATED-ROUTER '):
            raise ValueError(armed)
        # Unrelated full reads and short commands must remain transparent while
        # seeking. These are read-only opcodes, with no original chip attached.
        short_transfer(spi,b'\x9f',args.speed_hz)
        transfer(spi,0x0300ff00,args.speed_hz)
        short_transfer(spi,b'\x03\x00\x01',args.speed_hz)
        checked = 0
        selected=rows[:3] if args.wrong_address_after_anchor else rows
        for i,row in enumerate(selected):
            wrong=args.wrong_address_after_anchor and i==2
            cmd = row['command'] ^ (4 if wrong else 0)
            got = transfer(spi, cmd, args.speed_hz)
            if row['patch'] and not wrong:
                if got != row['word']:
                    raise ValueError(f'MISO mismatch at {cmd:08x}: wanted {row["word"]:08x}, got {got:08x}')
                checked += 1
        serial.write(b'status\n')
        status = serial.line(time.monotonic() + 5)
        fields = dict(x.split('=', 1) for x in status.split()[2:])
        wanted = '3' if args.wrong_address_after_anchor else '2'
        if fields['state'] != wanted or fields['skipped']!='3':
            raise ValueError(f'expected state={wanted}; {status}')
        print(json.dumps(dict(result='PASS', patched_words_checked=checked,
                              negative_address_test=args.wrong_address_after_anchor,
                              preamble_transactions_skipped=int(fields['skipped']),
                              spi_hz=args.speed_hz, original_flash_connected=False,
                              physical_bc250_test=False), indent=2))
    finally:
        try:
            serial.write(b'cancel\n')
        except (OSError, TimeoutError):
            pass
        serial.close()
        if spi is not None:
            os.close(spi)


if __name__ == '__main__':
    main()
