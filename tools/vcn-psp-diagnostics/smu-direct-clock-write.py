#!/usr/bin/env python3
"""Guarded, volatile SMU-core store to the Van Gogh VCN clock-enable address.

The first live mode stores zero only. The toggle mode stores zero, then one,
then zero again. Neither mode reads the target register, whose direct SMU-core
read stalled on this BC250. No BIOS or Pico flash is written.
"""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
BASE_SCRIPT = ROOT / 'smu-direct-clock-read.py'
SOURCE_SHA = 'b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0'
WRITE_SHA = 'eafebd45e986ab1cc1f48cfe33054942cf794ab6e27caa2d7b00f06b9957283c'
TARGET = 0x0116f200
RECOVERY = 'bc250-smu-direct-clock-recovery.timer'
GOVERNOR = 'cyan-skillfish-governor-smu'
METRICS = Path('/sys/class/drm/card1/device/gpu_metrics')
GPU = Path('/sys/bus/pci/devices/0000:01:00.0')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def metrics():
    data = METRICS.read_bytes()
    require(len(data) >= 88, 'short GPU metrics')
    size, major, minor = struct.unpack_from('<HBB', data)
    require((major, minor) == (2, 2) and size <= len(data),
            f'unexpected metrics version {major}.{minor} size={size}')
    avg_vclk, avg_dclk = struct.unpack_from('<HH', data, 72)
    now_vclk, now_dclk = struct.unpack_from('<HH', data, 84)
    return {'average_vclk_mhz': avg_vclk, 'average_dclk_mhz': avg_dclk,
            'current_vclk_mhz': now_vclk, 'current_dclk_mhz': now_dclk}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('preflight', 'zero', 'toggle'),
                        default='preflight')
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    require(BOOT_ID.read_text().strip() == args.expected_boot_id,
            'boot ID changed')
    require((GPU / 'vendor').read_text().strip() == '0x1002' and
            (GPU / 'device').read_text().strip() == '0x13fe', 'wrong GPU')
    require(hashlib.sha256((ROOT / 'smu-sram.bin').read_bytes()).hexdigest()
            == SOURCE_SHA, 'wrong SMU source image')
    body = (ROOT / 'smu-direct-clock-write.bin').read_bytes()
    require(len(body) == 90 and hashlib.sha256(body).hexdigest() == WRITE_SHA,
            'wrong SMU write helper')
    if args.mode != 'preflight':
        require(subprocess.run(['systemctl', 'is-active', '--quiet', RECOVERY])
                .returncode == 0, 'recovery timer required')

    spec = importlib.util.spec_from_file_location('smu_direct_clock_base', BASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.insert(0, str(ROOT / 'bc250-smu-unlock'))
    from bc250_smu import Bc250Smu
    from bc250_smu.errors import SmuTimeout

    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)

    with args.output.open('x') as evidence, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def emit(event, data):
            evidence.write(json.dumps({'time': time.time(), 'event': event,
                                       'data': data}) + '\n')
            evidence.flush()
            os.fsync(evidence.fileno())
            print(event, json.dumps(data), flush=True)

        emit('start', {'mode': args.mode, 'boot_id': args.expected_boot_id,
                       'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'base_script_sha256': hashlib.sha256(BASE_SCRIPT.read_bytes()).hexdigest(),
                       'body_sha256': WRITE_SHA})
        active = subprocess.run(['systemctl', 'is-active', '--quiet', GOVERNOR])
        active = active.returncode == 0
        smu = probe = None
        healthy = False
        target_zero_restored = args.mode != 'toggle'
        try:
            if active:
                subprocess.run(['systemctl', 'stop', GOVERNOR], check=True, timeout=15)
            smu = Bc250Smu(timeout=1)
            probe = module.Probe(
                smu, SmuTimeout, (ROOT / 'smu-sram.bin').read_bytes(), body,
                TARGET, emit, expected_body_sha=WRITE_SHA,
                expected_body_size=90, target_writes=True)
            probe.preflight()
            emit('metrics_before', metrics())
            if args.mode != 'preflight':
                probe.install()
                emit('store_zero_intent', {'address': hex(TARGET)})
                require(probe.invoke(0x42) == (1, 0), 'store-zero rejected')
                emit('metrics_after_zero', metrics())
                if args.mode == 'toggle':
                    try:
                        emit('store_one_intent', {'address': hex(TARGET)})
                        require(probe.invoke(0x43) == (1, 1), 'store-one rejected')
                        emit('metrics_after_one', metrics())
                    finally:
                        if not probe.pending:
                            emit('restore_zero_intent', {'address': hex(TARGET)})
                            require(probe.invoke(0x42) == (1, 0),
                                    'store-zero restoration rejected')
                            target_zero_restored = True
                            emit('metrics_after_restore', metrics())
                require(probe.invoke(0x40) == (1, 0x02500016),
                        'post-store signature failed')
            emit('completed', {'mode': args.mode,
                               'target_zero_restored': target_zero_restored})
        except BaseException as error:
            emit('error', {'detail': repr(error),
                           'target_zero_restored': target_zero_restored})
            raise
        finally:
            try:
                if probe is not None and not probe.pending:
                    probe.restore()
                if smu is not None and not (probe and probe.pending):
                    healthy = smu.alive()
            finally:
                if smu is not None:
                    smu.close()
                if active and healthy:
                    subprocess.run(['systemctl', 'start', GOVERNOR],
                                   check=True, timeout=15)
                emit('cleanup', {'smu_alive': healthy,
                                 'restored': probe.restored if probe else False,
                                 'pending': probe.pending if probe else False,
                                 'target_zero_restored': target_zero_restored,
                                 'governor_active': subprocess.run(
                                     ['systemctl', 'is-active', '--quiet', GOVERNOR])
                                     .returncode == 0})


if __name__ == '__main__':
    main()
