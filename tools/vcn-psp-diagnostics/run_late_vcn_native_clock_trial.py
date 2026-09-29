#!/usr/bin/env python3
"""Pair the native SMU VCN clock with one pinned opt-in decoder startup.

Run only on the isolated diagnostic boot with an armed Pi PDU recovery timer.
The clock-table generation is never rolled back. A second same-boot amdgpu
probe stalled after the first module was unloaded, even though SMU state was
retained; start another module only after a cold cycle. No BIOS EEPROM or Pico
QSPI flash write is involved.
"""

import argparse
import fcntl
import hashlib
import inspect
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import time

from bc250_smu import Bc250Smu
import trial_smu_clock_callback_once as callback
import trial_smu_clock_walker as clock

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
    'vcpu-early-ring-reset': ('amdgpu-vcn-early-ring-reset.ko',
                              '0f786456e81b669d4d5e7ebe31b8170bea31585691bfec625b3a086a8c0ebc8a'),
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
    'rbc-reset-oracle': ('amdgpu-vcn-rbc-cache-readback.ko',
                         '76042d81e0cddbdf1b4c6333cae97b4bd5b499df850b1a9ad5b5023ae9469e27'),
    'rbc-tmr-reset-oracle': ('amdgpu-vcn-rbc-tmr-reset-oracle.ko',
                             '6d79e9689b5b9925d4678e3164c969ea774a50d5e721c025513dbcda2352806e'),
    'rbc-tmr-bar-oracle': ('amdgpu-vcn-rbc-tmr-bar-oracle.ko',
                           'cb2ec3daa290476ae7366dea0354a7767c4dfd283a96029e48613f2c604239f1'),
    'vcpu-clock-differential': ('amdgpu-vcn-vcpu-clock-differential.ko',
                                'f7dd5a406289dfa14d3048752973eede292f332a4d7f92dc1e79cba65f1390fb'),
    'vcpu-memory-witness': ('amdgpu-vcn-vcpu-memory-witness.ko',
                            'cc8631cda71a8b993aa2f0471cabbd9bba99e03610ebdb2604d46dba175e790e'),
    'mmsch-ungate': ('amdgpu-vcn-mmsch-ungate.ko',
                     '2a91dbe76e9d865cfa5134ecec90c2e5d7d772c0edde81a6da6b037296fcbf37'),
    'rbc-clock-status-calibration': (
        'amdgpu-vcn-rbc-clock-status-calibration.ko',
        'f9221b276480768bbb8997d43e899ea114e470a5dd2dbe535c6bd34d57e3036c'),
    'fetch-bar-differential': (
        'amdgpu-vcn-fetch-bar-differential.ko',
        'e8583a2a9721251c7537d8296b6327ef17c7c627745a7630b02b9398aff06a3f'),
    'dpg-clock-report': (
        'amdgpu-vcn-dpg-clock-report.ko',
        '6be8a126cb6de8cf9d16189bf01dc3adcb3a72eac20bcfb8084e010d857fa85a'),
    'vcpu-address-fault': (
        'amdgpu-vcn-vcpu-address-fault.ko',
        '46ea4d6fde50cbd6a65e46b334d7cda3e63470a2b29c8de051684cd3932324f3'),
    'vcpu-pif-interrupt': (
        'amdgpu-vcn-vcpu-pif-interrupt.ko',
        '5bfb92b6eae67da34c0de94236d9e7502e993e6c1ea71a49bd40e9cf2d6172b7'),
    'vcpu-report-force': (
        'amdgpu-vcn-vcpu-report-force.ko',
        '3c8c9ee98099ce99de1659d96b79283b682bdae07e69f65acc509db45471c60b'),
    'vcpu-report-handoff': (
        'amdgpu-vcn-vcpu-report-handoff.ko',
        '4f9aa48ff185551ed80e233a9f964baec5ed915f9a39e46bd739341295091143'),
    'rbc-tmr-psp-writer': (
        'amdgpu-vcn-rbc-tmr-psp-writer.ko',
        '061fcf2273caa3a24dabc23918b0a65fa0010ec4cdb35a8823d2b25b9102fd66'),
    'rbc-tmr-psp-writer-stage': (
        'amdgpu-vcn-rbc-tmr-psp-writer.ko',
        '061fcf2273caa3a24dabc23918b0a65fa0010ec4cdb35a8823d2b25b9102fd66'),
    'vcpu-spin-stub': (
        'amdgpu-vcn-vcpu-spin-stub.ko',
        'ae3fb016302d7eb08db71543d63c74a5453ccd25b1d2924305425b1c6f894148'),
    'vcpu-spin-ring-reset': (
        'amdgpu-vcn-vcpu-spin-ring-reset.ko',
        '033b59c6704e97a90da399fd7c5038fad81b0d6495af2c12cda9cb4c05daf20f'),
    'vcpu-marker-stub': (
        'amdgpu-vcn-vcpu-marker-stub.ko',
        '0786d82a05b15bafd6c3b850bf7c9a15b711b61792ce4967d31b4c2a08d83986'),
    'vcpu-early-store': (
        'amdgpu-vcn-vcpu-early-store.ko',
        '0656c0f3c95718f22ec83fff601f71a35881e33bba08bd8da84a0cd6cff8cf69'),
    'vcpu-harvest-try': (
        'amdgpu-vcn-vcpu-harvest-try.ko',
        '791b1f75f4b1dea760e52326820becaf082092617d290c814dda85313af01484'),
    'rbc-perfmon-control': ('amdgpu-vcn-rbc-perfmon-control.ko',
                            '54eb58b2696dc228df2d1d3de6e8f3f026357f1e61ec08ea078897bff8c68ebd'),
    'rbc-perfmon-phase': ('amdgpu-vcn-rbc-perfmon-phase.ko',
                          'de2971abe94fe7fe66dfa794edbf8caeb51712482980e129e9c8ceab3c6a39e2'),
    'rbc-tmr-perfmon-phase': ('amdgpu-vcn-rbc-perfmon-phase.ko',
                              'de2971abe94fe7fe66dfa794edbf8caeb51712482980e129e9c8ceab3c6a39e2'),
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
CALLBACK_SHA = '993a921bd4f59370c9e80e78a79e3aaec5b1287b8c4006da588ac91466a98c82'
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


