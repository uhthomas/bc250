#!/usr/bin/env python3
"""Calibrate VCN LMI perfmon against proven ring GPU-memory reads.

Each of 32 selectors sees a separate 512-dword ring fetch whose final
scratch marker is checked. A nonzero count provides a usable event baseline
for a later VCPU firmware-fetch measurement; all-zero counts remain
inconclusive. No persistent firmware or hardware setting is changed.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-direct-packet-20260929/vcn_v2_0.c'
SOURCE_SHA = '9ca8ab8b4338494063daafaee19aff1c0e2d1497594f3abc9ec55356c41e102e'
DEST = BUILD / 'vcn-rbc-perfmon-control-20260929'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'

GUARD_OLD = '''\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096) {'''
GUARD_NEW = '''\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL) != 0) {'''
PACKETS_OLD = '''\t\tWRITE_ONCE(ring->ring[0], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[1], 0xdeadbeef);
\t\tfor (sample_i = 2; sample_i < 16; ++sample_i)
\t\t\tWRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
\t\t\t\t   PACKET0(adev->vcn.inst[0].internal.nop, 0));'''
PACKETS_NEW = '''\t\tfor (sample_i = 0; sample_i < 512; sample_i += 2) {
\t\t\tWRITE_ONCE(ring->ring[sample_i],
\t\t\t\t   PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\t\tWRITE_ONCE(ring->ring[sample_i + 1], 0xdeadbeef);
\t\t}'''
START_OLD = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\trptr_first = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);'''
START_NEW = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 1);
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\trptr_first = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);'''
BEFORE_CLEANUP = '''\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {
'''
SCAN = '''\t\t/* Selector zero saw the first independently confirmed fetch. */
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 2);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC perfmon selector=0 ctrl=%08x lo=%08x hi=%08x rptr=%08x scratch=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9));
\t\t{
\t\t\tu32 selector, completed = 1;

\t\t\tfor (selector = 1; selector < 32; ++selector) {
\t\t\t\tu32 control = selector << 8;
\t\t\t\tu32 rptr = 0, scratch = 0;
\t\t\t\tunsigned int tries;

\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, 0xcafedead);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, control);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, control | 1);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL,
\t\t\t\t\t run_cntl | UVD_RBC_RB_CNTL__RB_NO_FETCH_MASK);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 512);
\t\t\t\tif (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) != 0 ||
\t\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) != 0xcafedead) {
\t\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t\t "BC250 VCN RBC perfmon hold failed selector=%u\\n",
\t\t\t\t\t\t selector);
\t\t\t\t\tbreak;
\t\t\t\t}
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\t\t\tfor (tries = 0; tries < 1024; ++tries) {
\t\t\t\t\trptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
\t\t\t\t\tscratch = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9);
\t\t\t\t\tif (rptr == 512 && scratch == 0xdeadbeef)
\t\t\t\t\t\tbreak;
\t\t\t\t\tudelay(5);
\t\t\t\t}
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL,
\t\t\t\t\t control | 2);
\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t "BC250 VCN RBC perfmon selector=%u ctrl=%08x lo=%08x hi=%08x rptr=%08x scratch=%08x\\n",
\t\t\t\t\t selector,
\t\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
\t\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
\t\t\t\t\t rptr, scratch);
\t\t\t\tif (rptr != 512 || scratch != 0xdeadbeef)
\t\t\t\t\tbreak;
\t\t\t\tcompleted++;
\t\t\t}
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC perfmon done: completed=%u restored=%08x status=%08x\\n",
\t\t\t\t completed,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\t}
'''


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN perfmon anchor changed: {old[:60]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned ring source changed')
    source = data.decode()
    source = substitute(source, GUARD_OLD, GUARD_NEW)
    source = substitute(source, PACKETS_OLD, PACKETS_NEW)
    if source.count('WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);') != 1:
        raise ValueError('unexpected first ring pointer count')
    source = source.replace('WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);',
                            'WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 512);', 1)
    source = substitute(source, START_OLD, START_NEW)
    source = substitute(source, BEFORE_CLEANUP, SCAN + BEFORE_CLEANUP)
    source = source.replace('BC250 VCN RBC control ',
                            'BC250 VCN RBC perfmon control ')
    vcn = BUILD / 'vcn-rbc-direct-packet-20260929/amdgpu_vcn.c'
    if hashlib.sha256(vcn.read_bytes()).hexdigest() != VCN_SHA:
        raise ValueError('pinned amdgpu_vcn.c changed')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, contents in (('vcn_v2_0.c', source),
                           ('amdgpu_vcn.c', vcn.read_text())):
        path = DEST / name
        if path.exists() and path.read_text() != contents:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_text(contents)
        print(name, hashlib.sha256(contents.encode()).hexdigest())


if __name__ == '__main__':
    main()
