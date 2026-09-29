#!/usr/bin/env python3
"""Pair the native SMU VCN clock with one pinned opt-in decoder startup.

Run only on the isolated diagnostic boot with an armed Pi PDU recovery timer.
The clock-table generation is never rolled back: cold-cycle outlet 8 after
collecting the result. No BIOS EEPROM or Pico QSPI flash write is involved.
"""

import argparse
import fcntl
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import time

from bc250_smu import Bc250Smu
import trial_smu_clock_walker as clock
import trial_smu_clock_callback_once as callback

ROOT = Path('/var/lib/bc250/validation/video-20260922')
MODULES = {
    'lmi-oracle': ('amdgpu-vcn-lmi-oracle.ko',
                   '56343ccf27087c59e3f86fb22536decc365519b4d4e8c25bac0e027cfd8a89e1'),
    'postrelease-measure': ('amdgpu-vcn-postrelease-measure.ko',
                            '45380a06d508d4c2b0fb170b64dc4cb77c2bb0b4136dc21c427f8161e8c55bc6'),
    'crosspath-scratch': ('amdgpu-vcn-crosspath-scratch.ko',
                          '3ed185f9952c93ac8acd2d52457f844b719f0860e0ed61e4149b734c72076155'),
    'dpg-bank-survey': ('amdgpu-vcn-dpg-bank-survey.ko',
                        'f39444e89677689f359b31925697481fe9a999c3e53fe5eb275a6605557c1a85'),
    'relocation-control': ('amdgpu-vcn-dpg-bank-survey.ko',
                           'f39444e89677689f359b31925697481fe9a999c3e53fe5eb275a6605557c1a85'),
    'delayed-reset': ('amdgpu-vcn-delayed-reset.ko',
                      'e3e66da927d9463c77e81a2b72deebe54f94c3be67bc969c494e216ce38b1840'),
    'delayed-cache-size0': ('amdgpu-vcn-delayed-cache-size0.ko',
                            '250c1666410d4c32654745000c7d80819203770c774e72f7fadd5fbaaa98027d'),
    'direct-bo-powered': ('amdgpu-vcn-direct-bo-powered.ko',
                          '70aacb396d26ef0651f7d42468a4a413da82cd0cdd400c7d970d02b5dabba580'),
    'psp-bo-fetch': ('amdgpu-vcn-psp-bo-fetch.ko',
                     '7101cd6b9278ea5752051b1d9c06f97f1bb9a61a852cb062fd5eaae1affdd40e'),
    'psp-bo-premap': ('amdgpu-vcn-psp-bo-premap.ko',
                      '26009b01c48f857b8a899bffe60913614befac28d358c71453ae0cc02d17a726'),
    'lmi-latency': ('amdgpu-vcn-lmi-latency.ko',
                    '2102f14853045acc9a1ea80aebfd86a85264903ab3f3f01745bf2de6f34e72c3'),
    'memory-requests': ('amdgpu-vcn-memory-requests.ko',
                        '428a5a26de5d916a982ba5033f3d717313588e8c617cd96ccac4414b00c0ce45'),
    'lmi-perfmon': ('amdgpu-vcn-lmi-perfmon.ko',
                    'fbff7df48b00f3a12ba3aaf40a113b9f0cc52a8ebe9b949ef749e45ee787b620'),
    'mmsch-mode': ('amdgpu-vcn-mmsch-mode.ko',
                   '6708294cbb1e6337f3f381541df729d98266b4a5de6776bf8538e811fcf6663d'),
    'rbc-fetch': ('amdgpu-vcn-rbc-fetch.ko',
                  '7ac44304467aaf43d57eaeccaac89d9e0f7d936049149d5a8020e13e3f486c65'),
    'rbc-control': ('amdgpu-vcn-rbc-control.ko',
                    'e6beabd30af2016d709f62df76ae410aad3cbd0cdfee04419ec53bee71f0cd99'),
    'rbc-direct-packet': ('amdgpu-vcn-rbc-direct-packet.ko',
                          'c98efaaf5c13069ee6b30554ab41580796ffc9c8176f79c31248d45de208f60a'),
    'rbc-vcpu-trace': ('amdgpu-vcn-rbc-vcpu-trace.ko',
                       '0e2d2649ee443d8767e7d9b03ae777cf7c8443e1a50fa70d0664f7041d13dc1b'),
    'rbc-vcpu-clock': ('amdgpu-vcn-rbc-vcpu-clock.ko',
                       '731e7025c3db7524f1358e2476e62c876d8105d69f0bf1dfe86855213edd4209'),
    'rbc-vcpu-clock-internal': ('amdgpu-vcn-rbc-vcpu-clock-internal.ko',
                                'b181d030ae1e99e0be4be05bc9412aed9a9d7894ece3b591e46518ba593b3f52'),
    'rbc-vcpu-clock-mapped': ('amdgpu-vcn-rbc-vcpu-clock-mapped.ko',
                              '36a102866585debda1d486faacb363cc619c85d79ee8691c0182892358469710'),
    'rbc-vcpu-trace-mapped': ('amdgpu-vcn-rbc-vcpu-trace-mapped.ko',
                              '12953b90192276e42ba8ffbef5195a57bf50df6d0300c9880565b84494b14531'),
    'rbc-vcpu-reset-mapped': ('amdgpu-vcn-rbc-vcpu-reset-mapped.ko',
                              '30e1245ef82402c7160ac88a3f37500f79b2844ad6c572abf3724634d181a71b'),
    'rbc-cache-map': ('amdgpu-vcn-rbc-cache-map.ko',
                      'd03d6653104f1b46fc73207bc109b5999807ea5d64a7bbccd5102a7558b5864a'),
    'rbc-cache-readback': ('amdgpu-vcn-rbc-cache-readback.ko',
                           '76042d81e0cddbdf1b4c6333cae97b4bd5b499df850b1a9ad5b5023ae9469e27'),
    'host-vcpu-trace': ('amdgpu-vcn-host-vcpu-trace.ko',
                        '5ae1352f072727d4b162d75def8c2b35e69c935dc698ac8ebbb1166686135334'),
    'arbiter-probe': ('amdgpu-vcn-arbiter-probe.ko',
                      'dfba2a1b327c57f19d5347444c361bf3a6c9893e5f26a7ca6b9ce778de5f3614'),
    'clock-gate-probe': ('amdgpu-vcn-clock-gate-probe-v2.ko',
                         '608377257401f9dd599101ba71ae5a9a46a2c196237adaca62706d3798ae0de6'),
    'phase-map': ('amdgpu-vcn-startup-phase.ko',
                  'f164be16cdae057c7c20dd88ad89e0aeb75fc785e7e677d31bfeaaddf1eea837'),
    'ip-phase-map': ('amdgpu-vcn-ip-phase.ko',
                     'c1c2b7932d8bb629d3542264a9462bd9bc6bce4fe973cbebe98412cecbe3e1f6'),
    'psp-phase-map': ('amdgpu-vcn-psp-phase.ko',
                      '9dee7e5ad959f27ba5617100d1ff191665e1a81c079513241ab6657fc1991990'),
    'jpeg-only': ('amdgpu-bc250-jpeg-only.ko',
                  '1aa2556c089d19a4657d1278bdd3879ca2a67e59e1eee16190b9d224cd843d38'),
    'jpeg-mmio': ('amdgpu-bc250-jpeg-mmio.ko',
                  '5b83d4d4a5ee78055022ac7873a8621c18b031fae7ea39ea4454e2e7809914e3'),
    'jpeg-readback': ('amdgpu-bc250-jpeg-readback.ko',
                      '64a6b56569354182248245ca943c11b7571fb32444d3636c833ea94ba899ef87'),
    'jpeg-reset-clock': ('amdgpu-bc250-jpeg-reset-clock.ko',
                         'f45a7a2f5ff2e759afb0c41b962981c1c1cc50696cb04ffc9c5d5dda0275333d'),
    'jpeg-scratch': ('amdgpu-bc250-jpeg-scratch.ko',
                     '9123b4ed385203e19449c5e18466171fc9bb7e6e29409a5b881daac7eb663000'),
    'jpeg-uvdw-power': ('amdgpu-bc250-jpeg-uvdw-power.ko',
                        'cc6b465448eb9df13bffe589eebd17c95fb0482d2e575e09021fe3bcdfbf2ce0'),
}
FIRMWARE_SHA = 'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5'
STAGE_SHA = '0cca277fbeecbf71512ae253644af0964458f8324ca34df84934798e01a198dc'
ENTRY_SHA = '9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9'
DEPS = ('drm_display_helper', 'gpu-sched', 'amdxcp', 'ttm', 'cec',
        'drm_suballoc_helper', 'drm_exec', 'video', 'drm_ttm_helper',
        'drm_buddy', 'i2c-algo-bit', 'drm_panel_backlight_quirks')
