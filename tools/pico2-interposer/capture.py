#!/usr/bin/env python3
"""Collect/decode input-only Pico 2 CS#/SCLK/MOSI/MISO captures (stdlib only)."""
import argparse
import collections
import json
import os
from pathlib import Path
import select
import statistics
import struct
import termios
import time
import tty
import zlib

HEADER = struct.Struct('<8s6I')
MAGIC = b'BC25RAW1'
MAX_WORDS = 98304


def unpack(blob):
    if len(blob) < HEADER.size:
        raise ValueError('truncated capture header')
    magic, words, clock, divider, skip, flags, crc = HEADER.unpack_from(blob)
    if magic != MAGIC or not 1 <= words <= MAX_WORDS or not clock or not 1 <= divider <= 65535:
        raise ValueError('invalid capture header')
    data = blob[HEADER.size:]
    if len(data) != words * 4:
        raise ValueError('capture length mismatch')
    if zlib.crc32(data) != crc:
        raise ValueError('capture CRC mismatch')
    return dict(words=words, clock_hz=clock, divider=divider,
                sample_hz=clock / divider, skip=skip, flags=flags,
                crc32=f'{crc:08x}'), data


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)


class Serial:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        settings = termios.tcgetattr(self.fd)
        settings[2] |= termios.CLOCAL | termios.CREAD
        settings[4] = settings[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, settings)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.buffer = bytearray()

    def close(self):
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)
        except (OSError, termios.error):
            # USB removal invalidates the terminal. Preserve the original
            # disconnection error instead of hiding it behind cleanup failure.
            pass
        finally:
            os.close(self.fd)

    def write(self, data, timeout=5):
        deadline = time.monotonic() + timeout
        while data:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([], [self.fd], [], left)[1]:
                raise TimeoutError('serial write timed out')
            n = os.write(self.fd, data)
            data = data[n:]

    def read(self, n, deadline):
        while len(self.buffer) < n:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                raise TimeoutError('serial read timed out')
            chunk = os.read(self.fd, max(4096, n - len(self.buffer)))
            if not chunk:
                raise EOFError('Pico USB disconnected')
            self.buffer.extend(chunk)
        out = bytes(self.buffer[:n])
        del self.buffer[:n]
        return out

    def line(self, deadline):
        result = bytearray()
        while len(result) < 1024:
            ch = self.read(1, deadline)
            if ch == b'\n':
                return result.decode('ascii').rstrip('\r')
            result.extend(ch)
        raise ValueError('serial line too long')


