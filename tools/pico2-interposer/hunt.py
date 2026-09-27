#!/usr/bin/env python3
"""Collect read-only BC250 SPI address hits from passive Pico firmware v0.3."""
import argparse
import json
from pathlib import Path
import time

from capture import Serial, private_write


def parse_hits(header, lines, footer, first, last):
    if not header.startswith('HITS '):
        raise ValueError('missing hit header: ' + header)
    try:
        fields = dict(item.split('=', 1) for item in header[5:].split())
        seen,kept,overflow,stall,cancelled = (int(fields[k]) for k in
            ('seen','kept','overflow','stall','cancelled'))
    except (KeyError, ValueError) as exc:
        raise ValueError('invalid hit header') from exc
    if footer != 'DONEH' or len(lines) != kept or kept > 4096 or seen < kept + overflow:
        raise ValueError('truncated or inconsistent hit record')
    hits=[]
    previous=-1
    for line in lines:
        try:
            index_str,command_str=line.split()
            index,command=int(index_str),int(command_str,16)
        except ValueError as exc:
            raise ValueError('invalid hit line: '+line) from exc
        address=command & 0xffffff
        if (index<=previous or index>=seen or command>>24!=3 or
                not first<=address<last):
            raise ValueError('out-of-order or out-of-range hit: '+line)
        hits.append(dict(transaction=index,command=f'{command:08x}',address=f'{address:06x}'))
        previous=index
    return dict(seen=seen,kept=kept,overflow=overflow,stall=stall,
                cancelled=bool(cancelled),hits=hits,
                usable_for_ordering=not (overflow or stall or cancelled))


def collect(port, output, first, last, timeout):
    if not 0<=first<last<=0x1000000 or not 1<=timeout<=120:
        raise ValueError('address range or timeout out of bounds')
    if Path(output).exists():
        raise FileExistsError(output)
    serial=Serial(port)
    pending=False
    try:
        serial.write(b'\nstatus\n')
        status_deadline=time.monotonic()+5
        for _ in range(10):
            banner=serial.line(status_deadline)
            if banner not in ('','ERROR invalid command or limits'):
                break
        if (not banner.startswith('BC250-PICO2-PASSIVE v1 ') or
                'outputs=OFF' not in banner or 'hunt=1' not in banner):
            raise ValueError('requires passive v0.3 input-only firmware: '+banner)
        serial.line(time.monotonic()+5)
        serial.write(f'hunt {first:06x} {last:06x} {timeout*1000}\n'.encode())
        pending=True
        armed=serial.line(time.monotonic()+5)
        if not armed.startswith('ARMED HUNT ') or 'outputs=OFF' not in armed:
            raise ValueError(armed)
        print(armed+' — reboot the BC250 now',flush=True)
        header=serial.line(time.monotonic()+timeout+10)
        if not header.startswith('HITS '):
            raise ValueError(header)
        try:
            kept=int(dict(item.split('=',1) for item in header[5:].split())['kept'])
        except (KeyError,ValueError) as exc:
            raise ValueError('invalid hit count') from exc
        if not 0<=kept<=4096:
            raise ValueError('invalid kept hit count')
        transfer_deadline=time.monotonic()+30
        lines=[serial.line(transfer_deadline) for _ in range(kept)]
        footer=serial.line(transfer_deadline)
        pending=False
        result=parse_hits(header,lines,footer,first,last)
        result.update(schema=1,first=f'{first:06x}',last=f'{last:06x}',
                      pico_outputs_off=True,board_flash_written=False,
                      transport='USB CDC text',clock_hz=150000000)
        encoded=(json.dumps(result,indent=2)+'\n').encode()
        private_write(output,encoded)
        print(json.dumps({k:v for k,v in result.items() if k!='hits'},indent=2))
    finally:
        if pending:
            try: serial.write(b'x\n',timeout=1)
            except (OSError,TimeoutError): pass
        serial.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--first',type=lambda s:int(s,16),default=0x9dad00)
    p.add_argument('--last',type=lambda s:int(s,16),default=0x9dc240)
    p.add_argument('--timeout',type=int,default=35)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    collect(args.port,args.output,args.first,args.last,args.timeout)


if __name__=='__main__':
    main()