WIN = 0x01100000
ENABLES = (0x6d108, 0x6d130, 0x6d158)
CONTROL = 0x6d0f8
POWER_COMMAND = 0x6d17c
POWER_RAIL = 0x6d184
POWER_STATUS = 0x6d190


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded_power_up(smu, emit):
    """Reapply only controls already exercised in earlier volatile trials."""
    require([clock.smn(smu, address) for address in ENABLES] == [0, 0, 0]
            and clock.smn(smu, CONTROL) == 2,
            'VCN gate baseline differs after native clock request')
    require(clock.word(smu, 0xf714) == 0x10101 and
            clock.smn(smu, POWER_STATUS) == 0x01010101 and
            clock.smn(smu, POWER_COMMAND) == 0 and
            clock.smn(smu, POWER_RAIL) == 0,
            'domain-6 power baseline differs')
    for address in ENABLES:
        emit('smu_gate_write_intent', {'address': hex(WIN + address), 'value': 1})
        smu.smu_write32(WIN + address, 1)
        require(clock.smn(smu, address) == 1,
                f'VCN slot enable did not read back at {address:#x}')
    emit('smu_gate_write_intent', {'address': hex(WIN + CONTROL), 'value': 0})
    smu.smu_write32(WIN + CONTROL, 0)
    require(clock.smn(smu, CONTROL) == 0, 'domain gate did not release')
    for address, value, poll, mask, expected in (
        (POWER_COMMAND, 1, POWER_STATUS, 0x100, 0x100),
        (POWER_RAIL, 0x10000, POWER_RAIL, 0x10000, 0),
    ):
        emit('smu_power_write_intent', {'address': hex(WIN + address),
                                        'value': hex(value)})
        smu.smu_write32(WIN + address, value)
        deadline = time.monotonic() + 0.5
        while clock.smn(smu, poll) & mask != expected:
            require(time.monotonic() < deadline,
                    'domain-6 power acknowledgement timed out')
            time.sleep(0.01)
    require(clock.smn(smu, clock.CLOCK_SMN) == 16 and
            [clock.smn(smu, address) for address in ENABLES] == [1, 1, 1] and
            clock.smn(smu, CONTROL) == 0,
            'clock/gate state changed before decoder startup')
    emit('native_clock_and_gates_ready', {'clock_code': 16,
                                           'slot_enables': [1, 1, 1],
                                           'domain_gate': 0})


