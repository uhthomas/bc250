#!/usr/bin/env python3
"""Read-only BC250 SMU preflight for the Q3 0x1d VCN-clock walker.

This reads the live SMU clock table, its VCN slot, the Q3 handler pointer,
domain-6 controls and GPU metrics. It does not send the clock message or
write a target register, SRAM word, BIOS image or Pico image.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys

sys.path.insert(0, '/var/tmp/bc250-smu-vcn')
from bc250_smu import Bc250Smu

BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
GPU = Path('/sys/bus/pci/devices/0000:01:00.0')
METRICS = Path('/sys/class/drm/card1/device/gpu_metrics')
GOVERNOR = 'cyan-skillfish-governor-smu'
BASE = 0x13ed4
COUNT = 20
SENTINEL = 0x4f800000  # float32 4294967296.0


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read32(smu, address):
    data = smu.smu_read(address)
    require(len(data) == 4, f'short SMU read at {address:#x}')
    return struct.unpack('<I', data)[0]


def read_smn(smu, address):
    status, value = smu.sec_smn_read32(address)
    require(status == 1, f'SMN read failed at {address:#x}: {status:#x}')
    return value


def read_table(smu):
    # Q2's transfer engine accepts no more than 18 dwords per read.
    out = bytearray()
    length = 0x240
    for offset in range(0, length, 72):
        words = min(18, (length - offset) // 4)
        out.extend(smu.smu_read(BASE + offset, words))
    require(len(out) == length, 'short clock table')
    return bytes(out)


def metrics():
    data = METRICS.read_bytes()
    size, major, minor = struct.unpack_from('<HBB', data)
    require((major, minor) == (2, 2) and size <= len(data),
            f'unexpected GPU metrics {major}.{minor}')
    return {'vclk_current_mhz': struct.unpack_from('<H', data, 84)[0],
            'dclk_current_mhz': struct.unpack_from('<H', data, 86)[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root required')
    require(BOOT_ID.read_text().strip() == args.expected_boot_id,
            'boot ID changed')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'unexpected kernel')
    require((GPU / 'vendor').read_text().strip() == '0x1002' and
            (GPU / 'device').read_text().strip() == '0x13fe', 'unexpected GPU')
    require(subprocess.run(['systemctl', 'is-active', '--quiet', GOVERNOR])
            .returncode == 0, 'governor was not running')
    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    subprocess.run(['systemctl', 'stop', GOVERNOR], check=True, timeout=15)
    smu = None
    alive = False
    try:
        smu = Bc250Smu(timeout=2)
        require(smu.alive(), 'SMU liveness check failed')
        require(read32(smu, 0x7b3c) == 0, 'secure SMU debug path closed')
        require(read32(smu, 0x746c + 8 * (0x1d - 1)) == 0x2e6c8,
                'Q3 0x1d handler differs')
        require((read32(smu, 0x181e0), read32(smu, 0x181e4)) ==
                (BASE, BASE + COUNT * 12), 'clock-table pointers differ')
        blob = read_table(smu)
        u32 = lambda offset: struct.unpack_from('<I', blob, offset)[0]
        f32 = lambda word: struct.unpack('<f', struct.pack('<I', word))[0]
        rows = []
        zero_targets = []
        for index in range(COUNT):
            slot = u32(8 + 4 * index)
            applied_word = u32(0x5c + 12 * index)
            desired_word = u32(0x14c + 12 * index)
            entry = 0xf710 + slot * 28
            current = (read32(smu, (entry + 130) & ~3) >>
                       ((entry + 130) & 3) * 8) & 0xff
            row = {'mailbox_index': index + 1, 'slot': slot,
                   'current_code': current,
                   'applied_mhz': f32(applied_word),
                   'desired_mhz': f32(desired_word),
                   'desired_word': f'{desired_word:#010x}'}
            rows.append(row)
            if desired_word == 0 and slot != 0x17:
                zero_targets.append(index + 1)
        require([rows[i - 1]['slot'] for i in (11, 15, 16)] ==
                [0x18, 0x16, 0x17], 'VCN clock indices differ')
        require(rows[15]['desired_word'] == '0x00000000' and
                rows[15]['current_code'] == 0, 'VCN clock already changed')
        require(u32(0) == u32(4), 'clock walker already has pending work')
        controls = {f'{addr:#x}': f'{read_smn(smu, addr):#010x}'
                    for addr in (0x6d0f8, 0x6d128, 0x6d130, 0x6d190)}
        require(controls == {'0x6d0f8': '0x00000002',
                             '0x6d128': '0x00000000',
                             '0x6d130': '0x00000000',
                             '0x6d190': '0x01010101'},
                'domain-6 controls differ')
        result = {'boot_id': args.expected_boot_id, 'generation': u32(0),
                  'clock_rows': rows, 'non_target_zero_indices': zero_targets,
                  'skip_sentinel_word': f'{SENTINEL:#010x}',
                  'domain6_controls': controls, 'metrics': metrics(),
                  'target_writes': False}
        alive = smu.alive()
        require(alive, 'SMU stopped responding')
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        if smu is not None:
            if not alive:
                try:
                    alive = smu.alive()
                except Exception:
                    pass
            smu.close()
        if alive:
            subprocess.run(['systemctl', 'start', GOVERNOR], check=True,
                           timeout=15)


if __name__ == '__main__':
    main()
