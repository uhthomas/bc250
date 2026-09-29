#!/usr/bin/env python3
"""Move the sole powered PSP request after host reset writes for readback."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-postrelease-reload-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-postrelease-measure-20260927/vcn_v2_0.c'
SOURCE_SHA = '2950bcdc50f07fac9ac449de0935a61af3d686e6feae0a2246904f0d83f384a2'
START = '\tvcn_v2_0_mc_resume(vinst);\n\n'
END = '\n\tif (adev->pdev->device == 0x13fe)\n\t\tdev_warn(adev->dev,\n\t\t\t "BC250 VCN trace mc:'
GUARD = '''\t\t/* This measurement still submits the staged firmware. Refuse it if
\t\t * the live TMR and VCN allocations differ from the pinned trial.
\t\t */
\t\tif (adev->vcn.inst[0].gpu_addr != 0x000000f41fd00000ULL ||
\t\t    adev->vcn.inst[0].fw_shared.gpu_addr != 0x000000f41fda0000ULL ||
\t\t    adev->vcn.inst[0].fw->size != 405952 ||
\t\t    AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4) != 0x64000 ||
\t\t    ucode->tmr_mc_addr_hi != 0xf4 ||
\t\t    ucode->tmr_mc_addr_lo != 0x1fa00000 ||
\t\t    adev->gfx.config.gb_addr_config != 0x00100044) {
\t\t\tdev_err(adev->dev, "BC250 VCN postrelease allocation mismatch; PSP request skipped\\n");
\t\t\treturn -EINVAL;
\t\t}
\t\tdev_warn(adev->dev, "BC250 VCN postrelease allocation matched\\n");
'''
ANCHOR = '\t\tint postrelease_ret;\n\n'


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(START) == source.count(END) == source.count(ANCHOR) == 1
    prefix, tail = source.split(START, 1)
    removed, suffix = tail.split(END, 1)
    assert removed.count('psp_execute_ip_fw_load(&adev->psp, ucode)') == 1
    assert 'BC250 VCN pinned map matched before PSP write' in removed
    source = prefix + START + END.lstrip('\n') + suffix
    source = source.replace(ANCHOR, ANCHOR + GUARD, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