def preflight(expected_boot_id, module_kind):
    require(os.geteuid() == 0 and
            clock.BOOT_ID.read_text().strip() == expected_boot_id,
            'root or boot-ID guard failed')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    flags = Path('/proc/cmdline').read_text().split()
    for flag in ('bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
                 'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'):
        require(flag in flags, f'missing diagnostic boot flag: {flag}')
    require(not Path('/sys/module/amdgpu').exists(), 'GPU driver already loaded')
    require((clock.GPU/'vendor').read_text().strip() == '0x1002' and
            (clock.GPU/'device').read_text().strip() == '0x13fe', 'wrong GPU')
    require(not subprocess.check_output(['grub2-editenv', '-', 'list'],
                                        text=True).strip() and
            not Path('/boot/grub2/custom.cfg').exists(),
            'temporary diagnostic boot entry was not cleaned')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service])
                .returncode != 0, f'{service} is active')
    name, expected_sha = MODULES[module_kind]
    module = ROOT/'kernel'/name
    require(sha(module) == expected_sha, 'VCN module hash mismatch')
    firmware = lzma.decompress(
        Path('/usr/lib/firmware/amdgpu/navi10_vcn.bin.xz').read_bytes())
    require(hashlib.sha256(firmware).hexdigest() == FIRMWARE_SHA,
            'VCN firmware hash mismatch')
    stage = ROOT/'kernel/stage-psp-boot.sh'
    require(sha(stage) == STAGE_SHA and
            sha(ROOT/'kernel/psp-test-custom.cfg') == ENTRY_SHA,
            'diagnostic recovery entry changed')
    require(sha(clock.SOURCE) == clock.SOURCE_SHA,
            'captured SMU image changed')
    return stage, module, expected_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--module-kind', choices=tuple(MODULES),
                        default='lmi-oracle')
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--pi-pdu-timer-active', action='store_true')
    args = parser.parse_args()
    require(args.preflight_only or args.pi_pdu_timer_active,
            'verified Pi PDU timer required for writes')
    stage, module, module_sha = preflight(args.expected_boot_id,
                                          args.module_kind)
    if args.preflight_only:
        smu = Bc250Smu(timeout=2)
        try:
            trial = clock.Trial(smu, clock.SOURCE.read_bytes(),
                                lambda event, data: print(json.dumps(
                                    {'event': event, 'data': data})),
                                require_gpu_metrics=False)
            trial.preflight()
            require(clock.word(smu, 0x17090) == 0xc700 and
                    clock.word(smu, 0x17098) == 0xc7a0 and
                    clock.word(smu, 0xc760) == 0x2e448 and
                    clock.read(smu, 0x1b154, 0x4c) ==
                    trial.source[0x1b154:0x1b1a0],
                    'periodic callback differs')
            print(json.dumps({'preflight_only': True,
                              'boot_id': args.expected_boot_id,
                              'callback_verified': True}))
        finally:
            smu.close()
        return
    with args.output.open('x') as journal, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def emit(event, data):
            row = {'time': time.time(), 'event': event, 'data': data}
            journal.write(json.dumps(row) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            if event != 'kernel_rows':
                print(json.dumps(row), flush=True)

        emit('start', {'boot_id': args.expected_boot_id,
                       'module_kind': args.module_kind,
                       'module_sha256': module_sha,
                       'firmware_sha256': FIRMWARE_SHA,
                       'source_sha256': clock.SOURCE_SHA,
                       'runner_sha256': sha(Path(__file__)),
                       'cold_cycle_required': True})
        for dependency in DEPS:
            subprocess.run(['modprobe', dependency], check=True)
        require(not Path('/sys/module/amdgpu').exists(),
                'dependency loaded amdgpu')
        smu = Bc250Smu(timeout=2)
        try:
            trial = clock.Trial(smu, clock.SOURCE.read_bytes(), emit,
                                require_gpu_metrics=False)
            trial.preflight()
            callback.callback_once(trial, emit)
            guarded_power_up(smu, emit)
            # SETUP_TMR may hang the diagnostic driver, so pre-arm recovery.
            subprocess.run(['unshare', '--mount', '--propagation', 'private',
                            'bash', str(stage)], check=True, timeout=15)
            require(subprocess.check_output(['grub2-editenv', '-', 'list'],
                                            text=True).strip() == 'bc250_vcn_once=1'
                    and sha(Path('/boot/grub2/custom.cfg')) == ENTRY_SHA,
                    'diagnostic recovery entry not armed')
            emit('recovery_entry_staged', {'sha256': ENTRY_SHA})
            emit('insmod_intent', {'module': str(module), 'bc250_vcn': 1})
            result = subprocess.run(['insmod', str(module), 'bc250_vcn=1',
                                     'bc250_vcn_psp_probe=0'],
                                    capture_output=True, text=True, timeout=110)
            emit('insmod_return', {'returncode': result.returncode,
                                  'stdout': result.stdout[-2000:],
                                  'stderr': result.stderr[-2000:]})
            kernel_lines = subprocess.check_output(
                ['dmesg', '--color=never'], text=True).splitlines()
            rows = [line for line in kernel_lines
                if any(mark in line.lower() for mark in
                       ('amdgpu', 'vcn', 'uvd', 'psp', 'setup_tmr'))][-160:]
            emit('kernel_rows', rows)
            trace = [line for line in kernel_lines
                     if 'BC250 VCN' in line or 'BC250 MMSCH' in line]
            emit('vcn_register_trace', trace)
            if args.module_kind == 'host-vcpu-trace':
                armed = [line for line in trace
                         if 'BC250 VCN host trace armed:' in line]
                sampled = [line for line in trace
                           if 'BC250 VCN host trace result:' in line]
                restored = [line for line in trace
                            if 'BC250 VCN host trace restored:' in line]
                require(len(armed) == len(sampled) == len(restored) == 1,
                        'missing or duplicate host VCPU trace')
                armed_match = re.search(
                    r'before=([0-9a-f]{8}) after=([0-9a-f]{8}) '
                    r'prid=([0-9a-f]{8}) pc=([0-9a-f]{8}) '
                    r'status=([0-9a-f]{8})', armed[0])
                sampled_match = re.search(
                    r'first=([0-9a-f]{8}) last=([0-9a-f]{8}) '
                    r'and=([0-9a-f]{8}) or=([0-9a-f]{8}) '
                    r'changes=(\d+) status_or=([0-9a-f]{8}) '
                    r'cntl=([0-9a-f]{8}) prid=([0-9a-f]{8}) '
                    r'pf=([0-9a-f]{8}) lmi=([0-9a-f]{8})', sampled[0])
                restored_match = re.search(r'cntl=([0-9a-f]{8})',
                                           restored[0])
                require(armed_match and sampled_match and restored_match,
                        'malformed host VCPU trace')
                before, after, prid, pc, status = (
                    int(value, 16) for value in armed_match.groups())
                first, last, pc_and, pc_or, changes, status_or, cntl, \
                    prid_after, fault, lmi = (
                        int(value, 10 if i == 4 else 16)
                        for i, value in enumerate(sampled_match.groups()))
                require(before == 0x0ff20200 and after == 0x0ff20600 and
                        cntl == after and int(restored_match[1], 16) == before,
                        'host trace control failed to latch or restore')
                emit('vcn_host_vcpu_trace', {
                    'trace_enabled': True, 'prid_before': hex(prid),
                    'prid_after': hex(prid_after), 'pc_before': hex(pc),
                    'pc_first': hex(first), 'pc_last': hex(last),
                    'pc_and': hex(pc_and), 'pc_or': hex(pc_or),
                    'pc_changes': changes, 'status_before': hex(status),
                    'status_or': hex(status_or), 'page_fault': hex(fault),
                    'lmi_status': hex(lmi),
                    'vcpu_pc_nonzero': bool(pc_or & 0x0fffffff),
                })
            if args.module_kind in ('jpeg-only', 'jpeg-mmio',
                                    'jpeg-readback', 'jpeg-reset-clock',
                                    'jpeg-scratch', 'jpeg-uvdw-power'):
                jpeg_trace = [line for line in kernel_lines
                              if 'BC250 JPEG' in line or 'jpeg_dec' in line]
                emit('jpeg_register_trace', jpeg_trace)
                require(any('BC250 JPEG-only ring probe enabled' in line
                            for line in jpeg_trace),
                        'JPEG-only IP registration not observed')
                emit('jpeg_probe_result', {
                    'power_reached': any('BC250 JPEG power:' in line
                                         for line in jpeg_trace),
                    'ring_reached': any('BC250 JPEG ring:' in line
                                        for line in jpeg_trace),
                    'ring_test_failed': any('ring jpeg_dec test failed' in line
                                            for line in jpeg_trace),
                    'gpu_bound': (clock.GPU/'driver').exists(),
                })
            if args.module_kind in ('phase-map', 'ip-phase-map',
                                    'psp-phase-map'):
                phases = [line for line in trace if 'BC250 VCN phase ' in line]
                emit('vcn_phase_trace', phases)
                require(len(phases) == 6 and
                        all(any(f'BC250 VCN phase {phase}:' in line
                                for line in phases)
                            for phase in ('sw-entry', 'after-vcn-sw-init',
                                          'after-vcn-resume', 'start-entry',
                                          'after-smu-power-call', 'after-local-pg')),
                        'missing or duplicate VCN startup phase snapshot')
            if args.module_kind in ('ip-phase-map', 'psp-phase-map'):
                ip_phases = [line for line in trace
                             if 'BC250 VCN IP phase ' in line]
                emit('vcn_ip_phase_trace', ip_phases)
                require(len(ip_phases) >= 12 and
                        all(any(f'BC250 VCN IP phase {phase} ' in line
                                for line in ip_phases)
                            for phase in ('after-sw-init', 'after-phase1',
                                          'before-psp', 'after-psp',
                                          'after-smu-firmware', 'before-phase2',
                                          'phase2-before', 'phase2-after')),
                        'missing GPU IP hardware-init phase snapshot')
            if args.module_kind == 'psp-phase-map':
                psp_phases = [line for line in trace
                              if 'BC250 VCN PSP phase ' in line]
                emit('vcn_psp_phase_trace', psp_phases)
                require(len(psp_phases) >= 7 and
                        all(any(f'BC250 VCN PSP phase {phase}:' in line
                                for line in psp_phases)
                            for phase in ('hw-start-entry', 'after-ring-init',
                                          'after-ring-create', 'after-tmr-load',
                                          'after-hw-start', 'after-non-psp-fw')),
                        'missing PSP startup phase snapshot')
            if args.module_kind in ('direct-bo-powered', 'phase-map',
                                    'ip-phase-map', 'psp-phase-map'):
                direct = [line for line in trace if 'BC250 VCN direct BO:' in line]
                require(len(direct) == 1, 'missing or duplicate direct BO result')
                match = re.search(r'gpu=([0-9a-f]{16}) fw_size=(\d+) '
                                  r'version=([0-9a-f]{8}) power=([0-9a-f]{8}) '
                                  r'pgfsm=([0-9a-f]{8})', direct[0])
                require(match is not None, 'malformed direct BO result')
                direct_result = {'gpu_addr': int(match[1], 16),
                                 'firmware_bytes': int(match[2]),
                                 'version': int(match[3], 16),
                                 'power': int(match[4], 16),
                                 'pgfsm': int(match[5], 16)}
                emit('direct_bo_result', direct_result)
                require(direct_result['gpu_addr'] != 0 and
                        direct_result['firmware_bytes'] == 405952 and
                        direct_result['version'] == 0x0002001b and
                        direct_result['power'] == 0x800 and
                        direct_result['pgfsm'] == 0,
                        'direct BO state differs from pinned powered baseline')
            if args.module_kind in ('psp-bo-fetch', 'psp-bo-premap',
                                    'lmi-latency', 'arbiter-probe',
                                    'clock-gate-probe', 'memory-requests',
                                    'lmi-perfmon', 'mmsch-mode', 'rbc-fetch',
                                    'rbc-control', 'rbc-direct-packet',
                                    'rbc-vcpu-trace'):
                sw_guard_failed = [line for line in trace
                    if 'BC250 PSP/BO address guard failed' in line]
                prefix_failed = [line for line in trace
                    if 'BC250 VCN BO firmware prefix mismatch' in line]
                matched = [line for line in trace
                    if 'BC250 VCN pinned BO and payload matched before PSP write' in line]
                reloads = [line for line in trace
                    if 'BC250 VCN postpower reload:' in line]
                decisions = len(sw_guard_failed) + len(prefix_failed) + len(matched)
                require((1 <= decisions <= 2 if args.module_kind in
                         ('rbc-direct-packet', 'rbc-vcpu-trace')
                         else decisions == 1),
                        'missing or duplicate guarded PSP/BO decision')
                require(len(reloads) <= decisions,
                        'duplicate powered PSP reload')
                reload_result = None
                if reloads:
                    match = re.search(r'ret=(-?\d+) psp_status=([0-9a-f]{8})',
                                      reloads[0])
                    require(match is not None, 'malformed powered PSP reload')
                    reload_result = {'request_return': int(match[1]),
                                     'psp_status': '0x' + match[2]}
                emit('psp_bo_fetch_result', {
                    'address_guard_failed': bool(sw_guard_failed),
                    'payload_guard_failed': bool(prefix_failed),
                    'pinned_bo_and_payload_matched': bool(matched),
                    'powered_psp_reload': reload_result,
                    'vcpu_ready': any('status=00000002' in line
                                      for line in trace if 'trace wait[' in line),
                })
            if args.module_kind == 'arbiter-probe':
                snapshots = {}
                for phase in ('before', 'release', 'wait0'):
                    rows = [line for line in trace if
                            f'BC250 VCN arbiter {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate VCN arbiter {phase} sample')
                    match = re.search(
                        r'arb=([0-9a-f]{8}) mpc=([0-9a-f]{8}) '
                        r'vm=([0-9a-f]{8}) cgc=([0-9a-f]{8})',
                        rows[0])
                    require(match is not None,
                            f'malformed VCN arbiter {phase} sample')
                    snapshots[phase] = {
                        field: int(value, 16)
                        for field, value in zip(('arb', 'mpc', 'vm', 'cgc'),
                                                match.groups())}
                emit('vcn_arbiter_probe', {
                    'snapshots': snapshots,
                    'arbiter_readable': all(
                        snapshot['arb'] != 0xffffffff
                        for snapshot in snapshots.values()),
                    'vcpu_disable_bit_at_wait0': (
                        bool(snapshots['wait0']['arb'] & 0x8)
                        if snapshots['wait0']['arb'] != 0xffffffff else None),
                    'vcpu_drop_bit_at_wait0': (
                        bool(snapshots['wait0']['arb'] & 0x4)
                        if snapshots['wait0']['arb'] != 0xffffffff else None),
                })
            if args.module_kind == 'clock-gate-probe':
                snapshots = {}
                fields = ('vcpu', 'gate', 'ctrl', 'status')
                phases = ('before', 'clock-off', 'clock-restored',
                          'gate-on', 'gate-restored', 'release', 'wait0')
                for phase in phases:
                    rows = [line for line in trace if
                            f'BC250 VCN clock gate {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate VCN clock gate {phase} sample')
                    match = re.search(
                        r'vcpu=([0-9a-f]{8}) gate=([0-9a-f]{8}) '
                        r'ctrl=([0-9a-f]{8}) status=([0-9a-f]{8})',
                        rows[0])
                    require(match is not None,
                            f'malformed VCN clock gate {phase} sample')
                    snapshots[phase] = dict(zip(
                        fields, (int(value, 16) for value in match.groups())))
                before = snapshots['before']
                controls = ('vcpu', 'gate', 'ctrl')
                require(all(snapshots['clock-restored'][field] == before[field]
                            and snapshots['gate-restored'][field] == before[field]
                            for field in controls),
                        'VCN clock controls did not restore')
                vcpu_mask = 0x06000000
                emit('vcn_clock_gate_probe', {
                    'snapshots': snapshots,
                    'vcpu_status_mask': hex(vcpu_mask),
                    'clock_off_control_latched': (
                        snapshots['clock-off']['vcpu'] ==
                        (before['vcpu'] & ~0x200)),
                    'gate_on_control_latched': (
                        snapshots['gate-on']['gate'] ==
                        (before['gate'] | 0x40000)),
                    'clock_off_status_changed': bool(
                        (snapshots['clock-off']['status'] ^
                         before['status']) & vcpu_mask),
                    'gate_on_status_changed': bool(
                        (snapshots['gate-on']['status'] ^
                         before['status']) & vcpu_mask),
                    'interpretation_limit':
                        'Unchanged CGC_STATUS bits do not prove whether the VCPU clock oscillates.',
                })
            if args.module_kind in ('lmi-latency', 'memory-requests',
                                    'lmi-perfmon', 'mmsch-mode', 'rbc-fetch',
                                    'rbc-control', 'rbc-direct-packet',
                                    'rbc-vcpu-trace'):
                snapshots = {}
                fields = ('ctrl', 'lat', 'avg', 'perfctrl', 'countlo',
                          'counthi', 'mpc0', 'mpc1')
                for phase in ('before', 'armed', 'release', 'wait0'):
                    rows = [line for line in trace if
                            f'BC250 VCN LMI monitor {phase}:' in line]
                    require((1 <= len(rows) <= 2 if args.module_kind in
                             ('rbc-direct-packet', 'rbc-vcpu-trace')
                             else len(rows) == 1),
                            f'missing or duplicate LMI {phase} snapshot')
                    match = re.search(
                        r'ctrl=([0-9a-f]{8}) lat=([0-9a-f]{8}) '
                        r'avg=([0-9a-f]{8}) perfctrl=([0-9a-f]{8}) '
                        r'countlo=([0-9a-f]{8}) counthi=([0-9a-f]{8}) '
                        r'mpc0=([0-9a-f]{8}) mpc1=([0-9a-f]{8})',
                        rows[0])
                    require(match is not None,
                            f'malformed LMI {phase} snapshot')
                    snapshots[phase] = {
                        field: int(value, 16)
                        for field, value in zip(fields, match.groups())}
                before = snapshots['before']['ctrl']
                armed = snapshots['armed']['ctrl']
                require(before != 0xffffffff and
                        (armed & 0x700) == 0x700 and
                        (armed & ~0x700) == (before & ~0x700),
                        'VCN LMI latency START fields did not latch')
                emit('vcn_lmi_latency_monitor', {
                    'snapshots': snapshots,
                    'start_bits_latched': True,
                    'vcpu_ready': any('status=00000002' in line
                                      for line in trace if 'trace wait[' in line),
                    'interpretation_limit':
                        'Unchanged latency counters alone cannot prove no fetch '
                        'without a positive transaction control.',
                })
            if args.module_kind in ('memory-requests', 'lmi-perfmon',
                                    'mmsch-mode', 'rbc-fetch', 'rbc-control',
                                    'rbc-direct-packet', 'rbc-vcpu-trace'):
                rows = [line for line in trace
                        if 'BC250 VCN LMI requests:' in line]
                require((1 <= len(rows) <= 2 if args.module_kind in
                         ('rbc-direct-packet', 'rbc-vcpu-trace')
                         else len(rows) == 1),
                        'missing or duplicate LMI request sample')
                match = re.search(
                    r'samples=(\d+) before=([0-9a-f]{8}) first=([0-9a-f]{8}) '
                    r'last=([0-9a-f]{8}) and=([0-9a-f]{8}) or=([0-9a-f]{8}) '
                    r'transitions=(\d+) latency=([0-9a-f]{8}) '
                    r'pc=([0-9a-f]{8}) pf=([0-9a-f]{8})', rows[0])
                require(match is not None, 'malformed LMI request sample')
                samples, before, first, last, bit_and, bit_or, changes, lat, pc, pf = (
                    int(value, 10 if index in (0, 6) else 16)
                    for index, value in enumerate(match.groups()))
                require(samples == 4096 and first == before,
                        'LMI request sample geometry changed')
                read_clean_mask = 0x3311
                emit('vcn_lmi_memory_requests', {
                    'samples': samples,
                    'before': hex(before), 'last': hex(last),
                    'bitwise_and': hex(bit_and), 'bitwise_or': hex(bit_or),
                    'transitions': changes, 'latency': hex(lat),
                    'vcpu_pc': hex(pc), 'vcpu_page_fault': hex(pf),
                    'read_clean_mask': hex(read_clean_mask),
                    'read_clean_bit_fell': bool((before & read_clean_mask) &
                                                ~(bit_and & read_clean_mask)),
                    'interpretation_limit':
                        'A clean-bit fall is evidence of an in-flight request; '
                        'no fall does not prove that no read was attempted.',
                })
            if args.module_kind == 'rbc-fetch':
                pre = [line for line in trace
                       if 'BC250 VCN RBC pre:' in line]
                mapped = [line for line in trace
                          if 'BC250 VCN RBC mapped:' in line]
                fetched = [line for line in trace
                           if 'BC250 VCN RBC fetch:' in line]
                skipped = [line for line in trace
                           if 'BC250 VCN RBC guard skipped' in line]
                require(len(pre) == 1 and len(skipped) <= 1,
                        'missing or duplicate RBC preflight')
                if skipped:
                    require(not mapped and not fetched,
                            'RBC guard skip included writes')
                    emit('vcn_rbc_fetch', {'guard_skipped': True,
                                            'preflight': pre[0]})
                else:
                    require(len(mapped) == len(fetched) == 1,
                            'missing or duplicate RBC fetch sample')
                    match = re.search(
                        r'run=([0-9a-f]{8}) cntl=([0-9a-f]{8}) '
                        r'wptr=([0-9a-f]{8}) first=([0-9a-f]{8}) '
                        r'last=([0-9a-f]{8}) max=([0-9a-f]{8}) '
                        r'rptr_changes=(\d+) lmi_first=([0-9a-f]{8}) '
                        r'lmi_and=([0-9a-f]{8}) lmi_or=([0-9a-f]{8}) '
                        r'lmi_changes=(\d+) latency=([0-9a-f]{8}) '
                        r'status=([0-9a-f]{8}) pf=([0-9a-f]{8})',
                        fetched[0])
                    require(match is not None, 'malformed RBC fetch sample')
                    values = [int(value, 10 if i in (6, 10) else 16)
                              for i, value in enumerate(match.groups())]
                    (run, control, wptr, first, last, maximum, changes,
                     lmi_first, lmi_and, lmi_or, lmi_changes, latency,
                     status, fault) = values
                    mapped_match = re.search(
                        r'expected=([0-9a-f]{8}) observed=([0-9a-f]{8})',
                        mapped[0])
                    require(mapped_match is not None and
                            int(mapped_match[1], 16) ==
                            int(mapped_match[2], 16),
                            'RBC configuration failed to latch')
                    emit('vcn_rbc_fetch', {
                        'guard_skipped': False,
                        'control': hex(control),
                        'run_control': hex(run),
                        'wptr': wptr, 'rptr_first': first,
                        'rptr_last': last, 'rptr_max': maximum,
                        'rptr_transitions': changes,
                        'rptr_advanced': maximum >= 16 and first <= 16,
                        'lmi_first': hex(lmi_first),
                        'lmi_and': hex(lmi_and), 'lmi_or': hex(lmi_or),
                        'lmi_changes': lmi_changes,
                        'latency': hex(latency),
                        'uvd_status': hex(status),
                        'vcpu_page_fault': hex(fault),
                        'interpretation_limit':
                            'A matching ring read-pointer advance is evidence '
                            'that the VCN ring consumed the aligned NOP packets; '
                            'a stationary pointer does not prove no transient '
                            'memory request was issued.',
                    })
            if args.module_kind in ('rbc-control', 'rbc-direct-packet',
                                    'rbc-vcpu-trace'):
                result_event = {
                    'rbc-control': 'vcn_rbc_control',
                    'rbc-direct-packet': 'vcn_rbc_direct_packet',
                    'rbc-vcpu-trace': 'vcn_rbc_vcpu_trace',
                }[args.module_kind]
                pre = [line for line in trace
                       if 'BC250 VCN RBC pre:' in line]
                mapped = [line for line in trace
                          if 'BC250 VCN RBC control mapped:' in line]
                held = [line for line in trace
                        if 'BC250 VCN RBC control hold:' in line]
                executed = [line for line in trace
                            if 'BC250 VCN RBC control execute:' in line]
                skipped = [line for line in trace
                           if 'BC250 VCN RBC guard skipped' in line]
                if args.module_kind in ('rbc-direct-packet',
                                        'rbc-vcpu-trace'):
                    require(1 <= len(pre) <= 2 and
                            len(skipped) == len(pre) - 1 and
                            len(mapped) == len(held) == len(executed) == 1,
                            'unexpected RBC direct packet retry sequence')
                else:
                    require(len(pre) == 1 and len(skipped) <= 1,
                            'missing or duplicate RBC control preflight')
                if skipped and args.module_kind == 'rbc-control':
                    require(not mapped and not held and not executed,
                            'RBC control guard skip included writes')
                    emit(result_event, {'guard_skipped': True,
                                        'preflight': pre[0]})
                else:
                    require(len(mapped) == len(held) == len(executed) == 1,
                            'missing or duplicate RBC control snapshots')
                    map_match = re.search(
                        r'expected=([0-9a-f]{8}) observed=([0-9a-f]{8}) '
                        r'bar=([0-9a-f]{16}) rptr=([0-9a-f]{8}) '
                        r'wptr=([0-9a-f]{8}) scratch=([0-9a-f]{8})',
                        mapped[0])
                    hold_match = re.search(
                        r'cntl=([0-9a-f]{8}) wptr=([0-9a-f]{8}) '
                        r'rptr=([0-9a-f]{8}) scratch=([0-9a-f]{8}) '
                        r'lmi=([0-9a-f]{8}) latency=([0-9a-f]{8})',
                        held[0])
                    exec_match = re.search(
                        r'cntl=([0-9a-f]{8}) wptr=([0-9a-f]{8}) '
                        r'first=([0-9a-f]{8}) last=([0-9a-f]{8}) '
                        r'max=([0-9a-f]{8}) rptr_changes=(\d+) '
                        r'scratch=([0-9a-f]{8}) lmi_first=([0-9a-f]{8}) '
                        r'lmi_and=([0-9a-f]{8}) lmi_or=([0-9a-f]{8}) '
                        r'lmi_changes=(\d+) latency=([0-9a-f]{8}) '
                        r'status=([0-9a-f]{8}) pf=([0-9a-f]{8})',
                        executed[0])
                    require(map_match and hold_match and exec_match,
                            'malformed RBC control snapshot')
                    map_values = [int(value, 16) for value in map_match.groups()]
                    hold_values = [int(value, 16) for value in hold_match.groups()]
                    exec_values = [int(value, 10 if i in (5, 10) else 16)
                                   for i, value in enumerate(exec_match.groups())]
                    require(map_values[0] == map_values[1] == 0x1101010c and
                            map_values[2:] == [0x264000, 0, 0, 0xcafedead],
                            'RBC control mapping differs from pinned baseline')
                    require(hold_values[0] == 0x1001010c and
                            exec_values[0] == 0x1000010c and
                            hold_values[1] == exec_values[1] == 16,
                            'RBC control register state differs from expected')
                    emit(result_event, {
                        'guard_skipped': False,
                        'hold': {'control': hex(hold_values[0]),
                                 'write_pointer': hold_values[1],
                                 'read_pointer': hold_values[2],
                                 'scratch': hex(hold_values[3]),
                                 'lmi_status': hex(hold_values[4]),
                                 'latency': hex(hold_values[5])},
                        'execute': {'control': hex(exec_values[0]),
                                    'write_pointer': exec_values[1],
                                    'read_pointer_first': exec_values[2],
                                    'read_pointer_last': exec_values[3],
                                    'read_pointer_max': exec_values[4],
                                    'read_pointer_changes': exec_values[5],
                                    'scratch': hex(exec_values[6]),
                                    'lmi_first': hex(exec_values[7]),
                                    'lmi_and': hex(exec_values[8]),
                                    'lmi_or': hex(exec_values[9]),
                                    'lmi_changes': exec_values[10],
                                    'latency': hex(exec_values[11]),
                                    'uvd_status': hex(exec_values[12]),
                                    'page_fault': hex(exec_values[13])},
                        'command_executed': hold_values[2] == 0 and
                            hold_values[3] == 0xcafedead and
                            exec_values[4] >= 16 and
                            exec_values[6] == 0xdeadbeef,
                    })
            if args.module_kind == 'rbc-vcpu-trace':
                snapshots = {}
                for phase in ('pre', 'hold', 'execute'):
                    rows = [line for line in trace if
                            f'BC250 VCN RBC VCPU trace {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate RBC VCPU trace {phase}')
                    match = re.search(
                        r'cntl=([0-9a-f]{8}) pc=([0-9a-f]{8}) '
                        r'status=([0-9a-f]{8})', rows[0])
                    require(match is not None,
                            f'malformed RBC VCPU trace {phase}')
                    snapshots[phase] = dict(zip(
                        ('vcpu_control', 'pc_trace', 'uvd_status'),
                        (int(value, 16) for value in match.groups())))
                    if phase == 'pre':
                        packet = re.search(
                            r'packet=([0-9a-f]{8}) value=([0-9a-f]{8})',
                            rows[0])
                        require(packet is not None and
                                (int(packet[1], 16), int(packet[2], 16)) ==
                                (0x0000c258, 0x0ff20600),
                                'RBC VCPU trace packet differs from pinned value')
                    if phase == 'execute':
                        scratch = re.search(r'scratch=([0-9a-f]{8})', rows[0])
                        require(scratch is not None,
                                'RBC VCPU trace scratch result missing')
                        snapshots[phase]['scratch'] = int(scratch[1], 16)
                require(snapshots['pre']['vcpu_control'] == 0x0ff20200 and
                        snapshots['hold']['vcpu_control'] == 0x0ff20200,
                        'VCN VCPU control changed during NO_FETCH control')
                emit('vcn_vcpu_trace_packet', {
                    'snapshots': snapshots,
                    'trace_bit_latched': bool(
                        snapshots['execute']['vcpu_control'] & 0x400),
                    'pc_trace_changed': (
                        snapshots['execute']['pc_trace'] !=
                        snapshots['pre']['pc_trace']),
                    'vcpu_ready': bool(
                        snapshots['execute']['uvd_status'] & 2),
                    'scratch_packet_executed': (
                        snapshots['execute']['scratch'] == 0xdeadbeef),
                })
            if args.module_kind in ('rbc-vcpu-clock',
                                    'rbc-vcpu-clock-internal',
                                    'rbc-vcpu-clock-mapped'):
                phase_prefix = {
                    'rbc-vcpu-clock': 'BC250 VCN RBC VCPU clock',
                    'rbc-vcpu-clock-internal':
                        'BC250 VCN RBC VCPU internal clock',
                    'rbc-vcpu-clock-mapped':
                        'BC250 VCN RBC VCPU mapped clock',
                }[args.module_kind]
                if args.module_kind == 'rbc-vcpu-clock-mapped':
                    pre = [line for line in trace
                           if f'{phase_prefix} pre:' in line]
                    require(len(pre) == 1,
                            'missing or duplicate mapped packet preflight')
                    packet = re.search(
                        r'packet=([0-9a-f]{8}) value=([0-9a-f]{8})',
                        pre[0])
                    require(packet is not None and
                            (int(packet[1], 16), int(packet[2], 16)) ==
                            (0x000001d8, 0x0ff20000),
                            'mapped VCPU clock packet differs from pin')
                snapshots = {}
                for phase in ('first', 'second'):
                    rows = [line for line in trace if
                            f'{phase_prefix} {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate RBC VCPU clock {phase}')
                    match = re.search(
                        r'cntl=([0-9a-f]{8}) rptr=([0-9a-f]{8}) '
                        r'scratch=([0-9a-f]{8}) status=([0-9a-f]{8})',
                        rows[0])
                    require(match is not None,
                            f'malformed RBC VCPU clock {phase}')
                    snapshots[phase] = dict(zip(
                        ('vcpu_control', 'ring_read_pointer', 'scratch',
                         'uvd_status'),
                        (int(value, 16) for value in match.groups())))
                emit({
                    'rbc-vcpu-clock': 'vcn_rbc_vcpu_clock',
                    'rbc-vcpu-clock-internal': 'vcn_rbc_vcpu_clock_internal',
                    'rbc-vcpu-clock-mapped': 'vcn_rbc_vcpu_clock_mapped',
                }[args.module_kind], {
                    'snapshots': snapshots,
                    'first_packet_executed': (
                        snapshots['first']['ring_read_pointer'] == 16 and
                        snapshots['first']['scratch'] == 0x11112222),
                    'second_packet_executed': (
                        snapshots['second']['ring_read_pointer'] == 32 and
                        snapshots['second']['scratch'] == 0x33334444),
                    'clock_off_latched': (
                        snapshots['first']['vcpu_control'] == 0x0ff20000),
                    'clock_restored_by_ring': (
                        snapshots['second']['vcpu_control'] == 0x0ff20200),
                    'host_restore_used': any(
                        f'{phase_prefix} host restore:' in line
                        for line in trace),
                })
            if args.module_kind == 'rbc-vcpu-trace-mapped':
                prefix = 'BC250 VCN RBC VCPU mapped trace'
                pre = [line for line in trace if f'{prefix} pre:' in line]
                first = [line for line in trace if f'{prefix} first:' in line]
                sample = [line for line in trace if f'{prefix} sample:' in line]
                second = [line for line in trace if f'{prefix} second:' in line]
                require(all(len(rows) == 1 for rows in
                            (pre, first, sample, second)),
                        'missing or duplicate mapped VCPU trace sample')
                packet = re.search(
                    r'packet=([0-9a-f]{8}) value=([0-9a-f]{8})', pre[0])
                require(packet is not None and
                        (int(packet[1], 16), int(packet[2], 16)) ==
                        (0x000001d8, 0x0ff20600),
                        'mapped VCPU trace packet differs from pin')
                phases = {}
                for name, row in (('first', first[0]),
                                  ('second', second[0])):
                    match = re.search(
                        r'cntl=([0-9a-f]{8}) rptr=([0-9a-f]{8}) '
                        r'scratch=([0-9a-f]{8}) status=([0-9a-f]{8})', row)
                    require(match is not None,
                            f'malformed mapped VCPU trace {name}')
                    phases[name] = [int(value, 16)
                                    for value in match.groups()]
                sampled = re.search(
                    r'first=([0-9a-f]{8}) last=([0-9a-f]{8}) '
                    r'and=([0-9a-f]{8}) or=([0-9a-f]{8}) '
                    r'changes=(\d+) cntl=([0-9a-f]{8}) '
                    r'status=([0-9a-f]{8}) pf=([0-9a-f]{8})',
                    sample[0])
                require(sampled is not None, 'malformed mapped VCPU PC sample')
                pc_first, pc_last, pc_and, pc_or, pc_changes, \
                    sample_cntl, sample_status, fault = (
                        int(value, 10 if i == 4 else 16)
                        for i, value in enumerate(sampled.groups()))
                require(phases['first'][1:3] == [16, 0x11112222] and
                        phases['second'][1:3] == [32, 0x33334444] and
                        phases['second'][0] == 0x0ff20200,
                        'mapped trace packet marker or restore differs')
                emit('vcn_rbc_vcpu_trace_mapped', {
                    'first_control': hex(phases['first'][0]),
                    'sample_control': hex(sample_cntl),
                    'second_control': hex(phases['second'][0]),
                    'trace_bit_latched': phases['first'][0] == 0x0ff20600,
                    'pc_first': hex(pc_first), 'pc_last': hex(pc_last),
                    'pc_and': hex(pc_and), 'pc_or': hex(pc_or),
                    'pc_changes': pc_changes,
                    'first_status': hex(phases['first'][3]),
                    'second_status': hex(phases['second'][3]),
                    'sample_status': hex(sample_status),
                    'page_fault': hex(fault),
                    'host_restore_used': any(
                        f'{prefix} host restore:' in line for line in trace),
                })
            if args.module_kind in ('rbc-vcpu-reset-mapped', 'rbc-cache-map'):
                prefix = ('BC250 VCN RBC cache map'
                          if args.module_kind == 'rbc-cache-map'
                          else 'BC250 VCN RBC VCPU mapped reset')
                rows = {}
                for phase in ('pre', 'first', 'sample', 'second'):
                    found = [line for line in trace
                             if f'{prefix} {phase}:' in line]
                    require(len(found) == 1,
                            f'missing or duplicate mapped VCPU reset {phase}')
                    rows[phase] = found[0]
                packet = re.search(
                    r'packet=([0-9a-f]{8}) value=([0-9a-f]{8})', rows['pre'])
                require(packet is not None and
                        (int(packet[1], 16), int(packet[2], 16)) ==
                        (0x000001e0, 0x00000008),
                        'mapped VCPU reset packet differs from pin')
                phases = {}
                for phase in ('first', 'second'):
                    match = re.search(
                        r'cntl=([0-9a-f]{8}) rptr=([0-9a-f]{8}) '
                        r'scratch=([0-9a-f]{8}) status=([0-9a-f]{8})',
                        rows[phase])
                    require(match is not None,
                            f'malformed mapped VCPU reset {phase}')
                    phases[phase] = [int(value, 16)
                                     for value in match.groups()]
                sampled = re.search(
                    r'first=([0-9a-f]{8}) last=([0-9a-f]{8}) '
                    r'and=([0-9a-f]{8}) or=([0-9a-f]{8}) '
                    r'changes=(\d+) prid=([0-9a-f]{8}) '
                    r'pc=([0-9a-f]{8}) reset=([0-9a-f]{8}) '
                    r'pf=([0-9a-f]{8})', rows['sample'])
                require(sampled is not None,
                        'malformed mapped VCPU reset status sample')
                status_first, status_last, status_and, status_or, changes, \
                    prid, pc, reset, fault = (
                        int(value, 10 if i == 4 else 16)
                        for i, value in enumerate(sampled.groups()))
                cache_host = None
                if args.module_kind == 'rbc-cache-map':
                    host = [line for line in trace
                            if f'{prefix} host read:' in line]
                    require(len(host) == 1,
                            'missing or duplicate ring cache host read')
                    match = re.search(
                        r'high=([0-9a-f]{8}) low=([0-9a-f]{8}) '
                        r'offset=([0-9a-f]{8}) size=([0-9a-f]{8})',
                        host[0])
                    require(match is not None, 'malformed ring cache host read')
                    cache_host = {key: hex(int(value, 16)) for key, value in
                                  zip(('high', 'low', 'offset', 'size'),
                                      match.groups())}
                emit(('vcn_rbc_cache_map' if args.module_kind == 'rbc-cache-map'
                      else 'vcn_rbc_vcpu_reset_mapped'), {
                    'first_control': hex(phases['first'][0]),
                    'first_read_pointer': phases['first'][1],
                    'first_scratch': hex(phases['first'][2]),
                    'first_status': hex(phases['first'][3]),
                    'second_control': hex(phases['second'][0]),
                    'second_read_pointer': phases['second'][1],
                    'second_scratch': hex(phases['second'][2]),
                    'second_status': hex(phases['second'][3]),
                    'both_packet_markers_executed':
                        phases['first'][1:3] == [16, 0x11112222] and
                        phases['second'][1:3] == [32, 0x33334444],
                    'sample_status_first': hex(status_first),
                    'sample_status_last': hex(status_last),
                    'sample_status_and': hex(status_and),
                    'sample_status_or': hex(status_or),
                    'sample_status_changes': changes,
                    'vcpu_ready_seen': bool(status_or & 2),
                    'processor_id': hex(prid), 'pc_trace': hex(pc),
                    'reset_host_readback': hex(reset),
                    'cache_host_readback': cache_host,
                    'page_fault': hex(fault),
                    'host_clock_restore_used': any(
                        f'{prefix} host restore:' in line for line in trace),
                })
            if args.module_kind == 'rbc-cache-readback':
                prefix = 'BC250 VCN RBC cache oracle '

                def oracle_row(label, pattern):
                    rows = [line for line in trace
                            if f'{prefix}{label}:' in line]
                    require(rows, f'missing ring cache oracle {label}')
                    matched = re.search(pattern, rows[0])
                    require(matched is not None,
                            f'malformed ring cache oracle {label}')
                    return matched.groups(), len(rows)

                first, first_count = oracle_row(
                    'first',
                    r'rptr=([0-9a-f]{8}) scratch=([0-9a-f]{8}) '
                    r'status=([0-9a-f]{8})')
                second, second_count = oracle_row(
                    'second',
                    r'rptr=([0-9a-f]{8}) scratch=([0-9a-f]{8}) '
                    r'status=([0-9a-f]{8})')
                sentinel, sentinel_count = oracle_row(
                    'sentinel',
                    r'ret=(-?\d+) psp=([0-9a-f]{8}) '
                    r'scratch=([0-9a-f]{8}) rptr=([0-9a-f]{8}) '
                    r'marker=([0-9a-f]{8})')
                restored, restored_count = oracle_row(
                    'restored',
                    r'ret=(-?\d+) psp=([0-9a-f]{8}) '
                    r'scratch=([0-9a-f]{8}) rptr=([0-9a-f]{8}) '
                    r'marker=([0-9a-f]{8})')
                replay, replay_count = oracle_row(
                    'signed replay', r'ret=(-?\d+) psp=([0-9a-f]{8})')
                require(int(first[0], 16) == int(sentinel[3], 16) == 16 and
                        int(first[1], 16) == int(sentinel[4], 16) ==
                        0x11112222 and
                        int(second[0], 16) == int(restored[3], 16) == 32 and
                        int(second[1], 16) == int(restored[4], 16) ==
                        0x33334444,
                        'ring markers or read pointers changed during PSP reads')
                emit('vcn_rbc_cache_readback', {
                    'sentinel_psp_status': '0x' + sentinel[1],
                    'sentinel_observed': int(sentinel[1], 16) == 0x71363000,
                    'restored_psp_status': '0x' + restored[1],
                    'restore_observed': int(restored[1], 16) == 0x70000010,
                    'sentinel_request_return': int(sentinel[0]),
                    'restore_request_return': int(restored[0]),
                    'scratch_restored': int(sentinel[2], 16) ==
                        int(restored[2], 16) == 0,
                    'signed_replay_return': int(replay[0]),
                    'signed_replay_status': '0x' + replay[1],
                    'ring_first_status': '0x' + first[2],
                    'ring_second_status': '0x' + second[2],
                    'report_counts': [first_count, second_count,
                                      sentinel_count, restored_count,
                                      replay_count],
                })
            if args.module_kind == 'mmsch-mode':
                pre = [line for line in trace
                       if 'BC250 MMSCH mode pre:' in line]
                release = [line for line in trace
                           if 'BC250 MMSCH mode release:' in line]
                require(len(pre) == len(release) == 1,
                        'missing or duplicate MMSCH mode readback')
                pre_match = re.search(
                    r'before=([0-9a-f]{8}) candidate=([0-9a-f]{8}) '
                    r'after=([0-9a-f]{8}) status=([0-9a-f]{8}) '
                    r'reset2=([0-9a-f]{8}) report=([0-9a-f]{8}) '
                    r'lmi=([0-9a-f]{8})', pre[0])
                release_match = re.search(
                    r'ctrl=([0-9a-f]{8}) status=([0-9a-f]{8}) '
                    r'reset2=([0-9a-f]{8}) report=([0-9a-f]{8}) '
                    r'lmi=([0-9a-f]{8}) uvd=([0-9a-f]{8})', release[0])
                require(pre_match is not None and release_match is not None,
                        'malformed MMSCH mode readback')
                before, candidate, after, status, reset2, report, lmi = (
                    int(value, 16) for value in pre_match.groups())
                ctrl2, status2, reset22, report2, lmi2, uvd = (
                    int(value, 16) for value in release_match.groups())
                require(before == 0x8000018c and candidate == 0x18c and
                        after == candidate and ctrl2 == candidate,
                        'MMSCH mode bit failed to clear or remain clear')
                emit('vcn_mmsch_mode_trial', {
                    'before': hex(before), 'after': hex(after),
                    'pre': {'clock_status': hex(status),
                            'reset2': hex(reset2), 'report': hex(report),
                            'lmi_status': hex(lmi)},
                    'post_sample': {'clock_status': hex(status2),
                                    'reset2': hex(reset22),
                                    'report': hex(report2),
                                    'lmi_status': hex(lmi2),
                                    'uvd_status': hex(uvd)},
                    'vcpu_ready': any('status=00000002' in line
                                      for line in trace
                                      if 'trace wait[' in line),
                })
            if args.module_kind == 'lmi-perfmon':
                armed = [line for line in trace
                         if 'BC250 VCN perfmon armed:' in line]
                released = [line for line in trace
                            if 'BC250 VCN perfmon release:' in line]
                finished = [line for line in trace
                            if 'BC250 VCN perfmon done:' in line]
                selectors = [line for line in trace
                             if 'BC250 VCN perfmon selector=' in line]
                require(len(armed) == len(released) == len(finished) == 1 and
                        len(selectors) == 31,
                        'missing or duplicate LMI perfmon snapshots')
                snapshot_pattern = re.compile(
                    r'ctrl=([0-9a-f]{8}) lo=([0-9a-f]{8}) '
                    r'hi=([0-9a-f]{8}) credits=([0-9a-f]{8}) '
                    r'sph=([0-9a-f]{8})')
                snapshots = {}
                for phase, row in (('armed', armed[0]),
                                   ('release', released[0])):
                    match = snapshot_pattern.search(row)
                    require(match is not None,
                            f'malformed LMI perfmon {phase} snapshot')
                    snapshots[phase] = {
                        name: int(value, 16)
                        for name, value in zip(
                            ('ctrl', 'lo', 'hi', 'credits', 'sph'),
                            match.groups())}
                require(snapshots['armed']['ctrl'] == 1 and
                        snapshots['release']['ctrl'] == 2,
                        'LMI perfmon state control did not latch')
                selected = {}
                for row in selectors:
                    match = re.search(
                        r'selector=(\d+) ctrl=([0-9a-f]{8}) '
                        r'lo=([0-9a-f]{8}) hi=([0-9a-f]{8})', row)
                    require(match is not None, 'malformed LMI perfmon selector')
                    selector = int(match[1])
                    control, lo, hi = (int(value, 16)
                                       for value in match.groups()[1:])
                    require(1 <= selector < 32 and
                            selector not in selected and
                            control == (selector << 8 | 2),
                            'LMI perfmon selector control mismatch')
                    selected[selector] = (hi << 32) | lo
                require(set(selected) == set(range(1, 32)),
                        'LMI perfmon selector coverage incomplete')
                done_match = re.search(
                    r'nonzero_selectors=(\d+) restored=([0-9a-f]{8}) '
                    r'credits=([0-9a-f]{8}) sph=([0-9a-f]{8})',
                    finished[0])
                require(done_match is not None and
                        int(done_match[1]) == sum(value != 0
                                                  for value in selected.values())
                        and int(done_match[2], 16) == 0,
                        'LMI perfmon did not restore or counts disagree')
                emit('vcn_lmi_perfmon', {
                    'snapshots': snapshots,
                    'selector_counts': {str(k): v for k, v in selected.items()},
                    'post_scan_credits': int(done_match[3], 16),
                    'post_scan_sph': int(done_match[4], 16),
                    'interpretation_limit':
                        'VCN 2.0 selector event meanings are unverified. '
                        'A zero count does not establish zero memory requests '
                        'without an independently calibrated event.',
                })
            if args.module_kind == 'psp-bo-premap':
                reports = [line for line in trace
                           if 'BC250 VCN delayed BO map:' in line]
                require(len(reports) == 1,
                        'missing or duplicate delayed BO map report')
                match = re.search(
                    r'ret=(-?\d+) psp=([0-9a-f]{8}) low28=([0-9a-f]{8}) '
                    r'scratch=([0-9a-f]{8}) status=([0-9a-f]{8})',
                    reports[0])
                require(match is not None, 'malformed delayed BO map report')
                psp_status = int(match[2], 16)
                emit('psp_bo_map_persistence', {
                    'request_return': int(match[1]),
                    'psp_status': '0x' + match[2],
                    'scratch_restored': int(match[4], 16) == 0,
                    'after_first_vcpu_wait': int(match[5], 16) == 4,
                    'before_map_replay': True,
                    'all_sixteen_windows_matched': psp_status == 0x70000010,
                })
            if args.module_kind in ('postrelease-measure', 'crosspath-scratch',
                                    'dpg-bank-survey'):
                scratch_reached = True
                if args.module_kind in ('crosspath-scratch', 'dpg-bank-survey'):
                    routes = [line for line in trace
                              if 'BC250 VCN scratch routes:' in line]
                    require(len(routes) == 1,
                            'missing or duplicate BAR/SOC15 route control')
                    route_match = re.search(r'soc15=([0-9a-f]{8}) '
                                            r'bar=([0-9a-f]{8})', routes[0])
                    require(route_match is not None,
                            'malformed BAR/SOC15 route control')
                    emit('host_scratch_routes', {
                        'soc15': '0x' + route_match[1],
                        'absolute_bar': '0x' + route_match[2],
                    })
                    before = [line for line in trace
                              if 'BC250 VCN scratch before PSP:' in line]
                    after = [line for line in trace
                             if 'BC250 VCN scratch after PSP:' in line]
                    if not before and not after:
                        skipped = [line for line in trace if
                                   'BC250 VCN scratch baseline differs:' in line]
                        require(len(skipped) == 1,
                                'host scratch stopped without a baseline report')
                        scratch_reached = False
                        emit('host_scratch_unavailable', {
                            'absolute_bar': '0x' + route_match[2],
                            'psp_read_attempted': False,
                        })
                    else:
                        require(len(before) == len(after) == 1,
                                'missing or duplicate host scratch control')
                        require('00000000/5a13c0de' in before[0] and
                                after[0].endswith('00000000'),
                                'host VCN scratch control did not restore')
                        emit('host_psp_scratch_control', {
                            'before': '0x00000000',
                            'during': '0x5a13c0de',
                            'after': '0x00000000',
                            'psp_expected_low28': '0x0a13c0de',
                        })
                if scratch_reached:
                    reports = [line for line in trace
                               if 'BC250 VCN postrelease reload:' in line]
                    require(len(reports) == 1,
                            'missing or duplicate PSP postrelease report')
                    match = re.search(r'ret=(-?\d+) psp_status=([0-9a-f]{8}) '
                                      r'status=([0-9a-f]{8})', reports[0])
                    require(match is not None, 'malformed PSP postrelease report')
                    psp_status = int(match[2], 16)
                    result_event = ('psp_postrelease_reset'
                                    if args.module_kind == 'postrelease-measure'
                                    else 'psp_postrelease_readback')
                    result_data = {
                        'request_return': int(match[1]),
                        'psp_status': hex(psp_status),
                        'diagnostic_low28': (psp_status & 0x0fffffff
                                             if psp_status >> 28 == 7 else None),
                        'vcn_status': int(match[3], 16),
                    }
                    if args.module_kind == 'postrelease-measure':
                        result_data['reset_low28'] = result_data['diagnostic_low28']
                    else:
                        result_data['register'] = 'mmUVD_SCRATCH1'
                    emit(result_event, result_data)
                    if args.module_kind in ('crosspath-scratch', 'dpg-bank-survey'):
                        emit('psp_host_scratch_comparison', {
                            'psp_status': hex(psp_status),
                            'psp_low28': (hex(psp_status & 0x0fffffff)
                                          if psp_status >> 28 == 7 else None),
                            'host_low28': '0x0a13c0de',
                            'matches': psp_status == 0x7a13c0de,
                        })
                    if args.module_kind == 'dpg-bank-survey':
                        require(psp_status == 0x7a13c0de,
                                'PSP did not read the phase-matched VCN scratch sentinel')
                        bank = {}
                        for phase in ('pre', 'post'):
                            row = [line for line in trace if
                                   f'BC250 VCN DPG bank {phase}:' in line]
                            require(len(row) == 1,
                                    f'missing or duplicate DPG {phase} bank sample')
                            match = re.search(
                                r'low=([0-9a-f]{8}) high=([0-9a-f]{8}) '
                                r'off0=([0-9a-f]{8}) vmid=([0-9a-f]{8}) '
                                r'report=([0-9a-f]{8}) rawlow=([0-9a-f]{8})',
                                row[0])
                            require(match is not None,
                                    f'malformed DPG {phase} bank sample')
                            fields = ('low', 'high', 'off0', 'vmid', 'report',
                                      'rawlow')
                            bank[phase] = {field: '0x' + value for field, value
                                           in zip(fields, match.groups())}
                            require(bank[phase]['low'] == bank[phase]['rawlow'],
                                    f'SOC15/raw DPG {phase} routes differ')
                            row = [line for line in trace if
                                   f'BC250 VCN standard bank {phase}:' in line]
                            require(len(row) == 1,
                                    f'missing or duplicate standard {phase} bank sample')
                            match = re.search(
                                r'low=([0-9a-f]{8}) reset=([0-9a-f]{8}) '
                                r'reset2=([0-9a-f]{8}) vcpu=([0-9a-f]{8})',
                                row[0])
                            require(match is not None,
                                    f'malformed standard {phase} bank sample')
                            fields = ('low', 'reset', 'reset2', 'vcpu')
                            bank[phase]['standard'] = {
                                field: '0x' + value for field, value
                                in zip(fields, match.groups())}
                        emit('vcn_dpg_bank_survey', bank)
            if args.module_kind in ('delayed-reset', 'delayed-cache-size0'):
                cache_sample = args.module_kind == 'delayed-cache-size0'
                post = [line for line in trace
                        if 'BC250 VCN postrelease reload:' in line]
                delayed = [line for line in trace
                           if ('BC250 VCN delayed cache-size0:' if cache_sample
                               else 'BC250 VCN delayed reset:') in line]
                wait = [line for line in trace
                        if 'BC250 VCN trace wait[0]:' in line]
                require(len(post) == len(delayed) == len(wait) == 1,
                        'missing or duplicate delayed-reset phase')
                require('ret=0 psp_status=00000000 status=00000004' in post[0]
                        and 'status=00000004' in wait[0],
                        'initial cache map or VCPU wait changed')
                match = re.search(
                    r'ret=(-?\d+) psp=([0-9a-f]{8}) low28=([0-9a-f]{8}) '
                    r'scratch=([0-9a-f]{8}) status=([0-9a-f]{8})', delayed[0])
                require(match is not None, 'malformed delayed-reset report')
                psp_status = int(match[2], 16)
                require(psp_status >> 28 == 7 and
                        int(match[3], 16) == (psp_status & 0x0fffffff) and
                        int(match[4], 16) == 0 and
                        int(match[5], 16) == 4,
                        'delayed PSP reset/scratch report differs')
                emit('delayed_vcn_cache_size0_read' if cache_sample
                     else 'delayed_vcn_reset_read', {
                    'request_return': int(match[1]),
                    'psp_status': hex(psp_status),
                    ('cache_size0_low28' if cache_sample else 'reset_low28'):
                        hex(psp_status & 0x0fffffff),
                    'scratch_restored': True,
                    'after_first_vcpu_wait': True,
                    'before_host_retry': True,
                })
            if args.module_kind == 'relocation-control':
                post = [line for line in trace
                        if 'BC250 VCN postrelease reload:' in line]
                require(len(post) == 1 and
                        'ret=0 psp_status=00000000 status=00000004' in post[0],
                        'relocated cache-address table did not complete PSP reload')
                before = [line for line in trace
                          if 'BC250 VCN scratch before PSP:' in line]
                after = [line for line in trace
                         if 'BC250 VCN scratch after PSP:' in line]
                require(len(before) == len(after) == 1 and
                        '00000000/5a13c0de' in before[0] and
                        after[0].endswith('00000000'),
                        'relocation-control scratch marker did not restore')
                emit('vcn_map_relocation_control', {
                    'psp_reload_return': 0,
                    'psp_status': 0,
                    'relocated_address_table_loaded': True,
                    'vcpu_ready_claimed': False,
                })
            emit('result', {'gpu_bound': (clock.GPU/'driver').exists(),
                            'insmod_returncode': result.returncode,
                            'hardware_decode_verified': False,
                            'cold_cycle_required': True})
        except BaseException as error:
            emit('error', {'detail': repr(error), 'cold_cycle_required': True})
            raise
        finally:
            smu.close()
            emit('cleanup', {'sram_undo_attempted': False,
                             'clock_restored': False,
                             'cold_cycle_required': True})


if __name__ == '__main__':
    main()
