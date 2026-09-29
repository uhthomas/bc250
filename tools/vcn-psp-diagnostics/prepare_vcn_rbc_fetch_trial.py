#!/usr/bin/env python3
"""Request one aligned VCN decode-ring fetch from a valid GPU ring BO.

The opt-in module uses the stock ring allocation and NOP packet, matching the
Linux VCN 2.0 ring setup except that NO_FETCH/NO_UPDATE are cleared for a
short measured interval. It watches the hardware read pointer and LMI state.
No firmware, BIOS, or Pico flash content is changed.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-memory-requests-20260929/vcn_v2_0.c'
SOURCE_SHA = '26b58c21fa8e695d0e5356902a19f48d22b186995a962efa3bb53b81078b51a3'
DEST = BUILD / 'vcn-rbc-fetch-20260929'
ANCHOR = '\tfor (i = 0; i < 10; ++i) {\n'


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned LMI source changed')
    source = data.decode()
    if source.count(ANCHOR) != 1:
        raise ValueError('VCN wait anchor changed')
    probe = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
\t\tu32 version = RREG32_SOC15(UVD, 0, mmUVD_VERSION);
\t\tu32 harvest = RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING);
\t\tu32 status = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
\t\tu32 old_cntl = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL);
\t\tu32 old_rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
\t\tu32 old_wptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR);
\t\tu32 idle_cntl, run_cntl, observed_cntl;
\t\tu32 rptr_first, rptr_last, rptr_max, lmi_first, lmi_and, lmi_or;
\t\tu32 rptr_changes = 0, lmi_changes = 0;
\t\tunsigned int sample_i;

\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC pre: power=%08x pgfsm=%08x version=%08x harvest=%08x status=%08x cntl=%08x rptr=%08x wptr=%08x ring=%llx bytes=%u swptr=%llu nop=%08x\\n",
\t\t\t power, pgfsm, version, harvest, status,
\t\t\t old_cntl, old_rptr, old_wptr,
\t\t\t (unsigned long long)ring->gpu_addr, ring->ring_size,
\t\t\t (unsigned long long)ring->wptr,
\t\t\t ring->funcs ? PACKET0(adev->vcn.inst[0].internal.nop, 0) : 0);
\t\tif (power != 0x800 || pgfsm != 0 || version != 0x2001b ||
\t\t    harvest != 3 || status != 4 || old_cntl != 0x01000101 ||
\t\t    old_rptr != 0 || old_wptr != 0 || ring->wptr != 0 ||
\t\t    !ring->ring || !ring->funcs ||
\t\t    ring->funcs->align_mask != 0xf ||
\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096) {
\t\t\tdev_warn(adev->dev, "BC250 VCN RBC guard skipped\\n");
\t\t\treturn -EINVAL;
\t\t}

\t\t/* Eight valid NOP packets, aligned to the hardware's 16-dword
\t\t * WPTR granularity, in the already allocated VMID-0 ring BO.
\t\t */
\t\tfor (sample_i = 0; sample_i < 16; ++sample_i)
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
\t\tobserved_cntl = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC mapped: expected=%08x observed=%08x bar=%08x%08x rptr=%08x wptr=%08x\\n",
\t\t\t idle_cntl, observed_cntl,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR));
\t\tif (observed_cntl != idle_cntl) {
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
\t\t\treturn -EIO;
\t\t}

\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);
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
\t\t\t "BC250 VCN RBC fetch: run=%08x cntl=%08x wptr=%08x first=%08x last=%08x max=%08x rptr_changes=%u lmi_first=%08x lmi_and=%08x lmi_or=%08x lmi_changes=%u latency=%08x status=%08x pf=%08x\\n",
\t\t\t run_cntl, RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR),
\t\t\t rptr_first, rptr_last, rptr_max, rptr_changes,
\t\t\t lmi_first, lmi_and, lmi_or, lmi_changes,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
\t\t}
\t}

'''
    source = source.replace(ANCHOR, probe + ANCHOR, 1)
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-memory-requests-20260929/amdgpu_vcn.c'
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
