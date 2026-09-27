#!/usr/bin/env python3
"""Collect the full 32-bit command stream from the read-only Pico relay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import zlib

from capture import Serial, private_write

MAX_CHUNK_RECORDS = 256


def parse_chunk_header(line):
    try:
        marker, count, crc = line.split()
        n = int(count)
        wanted_crc = int(crc, 16)
    except ValueError as exc:
        raise ValueError('invalid CHNK header: ' + line) from exc
    if marker != 'CHNK' or not 1 <= n <= MAX_CHUNK_RECORDS or not 0 <= wanted_crc <= 0xffffffff:
        raise ValueError('invalid CHNK values: ' + line)
    return n, wanted_crc


def parse_done(line, received_records, received_commands):
    if not line.startswith('DONE '):
        raise ValueError('missing DONE trailer: ' + line)
    try:
        fields = dict(item.split('=', 1) for item in line[5:].split())
        seen, sent, records, overflow, stall, cancelled = (
            int(fields[k]) for k in ('seen', 'sent', 'records', 'overflow', 'stall', 'cancelled'))
    except (KeyError, ValueError) as exc:
        raise ValueError('invalid DONE trailer: ' + line) from exc
    if (min(seen, sent, overflow, stall, cancelled) < 0 or
            sent != received_commands or records != received_records or
            seen != sent + overflow or
            stall not in (0, 1) or cancelled not in (0, 1)):
        raise ValueError('inconsistent DONE counters: ' + line)
    return dict(seen=seen, sent=sent, records=records, overflow=overflow, stall=stall,
                cancelled=bool(cancelled), usable_for_ordering=not (overflow or stall or cancelled))


def collect(port, prefix, timeout, usb_test_records=0):
    if not 1 <= timeout <= 120:
        raise ValueError('timeout must be 1..120 seconds')
    if not 0 <= usb_test_records <= 32768:
        raise ValueError('USB test records must be 1..32768')
    binary = Path(str(prefix) + '.bin')
    metadata = Path(str(prefix) + '.json')
    partial = Path(str(prefix) + '.bin.partial')
    if any(p.exists() for p in (binary, metadata, partial)):
        raise FileExistsError(prefix)
    serial = Serial(port)
    pending = False
    try:
        serial.write(b'\nstatus\n')
        deadline = time.monotonic() + 5
        banner = ''
        for _ in range(10):
            banner = serial.line(deadline)
            if banner.startswith('BC250-PICO2-CS-PASS-STREAM v2 '):
                break
        required_state = 'armed=0 gate=0' if usb_test_records else 'armed=1 gate=1'
        if (not banner.startswith('BC250-PICO2-CS-PASS-STREAM v2 ') or
                required_state not in banner or
                'bios_write=UNAVAILABLE' not in banner):
            raise ValueError('requires CS-PASS-STREAM image in correct state: ' + banner)
        command = f'usb-test {usb_test_records}\n' if usb_test_records else f'stream-pass {timeout * 1000}\n'
        serial.write(command.encode())
        pending = True
        armed = serial.line(time.monotonic() + 5)
        wanted_output = 'outputs=OFF' if usb_test_records else 'outputs=CS_ONLY'
        if not armed.startswith('ARMED STREAM-PASS ') or wanted_output not in armed:
            raise ValueError(armed)
        print(armed + ('' if usb_test_records else ' — reboot the BC250 now'), flush=True)
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        received_records = 0
        received_commands = 0
        digest = hashlib.sha256()
        chunk_count = 0
        with os.fdopen(fd, 'wb') as out:
            overall_deadline = time.monotonic() + timeout + 35
            while True:
                line = serial.line(overall_deadline)
                if line.startswith('DONE '):
                    counters = parse_done(line, received_records, received_commands)
                    pending = False
                    break
                count, wanted_crc = parse_chunk_header(line)
                payload = serial.read(count * 8, overall_deadline)
                if zlib.crc32(payload) != wanted_crc:
                    raise ValueError(f'CRC mismatch on chunk {chunk_count}')
                if serial.read(1, overall_deadline) != b'\n':
                    raise ValueError('missing chunk terminator')
                for _, run_count in struct.iter_unpack('<II', payload):
                    if run_count == 0:
                        raise ValueError('zero-length RLE run')
                    received_commands += run_count
                out.write(payload)
                digest.update(payload)
                received_records += count
                chunk_count += 1
        os.replace(partial, binary)
        if usb_test_records:
            expected = b''.join(struct.pack('<II', 0x03000000 + 4 * i, 1)
                                for i in range(usb_test_records))
            if (received_records != usb_test_records or
                    digest.digest() != hashlib.sha256(expected).digest()):
                raise ValueError('synthetic USB pattern mismatch')
        result = dict(schema=2, image='CS-PASS-STREAM-v2-RLE',
                      binary=str(binary), binary_sha256=digest.hexdigest(),
                      chunks=chunk_count, clock_hz=200000000,
                      synthetic_usb_test=bool(usb_test_records),
                      board_flash_written=False, pico_flash_written=False,
                      **counters)
        private_write(metadata, (json.dumps(result, indent=2) + '\n').encode())
        print(json.dumps(result, indent=2))
    finally:
        if pending:
            try:
                serial.write(b'x\n', timeout=1)
            except (OSError, TimeoutError):
                pass
        serial.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--timeout', type=int, default=90)
    parser.add_argument('--output-prefix', required=True, type=Path)
    parser.add_argument('--usb-test-records', type=int, default=0)
    args = parser.parse_args()
    collect(args.port, args.output_prefix, args.timeout, args.usb_test_records)


if __name__ == '__main__':
    main()
