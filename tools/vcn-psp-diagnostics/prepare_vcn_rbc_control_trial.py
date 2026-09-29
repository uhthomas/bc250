#!/usr/bin/env python3
"""Build a guarded VCN ring fetch control using the kernel's scratch command.

The ring first has a valid command pending while RB_NO_FETCH is set. We then
clear only RB_NO_FETCH and compare the ring read pointer and scratch register.
All writes are volatile VCN registers or its existing ring BO.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-fetch-20260929/vcn_v2_0.c'
SOURCE_SHA = 'c572b63691b6cbeb39f21e61e03b8b629aac24a233b0166d6d033f3e03f4ed18'
DEST = BUILD / 'vcn-rbc-control-20260929'
START = '\t\t/* Eight valid NOP packets, aligned to the hardware\'s 16-dword\n'
END = '\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {\n'


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned RBC source changed')
    source = data.decode()
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError('RBC probe anchors changed')
    start = source.index(START)
    end = source.index(END, start)
    replacement = '''\t\t/* Match vcn_v2_0_dec_ring_test_ring(), then pad to the
\t\t * hardware's 16-dword WPTR granularity with valid NOP packets.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(adev->vcn.inst[0].internal.cmd, 0));
\t\tWRITE_ONCE(ring->ring[1],
\t\t\t   VCN_DEC_KMD_CMD | (VCN_DEC_CMD_PACKET_START << 1));
\t\tWRITE_ONCE(ring->ring[2], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[3], 0xdeadbeef);
\t\tfor (sample_i = 4; sample_i < 16; ++sample_i)
\t\t\tWRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
\t\t\t\t   PACKET0(adev->vcn.inst[0].internal.nop, 0));
\t\twmb();
\t\trun_cntl = REG_SET_FIELD(0, UVD_RBC_RB_CNTL, RB_BUFSZ,
\t\t\t\t\torder_base_2(ring->ring_size));
\t\trun_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_BLKSZ, 1);
\t\trun_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_RPTR_WR_EN, 1);
\t\tidle_cntl = run_cntl | UVD_RBC_RB_CNTL__RB_NO_FETCH_MASK |
\t\t\t\t\t UVD_RBC_RB_CNTL__RB_NO_UPDATE_MASK;
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID, 0);
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW,
\t\t\t\t lower_32_bits(ring->gpu_addr));
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH,
\t\t\t\t upper_32_bits(ring->gpu_addr));
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, 0xcafedead);
\t\tobserved_cntl = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC control mapped: expected=%08x observed=%08x bar=%08x%08x rptr=%08x wptr=%08x scratch=%08x\\n",
\t\t\t idle_cntl, observed_cntl,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9));
\t\tif (observed_cntl != idle_cntl ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) != 0xcafedead) {
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
\t\t\treturn -EIO;
\t\t}

\t\t/* With NO_FETCH set and NO_UPDATE clear, a WPTR write should
\t\t * leave RPTR and scratch stationary. This is the negative control.
\t\t */
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL,
\t\t\t\t run_cntl | UVD_RBC_RB_CNTL__RB_NO_FETCH_MASK);
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);
\t\tfor (sample_i = 0; sample_i < 1024; ++sample_i) {
\t\t\trptr_max = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
\t\t\tudelay(5);
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC control hold: cntl=%08x wptr=%08x rptr=%08x scratch=%08x lmi=%08x latency=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));

\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\trptr_first = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
\t\trptr_last = rptr_max = rptr_first;
\t\tlmi_first = RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS);
\t\tlmi_and = lmi_or = lmi_first;
\t\tfor (sample_i = 0; sample_i < 4096; ++sample_i) {
\t\t\tu32 rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
\t\t\tu32 lmi = RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS);

\t\t\trptr_changes += rptr != rptr_last;
\t\t\tlmi_changes += lmi != lmi_first;
\t\t\trptr_last = rptr;
\t\t\trptr_max = max(rptr_max, rptr);
\t\t\tlmi_and &= lmi;
\t\t\tlmi_or |= lmi;
\t\t\tudelay(5);
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC control execute: cntl=%08x wptr=%08x first=%08x last=%08x max=%08x rptr_changes=%u scratch=%08x lmi_first=%08x lmi_and=%08x lmi_or=%08x lmi_changes=%u latency=%08x status=%08x pf=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR),
\t\t\t rptr_first, rptr_last, rptr_max, rptr_changes,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
\t\t\t lmi_first, lmi_and, lmi_or, lmi_changes,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
'''
    source = source[:start] + replacement + source[end:]
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-rbc-fetch-20260929/amdgpu_vcn.c'
    if hashlib.sha256(vcn.read_bytes()).hexdigest() != (
            '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'):
        raise ValueError('pinned amdgpu_vcn.c changed')
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
