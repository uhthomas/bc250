#!/usr/bin/env python3
"""Guarded volatile test of SMU-window writability at BC250 SMN 0x50d6c.

The candidate value 0x8f0 adds bit 11 to the observed 0xf0 baseline. This
tests a Van Gogh-derived hypothesis, not a proven BC250 VCN control. The
script always attempts to restore 0xf0 and never writes BIOS/Pico flash.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

sys.path.insert(0, '/var/tmp/bc250-smu-vcn')
from bc250_smu import Bc250Smu

BASE = Path(__file__).with_name('compare_smu_fabric_window.py')
spec = importlib.util.spec_from_file_location('compare_smu_fabric_window', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

TARGET = 0x50d6c
BEFORE = 0xf0
CANDIDATE = 0x8f0
METRICS = Path('/sys/class/drm/card1/device/gpu_metrics')


def emit(event, data):
    print(json.dumps({'event': event, 'time': time.time(), 'data': data},
                     sort_keys=True), flush=True)


def vclk():
    data = METRICS.read_bytes()
    size, major, minor = struct.unpack_from('<HBB', data)
    base.require((major, minor) == (2, 2) and size <= len(data),
                 'unexpected GPU metrics version')
    return {'average_vclk_mhz': struct.unpack_from('<H', data, 72)[0],
            'current_vclk_mhz': struct.unpack_from('<H', data, 84)[0]}


def observation(fd, smu):
    host = base.root_smn_read(fd, TARGET)
    status, window = smu.sec_smn_read32(TARGET)
    base.require(status == 1, f'SMU window read failed: {status:#x}')
    return {'host': f'{host:#010x}', 'smu_window': f'{window:#010x}',
            'vclk': vclk()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    args = parser.parse_args()
    base.require(os.geteuid() == 0, 'root required')
    base.require(base.BOOT_ID.read_text().strip() == args.expected_boot_id,
                 'boot ID changed')
    base.identity(base.ROOT_CONFIG, 0x13e01022)
    base.identity(base.GPU_CONFIG, 0x13fe1002)
    base.require(subprocess.run(['systemctl', 'is-active', '--quiet',
                                 base.GOVERNOR]).returncode == 0,
                 'GPU governor not active before diagnostic')
    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    emit('start', {'boot_id': args.expected_boot_id, 'target': hex(TARGET),
                   'baseline': hex(BEFORE), 'candidate': hex(CANDIDATE)})
    subprocess.run(['systemctl', 'stop', base.GOVERNOR], check=True, timeout=15)
    smu = None
    fd = None
    target_may_have_changed = False
    restored = False
    alive = False
    try:
        smu = Bc250Smu(timeout=2)
        base.require(smu.alive(), 'SMU liveness failed')
        base.require(int.from_bytes(smu.smu_read(0x7b3c), 'little') == 0,
                     'secure SMU debug path is closed')
        fd = os.open(base.ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
        for address, expected in base.CONTROLS:
            host = base.root_smn_read(fd, address)
            status, window = smu.sec_smn_read32(address)
            base.require((host, status, window) == (expected, 1, expected),
                         f'control mismatch at {address:#x}')
        initial = observation(fd, smu)
        emit('baseline', initial)
        base.require(initial['host'] == f'{BEFORE:#010x}' and
                     initial['smu_window'] == f'{BEFORE:#010x}',
                     'fabric baseline mismatch')
        emit('idempotent_write_intent', {'value': hex(BEFORE)})
        smu.smn_write32(TARGET, BEFORE)
        same = observation(fd, smu)
        emit('idempotent_write_readback', same)
        base.require(same['host'] == f'{BEFORE:#010x}' and
                     same['smu_window'] == f'{BEFORE:#010x}',
                     'idempotent write changed fabric state')
        emit('candidate_write_intent', {'value': hex(CANDIDATE)})
        target_may_have_changed = True
        smu.smn_write32(TARGET, CANDIDATE)
        after = observation(fd, smu)
        emit('candidate_readback', after)
        base.require(after['host'] in (f'{BEFORE:#010x}', f'{CANDIDATE:#010x}') and
                     after['smu_window'] == after['host'],
                     'unexpected fabric readback; restoration required')
    finally:
        if target_may_have_changed and smu is not None:
            try:
                emit('restore_intent', {'value': hex(BEFORE)})
                smu.smn_write32(TARGET, BEFORE)
                if fd is not None:
                    final = observation(fd, smu)
                    emit('restore_readback', final)
                    restored = (final['host'] == f'{BEFORE:#010x}' and
                                final['smu_window'] == f'{BEFORE:#010x}')
            except Exception as error:
                emit('restore_error', {'error': repr(error)})
        if fd is not None:
            os.close(fd)
        if smu is not None:
            try:
                alive = smu.alive()
            except Exception:
                alive = False
            smu.close()
        if alive and (restored or not target_may_have_changed):
            subprocess.run(['systemctl', 'start', base.GOVERNOR],
                           check=True, timeout=15)
        emit('cleanup', {'smu_alive': alive, 'restored': restored,
                         'governor_active': subprocess.run(
                             ['systemctl', 'is-active', '--quiet', base.GOVERNOR]
                         ).returncode == 0})
        if target_may_have_changed:
            base.require(restored, 'fabric value not verified restored; cold cycle required')


if __name__ == '__main__':
    main()