def collect(port, output, skip, words, divider, timeout, *, usb_test=False, transfer_timeout=30):
    if not 0 <= skip <= 10000000 or not 1 <= words <= MAX_WORDS:
        raise ValueError('skip/words out of range')
    if not 1 <= divider <= 65535 or not 1 <= timeout <= 120:
        raise ValueError('divider/timeout out of range')
    if usb_test and (skip != 0 or divider != 1):
        raise ValueError('USB self-test requires skip=0 divider=1')
    if Path(output).exists():
        raise FileExistsError(output)
    serial = Serial(port)
    capture_pending = False
    try:
        # Complete any partial command left by an interrupted client. A previous
        # cancellation can leave one invalid-command reply ahead of our status.
        serial.write(b'\nstatus\n')
        status_deadline = time.monotonic() + 5
        for _ in range(10):
            banner = serial.line(status_deadline)
            if banner not in ('', 'ERROR invalid command or limits'):
                break
        if not banner.startswith('BC250-PICO2-PASSIVE v1 ') or 'outputs=OFF' not in banner:
            raise ValueError('device does not identify as the input-only firmware: ' + banner)
        if usb_test and 'usb_test=1' not in banner:
            raise ValueError('Pico needs passive firmware v0.2 or later for the USB self-test')
        serial.line(time.monotonic() + 5)  # help line
        request = f'usb-test {words}\n' if usb_test else f'capture {skip} {words} {divider} {timeout * 1000}\n'
        serial.write(request.encode())
        capture_pending = not usb_test
        deadline = time.monotonic() + timeout + 10
        armed = serial.line(deadline)
        if armed.startswith('ERROR '):
            capture_pending = False
        if not armed.startswith('ARMED '):
            raise ValueError(armed)
        print(armed + (' — testing USB only' if usb_test else ' — start the test source / normal BC250 boot now'), flush=True)
        line = serial.line(deadline)
        if line.startswith(('DATA ', 'ERROR ')):
            capture_pending = False
        if not line.startswith('DATA '):
            raise ValueError(line)
        length = int(line[5:])
        if length != HEADER.size + words * 4:
            raise ValueError('unexpected DATA length')
        # Transfer timeout is separate from the trigger timeout.
        try:
            blob = serial.read(length, time.monotonic() + transfer_timeout)
        except TimeoutError as error:
            partial = Path(str(output) + '.partial')
            private_write(partial, bytes(serial.buffer))
            raise TimeoutError(f'USB transfer stopped after {len(serial.buffer)}/{length} bytes; saved {partial}') from error
        if serial.read(6, time.monotonic() + 5) != b'\nDONE\n':
            raise ValueError('missing capture trailer')
        meta, data = unpack(blob)
        if (meta['skip'], meta['words'], meta['divider']) != (skip, words, divider):
            raise ValueError('capture parameters do not match request')
        if usb_test and (meta['flags'] != 0x80000000 or data != (bytes(range(256))*((len(data)+255)//256))[:len(data)]):
            raise ValueError('USB self-test flag/pattern mismatch')
        if not usb_test and meta['flags'] & 0x80000000:
            raise ValueError('synthetic USB test is not a SPI capture')
        private_write(output, blob)
        print(json.dumps(dict(output=str(output), **meta), indent=2))
    finally:
        # Stop an outstanding arm after host cancellation. 'x' is never a bus output.
        if capture_pending:
            try:
                serial.write(b'x\n', timeout=1)
            except (OSError, TimeoutError):
                pass
        serial.close()


def byte_values(bits, index):
    return bytes(sum(bits[i + j][index] << (7 - j) for j in range(8))
                 for i in range(0, len(bits) - 7, 8))


def decode(blob, rom=None):
    meta, data = unpack(blob)
    samples = [n for byte in data for n in (byte & 15, byte >> 4)]
    transactions = []
    periods, half_periods = [], []
    edge_ambiguities = 0
    current = None
    previous = samples[0]
    if not previous & 1:
        current = dict(start_sample=0, leading_partial=True, idle_clock=None,
                       cs_high_before_samples=None, bits=[], rises=[], edges=[])

    def finish(end, trailing=False):
        nonlocal current
        if current is None:
            return
        bits = current.pop('bits')
        rises = current.pop('rises')
        edges = current.pop('edges')
        periods.extend(b - a for a, b in zip(rises, rises[1:]))
        half_periods.extend(b - a for a, b in zip(edges, edges[1:]))
        current.update(end_sample=end, trailing_partial=trailing, clocks=len(bits))
        current['complete'] = not current['leading_partial'] and not trailing
        # These are sampled edge separations, not analogue timing guarantees.
        # An interval N samples wide can be almost one sample shorter on wire.
        current.update(
            cs_setup_samples=(edges[0]-current['start_sample']
                              if edges and not current['leading_partial'] else None),
            cs_hold_samples=end-edges[-1] if edges and not trailing else None,
            min_period_samples=min((b-a for a,b in zip(rises,rises[1:])),default=None),
            min_half_period_samples=min((b-a for a,b in zip(edges,edges[1:])),default=None))
        tx, rx = byte_values(bits, 0), byte_values(bits, 1)
        current['mosi_hex'], current['miso_hex'] = tx.hex(), rx.hex()
        if len(tx) >= 4 and tx[0] == 3:
            address = int.from_bytes(tx[1:4], 'big')
            current.update(opcode=3, address=address, data_hex=rx[4:].hex())
            if rom is not None and current['complete'] and len(bits) % 8 == 0:
                end_addr = address + len(rx) - 4
                current['rom_match'] = end_addr <= len(rom) and rx[4:] == rom[address:end_addr]
        elif tx:
            current['opcode'] = tx[0]
        transactions.append(current)
        current = None

    for i, sample in enumerate(samples[1:], 1):
        cs, old_cs = sample & 1, previous & 1
        if cs != old_cs and (sample ^ previous) & 2:
            edge_ambiguities += 1
        if old_cs and not cs:
            current = dict(start_sample=i, leading_partial=False,
                           idle_clock=(previous >> 1) & 1,
                           cs_high_before_samples=i-transactions[-1]['end_sample'] if transactions else None,
                           bits=[], rises=[], edges=[])
        if not old_cs and cs:
            finish(i)
        if current is not None and not cs:
            if (sample ^ previous) & 2:
                current['edges'].append(i)
            if sample & 2 and not previous & 2:
                if (sample ^ previous) & 12:
                    edge_ambiguities += 1
                current['bits'].append(((sample >> 2) & 1, (sample >> 3) & 1))
                current['rises'].append(i)
        previous = sample
    finish(len(samples), trailing=True)
    complete = [t for t in transactions if t['complete']]
    reads = [t for t in complete if t.get('opcode') == 3 and t['clocks'] >= 32 and t['clocks'] % 8 == 0]
    warnings = []
    if meta['flags'] & 0x7fffffff:
        warnings.append('DMA/PIO flagged capture discontinuity; timing/read counts cannot be trusted')
    if meta['flags'] & 0x80000000:
        warnings.append('synthetic USB transport self-test; not a SPI capture')
    if not periods:
        warnings.append('no measurable SPI clocks')
    elif min(periods) < 4 or (half_periods and min(half_periods) < 2):
        warnings.append('fewer than 4 samples per clock or 2 per half-cycle; insufficient timing margin')
    malformed = sum(t['clocks'] % 8 != 0 for t in complete)
    if malformed:
        warnings.append('complete transactions contain a non-byte clock count; inspect raw edges')
    if edge_ambiguities:
        warnings.append('CS/data changed in the same sample as a rising clock; setup timing is unresolved')
    mismatches = [t for t in reads if t.get('rom_match') is False]
    if mismatches:
        warnings.append('SPI data differs from supplied ROM; inspect before choosing switch triggers')
    summary = dict(**meta, duration_ms=len(samples) / meta['sample_hz'] * 1000,
                   complete_transactions=len(complete), partial_transactions=len(transactions)-len(complete),
                   read03_transactions=len(reads), read03_four_byte=sum(t['clocks']==64 for t in reads),
                   malformed_transactions=malformed, rom_compared=rom is not None,
                   sampled_edge_ambiguities=edge_ambiguities,
                   rom_mismatches=len(mismatches), warnings=warnings,
                   opcode_counts=dict(collections.Counter(f"0x{t['opcode']:02x}" for t in complete if 'opcode' in t)),
                   type50_reads=sum(0x9dad00 <= t['address'] < 0x9dbad0 for t in reads),
                   type51_reads=sum(0x9dbb00 <= t['address'] < 0x9dc240 for t in reads))
    if periods:
        summary.update(median_clock_hz=meta['sample_hz']/statistics.median(periods),
                       # Quantized periods alternate between adjacent sample
                       # counts. Their mean preserves fractional clock ratios;
                       # the median alone would label a ~33 MHz clock 30 MHz.
                       mean_clock_hz=meta['sample_hz']/statistics.mean(periods),
                       period_samples_histogram=dict(sorted(collections.Counter(periods).items())),
                       min_samples_per_clock=min(periods),
                       min_samples_per_half_clock=min(half_periods) if half_periods else None)
    return dict(summary=summary, transactions=transactions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect')
    c.add_argument('--port', required=True)
    c.add_argument('--output', type=Path, required=True)
    c.add_argument('--skip', type=int, default=0)
    c.add_argument('--words', type=int, default=MAX_WORDS)
    c.add_argument('--divider', type=int, default=1)
    c.add_argument('--timeout', type=int, default=60)
    u = sub.add_parser('usb-test', help='verify binary USB transfer without capturing SPI')
    u.add_argument('--port', required=True)
    u.add_argument('--output', type=Path, required=True)
    u.add_argument('--words', type=int, default=MAX_WORDS)
    d = sub.add_parser('decode')
    d.add_argument('capture', type=Path)
    d.add_argument('--rom', type=Path)
    d.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'usb-test':
        collect(args.port,args.output,0,args.words,1,10,usb_test=True)
    elif args.command == 'collect':
        collect(args.port, args.output, args.skip, args.words, args.divider, args.timeout)
    else:
        result = decode(args.capture.read_bytes(), args.rom.read_bytes() if args.rom else None)
        private_write(args.output, (json.dumps(result, indent=2)+'\n').encode())
        print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