def guarded_power_up(smu, emit, expected_clock_code, vclk_mhz):
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
    require(clock.smn(smu, clock.CLOCK_SMN) == expected_clock_code and
            [clock.smn(smu, address) for address in ENABLES] == [1, 1, 1] and
            clock.smn(smu, CONTROL) == 0,
            'clock/gate state changed before decoder startup')
    emit('native_clock_and_gates_ready', {'clock_code': expected_clock_code,
                                           'requested_vclk_mhz': vclk_mhz,
                                           'slot_enables': [1, 1, 1],
                                           'domain_gate': 0})


def guarded_domain6_cycle(smu, emit, expected_clock_code):
    """Exercise the pinned SMU domain-6 down/up register sequence once.

    The native VCLK request above occurs while the SMU already records
    domain 6 as powered. This tests whether a real power transition is
    needed to propagate that clock to VCN. The recovery PDU timer is armed
    by the caller, and any failed readback aborts before loading amdgpu.
    """
    require(clock.word(smu, 0xf714) == 0x10101 and
            clock.smn(smu, POWER_STATUS) == 0x01010101 and
            clock.smn(smu, POWER_COMMAND) == 0 and
            clock.smn(smu, POWER_RAIL) == 0 and
            clock.smn(smu, CONTROL) == 0 and
            [clock.smn(smu, address) for address in ENABLES] == [1, 1, 1] and
            clock.smn(smu, clock.CLOCK_SMN) == expected_clock_code,
            'domain-6 cycle baseline differs')

    def write_and_poll(address, value, poll_address, mask, expected, phase):
        emit('domain6_cycle_write_intent', {'phase': phase,
                                            'address': hex(WIN + address),
                                            'value': hex(value)})
        smu.smu_write32(WIN + address, value)
        deadline = time.monotonic() + 0.5
        while True:
            observed = clock.smn(smu, poll_address)
            if observed & mask == expected:
                emit('domain6_cycle_readback', {'phase': phase,
                                                 'address': hex(poll_address),
                                                 'value': hex(observed)})
                return observed
            require(time.monotonic() < deadline,
                    f'domain-6 {phase} acknowledgement timed out: '
                    f'{observed:#x}')
            time.sleep(0.01)

    # FUN_00024764 gates slots 0x16, 0x17 and 0x18 before calling
    # FUN_00023b14(6, 0). Their domain-control bits are 0, 1 and 2.
    write_and_poll(CONTROL, 0x7, CONTROL, 0x7, 0x7, 'close-slot-gates')
    # FUN_00023b14(6, 0): rail <- 1, then command <- 0x10.
    write_and_poll(POWER_RAIL, 1, POWER_RAIL, 1, 0, 'rail-down')
    down = write_and_poll(POWER_COMMAND, 0x10, POWER_STATUS,
                          0x1000, 0x1000, 'domain-down')
    require(down != 0x01010101,
            'domain-6 down command produced no status transition')
    # FUN_00023b14(6, 1): command <- 1, then rail <- 0x10000.
    up = write_and_poll(POWER_COMMAND, 1, POWER_STATUS,
                        0x100, 0x100, 'domain-up')
    write_and_poll(POWER_RAIL, 0x10000, POWER_RAIL,
                   0x10000, 0, 'rail-up')
    write_and_poll(CONTROL, 0, CONTROL, 0x7, 0, 'open-slot-gates')
    final = {'power_status': clock.smn(smu, POWER_STATUS),
             'power_command': clock.smn(smu, POWER_COMMAND),
             'power_rail': clock.smn(smu, POWER_RAIL),
             'domain_gate': clock.smn(smu, CONTROL),
             'slot_enables': [clock.smn(smu, address) for address in ENABLES],
             'clock_code': clock.smn(smu, clock.CLOCK_SMN),
             'smu_domain_state': clock.word(smu, 0xf714)}
    require(final['power_status'] & 0x100 == 0x100 and
            final['power_command'] == 0 and
            final['power_rail'] == 0 and
            final['domain_gate'] == 0 and
            final['slot_enables'] == [1, 1, 1] and
            final['clock_code'] == expected_clock_code and
            final['smu_domain_state'] == 0x10101,
            f'domain-6 cycle did not restore guarded state: {final}')
    emit('domain6_cycle_complete', {'down_status': hex(down),
                                    'up_status': hex(up), **final})


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
    callback_path = ROOT/'kernel/trial_smu_clock_callback_once.py'
    require(Path(callback.__file__).resolve() == callback_path and
            sha(callback_path) == CALLBACK_SHA and
            getattr(callback, 'SUPPORTED_VCLKS', None) == (800, 1250) and
            'vclk_mhz' in inspect.signature(callback.callback_once).parameters,
            'SMU callback import or source differs from the reviewed 800 MHz trial')
    require(sha(clock.SOURCE) == clock.SOURCE_SHA,
            'captured SMU image changed')
    return stage, module, expected_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--module-kind', choices=tuple(MODULES),
                        default='lmi-oracle')
    parser.add_argument('--vclk-mhz', type=int, choices=(800, 1250),
                        default=1250)
    parser.add_argument('--cycle-domain6-once', action='store_true')
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
                              'requested_vclk_mhz': args.vclk_mhz,
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
                       'requested_vclk_mhz': args.vclk_mhz,
                       'cycle_domain6_once': args.cycle_domain6_once,
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
            applied = callback.callback_once(trial, emit,
                                             vclk_mhz=args.vclk_mhz)
            guarded_power_up(smu, emit, applied['hardware_code'],
                             args.vclk_mhz)
            if args.cycle_domain6_once:
                guarded_domain6_cycle(smu, emit,
                                      applied['hardware_code'])
            # SETUP_TMR may hang the diagnostic driver, so pre-arm recovery.
            subprocess.run(['unshare', '--mount', '--propagation', 'private',
                            'bash', str(stage)], check=True, timeout=15)
            require(subprocess.check_output(['grub2-editenv', '-', 'list'],
                                            text=True).strip() == 'bc250_vcn_once=1'
                    and sha(Path('/boot/grub2/custom.cfg')) == ENTRY_SHA,
                    'diagnostic recovery entry not armed')
            emit('recovery_entry_staged', {'sha256': ENTRY_SHA})
            kernel_before = subprocess.check_output(
                ['dmesg', '--color=never'], text=True).splitlines()
            emit('insmod_intent', {'module': str(module), 'bc250_vcn': 1})
            result = subprocess.run(['insmod', str(module), 'bc250_vcn=1',
                                     'bc250_vcn_psp_probe=0'],
                                    capture_output=True, text=True, timeout=110)
            emit('insmod_return', {'returncode': result.returncode,
                                  'stdout': result.stdout[-2000:],
                                  'stderr': result.stderr[-2000:]})
            kernel_all = subprocess.check_output(
                ['dmesg', '--color=never'], text=True).splitlines()
            require(kernel_all[:len(kernel_before)] == kernel_before,
                    'kernel log rotated during diagnostic trial')
            kernel_lines = kernel_all[len(kernel_before):]
            rows = [line for line in kernel_lines
                if any(mark in line.lower() for mark in
                       ('amdgpu', 'vcn', 'uvd', 'psp', 'setup_tmr'))][-160:]
            emit('kernel_rows', rows)
            trace = [line for line in kernel_lines
                     if 'BC250 VCN' in line or 'BC250 MMSCH' in line]
            emit('vcn_register_trace', trace)
            if args.module_kind in ('vcpu-spin-stub',
                                    'vcpu-spin-ring-reset'):
                spin = [line for line in kernel_lines
                        if 'BC250 VCPU spin BO:' in line]
                require(len(spin) == 1, 'missing or duplicate VCPU spin BO report')
                match = re.search(
                    r'file=([0-9a-f]{4}) buffer=([0-9a-f]{4}) '
                    r'bytes=([0-9a-f]{6})', spin[0])
                require(match is not None and match.groups() ==
                        ('f308', 'f208', '06ffff'),
                        'VCPU spin BO bytes or location differ')
                samples = [line for line in trace
                           if 'BC250 VCN VCPU release:' in line or
                           'BC250 VCN VCPU wait0:' in line]
                emit('vcn_vcpu_spin_stub', {
                    'bo_readback': match[3],
                    'file_offset': match[1],
                    'buffer_offset': match[2],
                    'vcpu_samples': samples,
                    'interpretation_limit':
                        'A flat PC cannot distinguish reset, wrong entry point or blocked instruction fetch.',
                })
            if args.module_kind == 'vcpu-marker-stub':
                program_rows = [line for line in kernel_lines
                                if 'BC250 VCPU marker BO:' in line]
                before_rows = [line for line in kernel_lines
                               if 'BC250 VCPU marker before:' in line]
                after_rows = [line for line in kernel_lines
                              if 'BC250 VCPU marker after:' in line]
                wait_rows = [line for line in kernel_lines
                             if 'BC250 VCPU marker wait0:' in line]
                require(len(program_rows) == len(before_rows) ==
                        len(after_rows) == len(wait_rows) == 1,
                        'missing or duplicate VCPU marker witness')
                program = re.search(
                    r'code=f208 bytes=([0-9a-f]{24}) '
                    r'address=([0-9a-f]{8}) value=([0-9a-f]{8})',
                    program_rows[0])
                before = re.search(r'value=([0-9a-f]{8})', before_rows[0])
                after = re.search(
                    r'value=([0-9a-f]{8}) before=([0-9a-f]{8}) '
                    r'pc=([0-9a-f]{8})', after_rows[0])
                wait = re.search(r'value=([0-9a-f]{8})', wait_rows[0])
                require(program is not None and before is not None and
                        after is not None and wait is not None and
                        program.groups() ==
                        ('21fefb31fefb32620006ffff', '6100ffd0',
                         '7bc25001') and
                        before[1] == after[2] == '00000000',
                        'VCPU marker program, address or initial state differs')
                emit('vcn_vcpu_marker_stub', {
                    'program': program[1],
                    'target': '0x' + program[2],
                    'marker': '0x' + program[3],
                    'before': '0x' + before[1],
                    'after': '0x' + after[1],
                    'wait0': '0x' + wait[1],
                    'pc_trace': '0x' + after[3],
                    'marker_observed': program[3] in (after[1], wait[1]),
                    'early_boot_store_observed':
                        '61010010' in (after[1], wait[1]),
                    'interpretation_limit':
                        'If both expected stores are absent, no fetch and a wrong stack mapping remain possible; the later custom program entry is not proven.',
                })
            if args.module_kind in ('vcpu-early-store',
                                    'vcpu-harvest-try'):
                program_rows = [line for line in kernel_lines
                                if 'BC250 VCPU early BO:' in line]
                before_rows = [line for line in kernel_lines
                               if 'BC250 VCPU early before:' in line]
                after_rows = [line for line in kernel_lines
                              if 'BC250 VCPU early after:' in line]
                wait_rows = [line for line in kernel_lines
                             if 'BC250 VCPU early wait0:' in line]
                require(len(program_rows) == len(before_rows) ==
                        len(after_rows) == len(wait_rows) == 1,
                        'missing or duplicate VCPU early-store witness')
                program = re.search(
                    r'store=454 next=456 bytes=([0-9a-f]{6}) '
                    r'literal=124 value=([0-9a-f]{8}) target=([0-9a-f]{8})',
                    program_rows[0])
                before = re.search(r'value=([0-9a-f]{8})', before_rows[0])
                after = re.search(
                    r'value=([0-9a-f]{8}) before=([0-9a-f]{8}) '
                    r'pc=([0-9a-f]{8})', after_rows[0])
                wait = re.search(r'value=([0-9a-f]{8})', wait_rows[0])
                require(program is not None and before is not None and
                        after is not None and wait is not None and
                        program.groups() ==
                        ('06ffff', '0250c27b', '6100ffd0') and
                        before[1] == after[2] == '00000000',
                        'VCPU early program, target or initial state differs')
                emit('vcn_vcpu_early_store', {
                    'self_loop': program[1],
                    'literal_le': program[2],
                    'target': '0x' + program[3],
                    'before': '0x' + before[1],
                    'after': '0x' + after[1],
                    'wait0': '0x' + wait[1],
                    'pc_trace': '0x' + after[3],
                    'marker_observed':
                        '7bc25002' in (after[1], wait[1]),
                    'interpretation_limit':
                        'A marker proves the early store executed if the stack mapping is correct. Absence cannot distinguish a stalled VCPU from a wrong host mapping or a reset-vector path that bypasses this code.',
                })
                if args.module_kind == 'vcpu-harvest-try':
                    harvest_rows = [line for line in kernel_lines
                                    if 'BC250 VCPU harvest trial:' in line]
                    require(len(harvest_rows) == 1,
                            'missing or duplicate VCPU harvest readback')
                    harvest = re.search(
                        r'before=([0-9a-f]{8}) after=([0-9a-f]{8}) '
                        r'version=([0-9a-f]{8})', harvest_rows[0])
                    require(harvest is not None and
                            harvest[1] == '00000003' and
                            harvest[3] == '0002001b',
                            'VCN harvest guard or powered version changed')
                    emit('vcn_vcpu_harvest_try', {
                        'before': '0x' + harvest[1],
                        'after': '0x' + harvest[2],
                        'version': '0x' + harvest[3],
                        'clear_latched': harvest[2] == '00000000',
                        'marker_observed':
                            '7bc25002' in (after[1], wait[1]),
                        'interpretation_limit':
                            'A refused volatile write does not establish whether the disable indication originates from a physical fuse or an earlier policy latch.',
                    })
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
            if args.module_kind in ('psp-bo-fetch', 'vcpu-early-ring-reset',
                                    'psp-bo-premap',
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
            if args.module_kind == 'vcpu-early-ring-reset':
                rows = [line for line in trace
                        if 'BC250 VCN early ring reset:' in line]
                require(len(rows) == 1,
                        'missing or duplicate early reset-ring result')
                match = re.search(
                    r'first=([0-9a-f]{8})/([0-9a-f]{8}) '
                    r'second=([0-9a-f]{8})/([0-9a-f]{8}) '
                    r'dpg=([0-9a-f]{8}) status=([0-9a-f]{8}) '
                    r'prid=([0-9a-f]{8}) pc=([0-9a-f]{8})', rows[0])
                require(match is not None, 'malformed early reset-ring result')
                values = [int(value, 16) for value in match.groups()]
                require(values[:4] == [16, 0x11112222, 32, 0x33334444],
                        'early reset hold/release packets were not executed')
                emit('vcpu_early_ring_reset', {
                    'hold_packet_executed': True,
                    'release_packet_executed': True,
                    'dpg_clock_report': hex(values[4]),
                    'uvd_status': hex(values[5]),
                    'vcpu_ready_at_release': bool(values[5] & 2),
                    'vcpu_prid': hex(values[6]),
                    'vcpu_pc_trace': hex(values[7]),
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
            if args.module_kind in ('rbc-vcpu-reset-mapped',
                                    'vcpu-spin-ring-reset',
                                    'vcpu-marker-stub',
                                    'vcpu-early-store',
                                    'vcpu-harvest-try', 'rbc-cache-map'):
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
            if args.module_kind in ('rbc-cache-readback',
                                    'rbc-reset-oracle',
                                    'rbc-tmr-reset-oracle',
                                    'rbc-tmr-bar-oracle',
                                    'vcpu-clock-differential',
                                    'vcpu-memory-witness',
                                    'mmsch-ungate',
                                    'rbc-clock-status-calibration',
                                    'fetch-bar-differential',
                                    'dpg-clock-report',
                                    'vcpu-address-fault',
                                    'vcpu-pif-interrupt'):
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
                third = third_count = None
                if args.module_kind in ('fetch-bar-differential',
                                        'vcpu-address-fault',
                                        'vcpu-pif-interrupt'):
                    third, third_count = oracle_row(
                        'third',
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
                        0x11112222,
                        'first ring marker changed during PSP read')
                if args.module_kind in ('fetch-bar-differential',
                                        'vcpu-address-fault',
                                        'vcpu-pif-interrupt'):
                    require(int(second[0], 16) == 32 and
                            int(second[1], 16) == 0x22223333 and
                            int(third[0], 16) == int(restored[3], 16) == 48 and
                            int(third[1], 16) == int(restored[4], 16) ==
                            0x33334444,
                            'fetch differential ring markers changed')
                else:
                    require(int(second[0], 16) == int(restored[3], 16) == 32 and
                            int(second[1], 16) == int(restored[4], 16) ==
                            0x33334444,
                            'ring markers changed during PSP read')
                reset_oracle = args.module_kind in ('rbc-reset-oracle',
                                                    'rbc-tmr-reset-oracle',
                                                    'rbc-tmr-bar-oracle',
                                                    'vcpu-clock-differential',
                                                    'vcpu-memory-witness',
                                                    'mmsch-ungate',
                                                    'rbc-clock-status-calibration',
                                                    'fetch-bar-differential',
                                                    'dpg-clock-report',
                                                    'vcpu-address-fault',
                                                    'vcpu-pif-interrupt')
                bar_oracle = args.module_kind in ('rbc-tmr-bar-oracle',
                                                  'vcpu-clock-differential',
                                                  'vcpu-memory-witness',
                                                  'mmsch-ungate',
                                                  'rbc-clock-status-calibration',
                                                  'fetch-bar-differential',
                                                  'dpg-clock-report',
                                                  'vcpu-address-fault',
                                                  'vcpu-pif-interrupt')
                expected_sentinel = (0x71080000 if args.module_kind in
                                     ('vcpu-address-fault', 'vcpu-pif-interrupt')
                                     else 0x71010000
                                     if bar_oracle else 0x71363000)
                event = ('vcn_rbc_tmr_bar_oracle' if bar_oracle else
                         'vcn_rbc_tmr_reset_oracle' if args.module_kind ==
                         'rbc-tmr-reset-oracle' else 'vcn_rbc_reset_oracle'
                         if reset_oracle else 'vcn_rbc_cache_readback')
                emit(event, {
                    'sentinel_psp_status': '0x' + sentinel[1],
                    'sentinel_observed':
                        int(sentinel[1], 16) == expected_sentinel,
                    'expected_sentinel': hex(expected_sentinel),
                    'restored_psp_status': '0x' + restored[1],
                    'restore_observed':
                        ((int(restored[1], 16) & 0xff000000) == 0x73000000
                        if reset_oracle else
                         int(restored[1], 16) == 0x70000010),
                    'reset_report_valid':
                        reset_oracle and
                        (int(restored[1], 16) & 0xff000000) == 0x73000000,
                    'psp_reset_low24':
                        (hex(int(restored[1], 16) & 0x00ffffff)
                         if reset_oracle else None),
                    'vcpu_reset_and_vclk_status_clear':
                        (int(restored[1], 16) & 0x00080008) == 0
                        if reset_oracle else None,
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
                if args.module_kind in ('fetch-bar-differential',
                                        'vcpu-address-fault',
                                        'vcpu-pif-interrupt'):
                    require(third_count == 1, 'missing third ring report')
                    emit('vcn_fetch_bar_ring_restore', {
                        'rptr': int(third[0], 16),
                        'marker': '0x' + third[1],
                        'status': '0x' + third[2],
                    })
                if bar_oracle:
                    require(int(sentinel[0]) == int(restored[0]) ==
                            int(replay[0]) == 0 and
                            int(sentinel[1], 16) == expected_sentinel and
                            int(restored[1], 16) == 0x73000000 and
                            int(replay[1], 16) == 0,
                            'TMR BAR ring shift or restoration not proven')
            if args.module_kind == 'fetch-bar-differential':
                fields = ('status0', 'status_or', 'pc_or', 'pf_or',
                          'status', 'pc', 'pf', 'prid', 'lmi', 'latency')
                observations = {}
                for phase in ('displaced', 'restored'):
                    rows = [line for line in kernel_lines if
                            f'BC250 VCPU fetch differential {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate fetch differential {phase}')
                    values = re.search(
                        r' '.join(rf'{field}=([0-9a-f]{{8}})'
                                  for field in fields), rows[0])
                    require(values is not None,
                            f'malformed fetch differential {phase}')
                    observations[phase] = {
                        field: hex(int(value, 16))
                        for field, value in zip(fields, values.groups())}
                emit('vcn_fetch_bar_differential', {
                    'observations': observations,
                    'interpretation_limit':
                        'Equal status and zero trace/fault do not exclude silent fetch of bad instructions.',
                })
            if args.module_kind in ('vcpu-address-fault',
                                    'vcpu-pif-interrupt'):
                held_rows = [line for line in kernel_lines if
                             'BC250 VCPU address fault held:' in line]
                require(len(held_rows) == 1,
                        'missing or duplicate held VCPU address-error report')
                held_match = re.search(
                    r'sys=([0-9a-f]{8}) en=([0-9a-f]{8}) '
                    r'trce_rd=([0-9a-f]{8})', held_rows[0])
                require(held_match is not None,
                        'malformed held VCPU address-error report')
                held = dict(zip(('sys', 'en', 'trce_rd'),
                                (int(v, 16) for v in held_match.groups())))
                fields = ('status0', 'status_or', 'pc_or', 'sys_or',
                          'status', 'pc', 'sys', 'prid', 'lmi',
                          'latency', 'trce_rd')
                observations = {}
                for phase in ('displaced', 'restored'):
                    rows = [line for line in kernel_lines if
                            f'BC250 VCPU address fault {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate VCPU address-error {phase}')
                    values = re.search(
                        r' '.join(rf'{field}=([0-9a-f]{{8}})'
                                  for field in fields), rows[0])
                    require(values is not None,
                            f'malformed VCPU address-error {phase}')
                    observations[phase] = dict(zip(
                        fields, (int(v, 16) for v in values.groups())))
                pif_route = None
                if args.module_kind == 'vcpu-pif-interrupt':
                    def pif_row(label, fields):
                        rows = [line for line in kernel_lines if
                                f'BC250 VCPU PIF {label}:' in line]
                        require(len(rows) == 1,
                                f'missing or duplicate VCPU PIF {label}')
                        values = re.search(
                            r' '.join(rf'{field}=([0-9a-f]{{8}})'
                                      for field in fields), rows[0])
                        require(values is not None,
                                f'malformed VCPU PIF {label}')
                        return dict(zip(fields,
                                        (int(v, 16) for v in values.groups())))

                    armed = pif_row('armed',
                                    ('old_sys', 'old_vcpu', 'sys', 'vcpu',
                                     'master', 'status'))
                    displaced_en = pif_row('displaced enable',
                                            ('sys', 'vcpu', 'master'))
                    restored_en = pif_row('restored enable',
                                           ('sys', 'vcpu', 'master'))
                    disarmed = pif_row('disarmed',
                                       ('sys', 'vcpu', 'status'))
                    pif_route = {
                        'armed': {k: hex(v) for k, v in armed.items()},
                        'displaced_enable': {
                            k: hex(v) for k, v in displaced_en.items()},
                        'restored_enable': {
                            k: hex(v) for k, v in restored_en.items()},
                        'disarmed': {k: hex(v) for k, v in disarmed.items()},
                        'both_pif_enables_latched':
                            bool(armed['sys'] & armed['vcpu'] & 1),
                        'both_pif_enables_survived_release':
                            bool(displaced_en['sys'] & displaced_en['vcpu'] & 1),
                        'original_enables_restored':
                            (disarmed['sys'] == armed['old_sys'] and
                             disarmed['vcpu'] == armed['old_vcpu']),
                    }
                emit('vcn_vcpu_address_fault', {
                    'firmware_bar_low_during_test': '0x20080000',
                    'vr_aperture_end': '0xf41fffffff',
                    'held': {k: hex(v) for k, v in held.items()},
                    'observations': {
                        phase: {k: hex(v) for k, v in values.items()}
                        for phase, values in observations.items()},
                    'new_pif_address_error_seen':
                        bool((observations['displaced']['sys_or'] & 1) and
                             not ((armed['status'] if pif_route else
                                   held['sys']) & 1)),
                    'pif_route': pif_route,
                    'interpretation_limit':
                        'PIF_ADDR_ERR_INT is a named address-error bit, but a zero does not exclude silent VCPU fetch failure.',
                })
            if args.module_kind in ('vcpu-report-force',
                                    'vcpu-report-handoff'):
                handoff = args.module_kind == 'vcpu-report-handoff'
                rows = [line for line in kernel_lines if
                        'BC250 VCPU report phase=' in line]
                require(len(rows) == (5 if handoff else 4),
                        f'unexpected VCPU report phase count: {len(rows)}')
                phase_fields = ('phase', 'rptr', 'marker', 'status', 'dpg',
                                'prid', 'pc', 'lmi')
                phases = []
                for row in rows:
                    match = re.search(
                        r' '.join(rf'{field}=([0-9a-f]+)'
                                  for field in phase_fields), row)
                    require(match is not None, 'malformed VCPU report phase')
                    values = dict(zip(phase_fields, match.groups()))
                    phase = int(values['phase'])
                    require(phase == len(phases), 'VCPU report phase order changed')
                    require(int(values['rptr'], 16) == (phase + 1) * 16 and
                            int(values['marker'], 16) == 0x11110000 | phase,
                            'VCPU report ring packet did not reach marker')
                    phases.append({
                        k: int(v) if k == 'phase' else hex(int(v, 16))
                        for k, v in values.items()})
                final_rows = [line for line in kernel_lines if
                              ('BC250 VCPU report handoff:' if handoff else
                               'BC250 VCPU report final:') in line]
                require(len(final_rows) == 1,
                        'missing or duplicate VCPU report restoration')
                final_fields = ('status', 'dpg', 'prid', 'pc', 'rptr')
                final_match = re.search(
                    r' '.join(rf'{field}=([0-9a-f]{{8}})'
                              for field in final_fields), final_rows[0])
                require(final_match is not None,
                        'malformed VCPU report restoration')
                final = dict(zip(final_fields,
                                 (int(v, 16) for v in final_match.groups())))
                require(final['status'] == (2 if handoff else 4),
                        'unexpected VCPU report final status')
                downstream = None
                if handoff:
                    wait_rows = [line for line in kernel_lines if
                                 'BC250 VCPU report after wait:' in line]
                    test_rows = [line for line in kernel_lines if
                                 'BC250 VCPU report decode test:' in line]
                    require(len(wait_rows) == len(test_rows) == 1,
                            'forced report did not reach exactly one decode test')
                    wait_fields = ('status', 'master', 'prid', 'pc')
                    wait_match = re.search(
                        r' '.join(rf'{field}=([0-9a-f]{{8}})'
                                  for field in wait_fields), wait_rows[0])
                    test_fields = ('ret', 'status', 'master', 'rptr',
                                   'wptr', 'scratch', 'prid', 'pc')
                    test_match = re.search(
                        r'ret=(-?\d+) ' +
                        r' '.join(rf'{field}=([0-9a-f]{{8}})'
                                  for field in test_fields[1:]), test_rows[0])
                    require(wait_match is not None and test_match is not None,
                            'malformed forced-report downstream observation')
                    downstream = {
                        'after_wait': dict(zip(
                            wait_fields,
                            (hex(int(v, 16)) for v in wait_match.groups()))),
                        'decode_ring_test': {
                            'ret': int(test_match.group(1)),
                            **dict(zip(test_fields[1:],
                                       (hex(int(v, 16)) for v in
                                        test_match.groups()[1:])))},
                    }
                emit('vcn_vcpu_report_force', {
                    'phases': phases,
                    'final': {k: hex(v) for k, v in final.items()},
                    'status_two_latched_under_reset':
                        int(phases[0]['status'], 16) == 2,
                    'status_two_latched_after_release':
                        int(phases[2]['status'], 16) == 2,
                    'downstream': downstream,
                    'interpretation_limit':
                        'A host-written ready report is not evidence that the VCPU fetched or decoded an instruction.',
                })
            if args.module_kind == 'rbc-clock-status-calibration':
                rows = [line for line in kernel_lines
                        if 'BC250 RBC clock status calibration:' in line]
                require(len(rows) == 1,
                        'missing or duplicate RBC clock status calibration')
                fields = ('gate0', 'gate1', 'gate2', 'status0', 'status1',
                          'status2', 'ctrl')
                values = re.findall(r'\b(?:' + '|'.join(fields) +
                                    r')=([0-9a-f]{8})\b', rows[0])
                require(len(values) == len(fields),
                        'malformed RBC clock status calibration')
                witness = dict(zip(fields, (int(v, 16) for v in values)))
                require(witness['gate0'] == witness['gate2'] == 0x00100000
                        and witness['gate1'] == 0x00100010
                        and witness['ctrl'] == 0x8000018c,
                        'RBC gate did not toggle and restore')
                emit('vcn_rbc_clock_status_calibration', {
                    'values': {key: hex(value)
                               for key, value in witness.items()},
                    'rbc_sclk_status_bits': [
                        bool(witness[key] & 0x00000800)
                        for key in ('status0', 'status1', 'status2')],
                    'rbc_sclk_status_changed': bool(
                        (witness['status0'] ^ witness['status1']) &
                        0x00000800),
                    'interpretation_limit':
                        'A gate register toggle alone does not prove the RBC clock physically stopped.',
                })
            if args.module_kind in ('vcpu-clock-differential',
                                    'dpg-clock-report'):
                def clock_row(label, fields):
                    rows = [line for line in kernel_lines
                            if f'BC250 VCPU clock {label}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate VCPU clock {label} report')
                    values = re.findall(r'\b(?:' + '|'.join(fields) +
                                        r')=([0-9a-f]{8})\b', rows[0])
                    require(len(values) == len(fields),
                            f'malformed VCPU clock {label} report')
                    return dict(zip(fields, (int(v, 16) for v in values)))

                diff = clock_row('differential',
                                 ('gate', 'cgcctrl', 'cgc_on', 'cgc_off',
                                  'cgc_back', 'ctrl_on', 'ctrl_off',
                                  'ctrl_back', 'prid') +
                                 (('dpg_on', 'dpg_off', 'dpg_back')
                                  if args.module_kind == 'dpg-clock-report'
                                  else ()))
                released = clock_row('released',
                                     ('gate', 'cgcctrl', 'cgc', 'ctrl',
                                      'prid', 'pc', 'status') +
                                     (('dpg',) if args.module_kind ==
                                      'dpg-clock-report' else ()))
                wait0 = clock_row('wait0',
                                  ('gate', 'cgcctrl', 'cgc', 'ctrl', 'prid') +
                                  (('dpg',) if args.module_kind ==
                                   'dpg-clock-report' else ()))
                require(diff['ctrl_on'] == diff['ctrl_back'] == 0x0ff20200 and
                        diff['ctrl_off'] == 0x0ff20000,
                        'VCPU clock control toggle did not restore')
                emit(('vcn_dpg_clock_report' if args.module_kind ==
                      'dpg-clock-report' else 'vcn_vcpu_clock_differential'), {
                    'held': {k: hex(v) for k, v in diff.items()},
                    'released': {k: hex(v) for k, v in released.items()},
                    'wait0': {k: hex(v) for k, v in wait0.items()},
                    'vcpu_gate_bits': [bool(diff['gate'] & 0x40000),
                                       bool(released['gate'] & 0x40000),
                                       bool(wait0['gate'] & 0x40000)],
                    'vcpu_sclk_status_bits':
                        [bool(diff[x] & 0x02000000)
                         for x in ('cgc_on', 'cgc_off', 'cgc_back')],
                    'vcpu_vclk_status_bits':
                        [bool(diff[x] & 0x04000000)
                         for x in ('cgc_on', 'cgc_off', 'cgc_back')],
                    'rbc_sclk_status_bits':
                        [bool(diff[x] & 0x00000800)
                         for x in ('cgc_on', 'cgc_off', 'cgc_back')],
                })
            if args.module_kind == 'vcpu-memory-witness':
                rows = [line for line in kernel_lines
                        if 'BC250 VCPU memory witness:' in line]
                require(len(rows) == 1,
                        'missing or duplicate VCPU memory witness')
                fields = ('stack0', 'stack_hold', 'stack_run', 'ctx0',
                          'ctx_hold', 'ctx_run', 'status', 'prid', 'pc', 'pf')
                values = re.findall(r'\b(?:' + '|'.join(fields) +
                                    r')=([0-9a-f]{8})\b', rows[0])
                require(len(values) == len(fields),
                        'malformed VCPU memory witness')
                witness = dict(zip(fields, (int(v, 16) for v in values)))
                emit('vcn_vcpu_memory_witness', {
                    'values': {k: hex(v) for k, v in witness.items()},
                    'reset_held_control_stable':
                        witness['stack0'] == witness['stack_hold'] and
                        witness['ctx0'] == witness['ctx_hold'],
                    'stack_changed_after_release':
                        witness['stack_run'] != witness['stack_hold'],
                    'context_changed_after_release':
                        witness['ctx_run'] != witness['ctx_hold'],
                    'interpretation_limit':
                        'Unchanged stack/context does not exclude instruction fetch without a write.',
                })
            if args.module_kind == 'mmsch-ungate':
                mmsch_rows = {}
                for phase in ('held', 'released', 'wait0', 'restored'):
                    rows = [line for line in trace
                            if f'BC250 MMSCH ungate {phase}:' in line]
                    require(len(rows) == 1,
                            f'missing or duplicate MMSCH ungate {phase}')
                    mmsch_rows[phase] = {
                        field: int(value, 16)
                        for field, value in re.findall(
                            r'\b([a-z0-9]+)=([0-9a-f]{8})\b', rows[0])}
                held = mmsch_rows['held']
                restored = mmsch_rows['restored']
                require(held['ctrl0'] == restored['ctrl'] == 0x8000018c
                        and held['gate0'] == restored['gate'] == 0x00100000
                        and all(mmsch_rows[phase]['ctrl'] == 0x0000018c
                                and mmsch_rows[phase]['gate'] == 0
                                for phase in ('held', 'released', 'wait0')),
                        'MMSCH clock mode/gate did not change and restore')
                emit('vcn_mmsch_ungate', {
                    'phases': {phase: {field: hex(value)
                                      for field, value in row.items()}
                               for phase, row in mmsch_rows.items()},
                    'reset_status_bits': {
                        phase: hex(row['reset2'] & 0x00030000)
                        for phase, row in mmsch_rows.items()},
                    'vcpu_ready_during_trial': any(
                        mmsch_rows[phase]['status'] & 2
                        for phase in ('held', 'released', 'wait0')),
                })
            if args.module_kind in ('rbc-tmr-psp-writer',
                                    'rbc-tmr-psp-writer-stage'):
                rows = {}
                for label in ('PSP writer result=', 'RBC BO control:',
                              'RBC PSP packets:', 'RBC restored:'):
                    matches = [line for line in kernel_lines
                               if f'BC250 TMR {label}' in line]
                    require(len(matches) <= 1,
                            f'duplicate TMR packet report: {label}')
                    if matches:
                        rows[label] = matches[0]
                writer_match = re.search(r'writer result=([0-9a-f]{8})',
                                         rows.get('PSP writer result=', ''))
                control_match = re.search(
                    r'ok=(\d+) rptr=([0-9a-f]{8}) marker=([0-9a-f]{8})',
                    rows.get('RBC BO control:', ''))
                tmr_match = re.search(
                    r'ok=(\d+) rptr=([0-9a-f]{8}) marker=([0-9a-f]{8})',
                    rows.get('RBC PSP packets:', ''))
                emit('vcn_rbc_tmr_psp_writer', {
                    'psp_writer_result': (hex(int(writer_match[1], 16))
                                          if writer_match else None),
                    'normal_bo_ring_control': ({
                        'ok': bool(int(control_match[1])),
                        'read_pointer': int(control_match[2], 16),
                        'scratch': hex(int(control_match[3], 16)),
                    } if control_match else None),
                    'psp_written_tmr_ring': ({
                        'ok': bool(int(tmr_match[1])),
                        'read_pointer': int(tmr_match[2], 16),
                        'scratch': hex(int(tmr_match[3], 16)),
                    } if tmr_match else None),
                    'ring_restored': 'RBC restored:' in rows,
                    'interpretation_limit':
                        'An RBC marker from TMR proves ring packet fetch, not VCPU instruction fetch.',
                })
            if args.module_kind in ('rbc-perfmon-phase',
                                    'rbc-tmr-perfmon-phase'):
                readings = {}
                for label in ('held', 'released'):
                    rows = [line for line in trace if
                            f'BC250 VCN perfmon phase {label}:' in line]
                    require(1 <= len(rows) <= 2,
                            f'missing or unexpected perfmon phase {label} reports')
                    if len(rows) == 2:
                        require(any('BC250 VCN RBC guard skipped' in line
                                    for line in trace),
                                'second perfmon phase lacks recovery guard')
                    match = re.search(
                        r'ctrl=([0-9a-f]{8}) lo=([0-9a-f]{8}) '
                        r'hi=([0-9a-f]{8}) status=([0-9a-f]{8}) '
                        r'pf=([0-9a-f]{8})', rows[0])
                    require(match is not None and int(match[1], 16) == 0x802,
                            f'malformed perfmon phase {label}')
                    readings[label] = {
                        'count': int(match[2], 16) |
                            (int(match[3], 16) << 32),
                        'status': '0x' + match[4],
                        'page_fault': '0x' + match[5],
                        'report_count': len(rows),
                    }
                emit('vcn_perfmon_vcpu_phase', readings)
            if args.module_kind in ('rbc-perfmon-control',
                                    'rbc-perfmon-phase',
                                    'rbc-tmr-perfmon-phase'):
                reports = [line for line in trace
                           if 'BC250 VCN RBC perfmon selector=' in line]
                done = [line for line in trace
                        if 'BC250 VCN RBC perfmon done:' in line]
                require(reports and len(done) == 1,
                        'missing ring perfmon selector or completion')
                readings = {}
                for line in reports:
                    match = re.search(
                        r'selector=(\d+) ctrl=([0-9a-f]{8}) '
                        r'lo=([0-9a-f]{8}) hi=([0-9a-f]{8}) '
                        r'rptr=([0-9a-f]{8}) scratch=([0-9a-f]{8})',
                        line)
                    require(match is not None,
                            'malformed ring perfmon selector report')
                    index = int(match[1])
                    require(index not in readings and 0 <= index < 32,
                            'duplicate or out-of-range ring perfmon selector')
                    readings[index] = {
                        'control': int(match[2], 16),
                        'count': int(match[3], 16) |
                            (int(match[4], 16) << 32),
                        'read_pointer': int(match[5], 16),
                        'scratch': int(match[6], 16),
                    }
                match = re.search(
                    r'completed=(\d+) restored=([0-9a-f]{8}) '
                    r'status=([0-9a-f]{8})', done[0])
                require(match is not None, 'malformed ring perfmon completion')
                completed = int(match[1])
                require(completed == len(readings) and
                        all(row['read_pointer'] == 512 and
                            row['scratch'] == 0xdeadbeef and
                            row['control'] == (index << 8) | 2
                            for index, row in readings.items()) and
                        int(match[2], 16) == 0,
                        'ring fetch or perfmon control did not complete')
                emit('vcn_rbc_perfmon_control', {
                    'completed_fetches': completed,
                    'all_selectors_scanned': completed == 32,
                    'nonzero_selectors': [index for index, row in
                                          sorted(readings.items())
                                          if row['count']],
                    'counts': {str(index): row['count'] for index, row in
                               sorted(readings.items())},
                    'final_status': '0x' + match[3],
                    'interpretation_limit':
                        'Selector 8 counts a known ring fetch, but its exact '
                        'event meaning is unknown; a zero VCPU-window count '
                        'does not prove that the VCPU made no memory read.',
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
