#!/usr/bin/env python3
"""Pi 5 SPI0 -> Pico bench, with BC250 and CH347 completely disconnected."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import time
import zlib
from capture import Serial
from spi_host import transfer


def script(manifest=None, segment=None):
    if manifest is None:
        rng = random.Random(250)
        values = [0, 0xffffffff, 0xaaaaaaaa, 0x55555555] + [rng.getrandbits(32) for _ in range(252)]
        return [(0x03100000+4*i,v) for i,v in enumerate(values)]
    m = json.loads(Path(manifest).read_text())
    source = Path(m['overlay']['path'])
    if not source.is_absolute(): source = Path(manifest).resolve().parent / source
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != m['overlay']['sha256']:
        raise ValueError('overlay hash mismatch')
    entry = next((x for x in m['overlay']['segments'] if x['name']==segment), None)
    if entry is None:
        raise ValueError('unknown overlay segment')
    blob = data[entry['buffer_offset']:entry['buffer_offset']+entry['length']]
    if hashlib.sha256(blob).hexdigest() != entry['sha256'] or len(blob)%4:
        raise ValueError('segment hash/alignment mismatch')
    return [(0x03000000 | (entry['flash_address']+i), int.from_bytes(blob[i:i+4],'big'))
            for i in range(0,len(blob),4)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--spi',default='/dev/spidev0.0')
    p.add_argument('--speed-hz',type=int,default=250000)
    p.add_argument('--isolated-pi-wiring',action='store_true',
                   help='confirm only Pi/Pico are connected; no BC250/CH347/flash')
    p.add_argument('--overlay-manifest',type=Path)
    p.add_argument('--segment')
    a=p.parse_args()
    if not a.isolated_pi_wiring:
        p.error('--isolated-pi-wiring is required before any SPI device is opened')
    if not 10000<=a.speed_hz<=1000000:
        p.error('bench rate must be 10 kHz..1 MHz')
    if bool(a.overlay_manifest)!=bool(a.segment):
        p.error('supply both --overlay-manifest and --segment')
    model=Path('/proc/device-tree/model')
    if not model.exists() or b'Raspberry Pi 5' not in model.read_bytes():
        p.error('this wiring/runbook is specifically for Pi 5 SPI0')
    pairs=script(a.overlay_manifest,a.segment)
    if not 1<=len(pairs)<=32768: raise ValueError('script length')
    blob=b''.join(struct.pack('<II',*x) for x in pairs)
    serial=Serial(a.port)
    spi=None
    try:
        serial.write(b'status\n')
        if not serial.line(time.monotonic()+5).startswith('BC250-PICO2-BENCH v1 '):
            raise ValueError('expected isolated bench firmware, not passive/active firmware')
        serial.write(f'load {len(pairs)} {zlib.crc32(blob):08x}\n'.encode())
        if serial.line(time.monotonic()+5)!=f'LOAD {len(pairs)}':
            raise ValueError('load not accepted')
        serial.write(blob,timeout=30)
        loaded=serial.line(time.monotonic()+10)
        if not loaded.startswith(f'LOADED {len(pairs)} '): raise ValueError(loaded)
        spi=os.open(a.spi,os.O_RDWR)
        fcntl.ioctl(spi,0x40016b01,struct.pack('B',0))  # mode 0
        fcntl.ioctl(spi,0x40016b03,struct.pack('B',8))
        fcntl.ioctl(spi,0x40046b04,struct.pack('I',a.speed_hz))
        serial.write(b'bench-isolated 120000\n')
        armed=serial.line(time.monotonic()+5)
        if not armed.startswith('ARMED ISOLATED-BENCH '): raise ValueError(armed)
        bad=[]
        for i,(command,wanted) in enumerate(pairs):
            got=transfer(spi,command,a.speed_hz)
            if got!=wanted: bad.append(dict(index=i,command=f'{command:08x}',
                                           expected=f'{wanted:08x}',actual=f'{got:08x}'))
        line=serial.line(time.monotonic()+10)
        fields=line.split()
        if len(fields)!=5 or fields[0]!='RESULT': raise ValueError(line)
        n,mismatches,flags=map(int,fields[1:4])
        if n!=len(pairs): raise ValueError('result count mismatch')
        observed=serial.read(n*4,time.monotonic()+30)
        if zlib.crc32(observed)!=int(fields[4],16): raise ValueError('result CRC')
        if serial.read(6,time.monotonic()+5)!=b'\nDONE\n': raise ValueError('trailer')
        actual=list(struct.unpack(f'<{n}I',observed))
        counted=sum(x!=y[0] for x,y in zip(actual,pairs))
        if counted!=mismatches: raise ValueError('firmware command-check disagreement')
        report=dict(transactions=n,speed_hz=a.speed_hz,command_mismatches=mismatches,
                    response_mismatches=len(bad),first_response_mismatches=bad[:8],
                    flags=flags,passed=not(mismatches or bad or flags),
                    board_connected=False,flash_written=False)
        print(json.dumps(report,indent=2))
        if not report['passed']: raise SystemExit(1)
    finally:
        if spi is not None: os.close(spi)
        try: serial.write(b'x\n',timeout=1)
        except (OSError,TimeoutError): pass
        serial.close()


if __name__=='__main__': main()
