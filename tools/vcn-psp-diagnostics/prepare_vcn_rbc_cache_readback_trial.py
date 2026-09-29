#!/usr/bin/env python3
"""Test one VCN ring cache write with an existing PSP read-only oracle.

Use the pinned ordinary BO and existing signed BO-premap hook. While holding
VCPU reset, write a temporary smaller cache-size0 through the ring; ask the
PSP to compare all sixteen cache words before it writes anything; restore
the original ring value; compare again; then replay the signed original map.
No BIOS EEPROM or Pico QSPI write is part of this trial.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-cache-map-20260929/vcn_v2_0.c'
SOURCE_SHA = 'd17eaa8c5238474378af261d7340b053d8023a3bea306707bb01d9937ae333fa'
DEST = BUILD / 'vcn-rbc-cache-readback-20260929'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'

OLD_SIZE = '''\t\tWRITE_ONCE(ring->ring[9],
\t\t\t   AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4));'''
NEW_SIZE = '''\t\t/* One page below the pinned 0x64000, only while VCPU reset is held. */
\t\tWRITE_ONCE(ring->ring[9], 0x63000);'''
BEFORE_SECOND = '''\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)
'''
SAMPLE_SENTINEL = '''\t\t/* The signed BO-premap hook reads all sixteen cache words before
\t\t * replaying any writes. Index 3 is cache-size0. Its diagnostic
\t\t * response should be 0x71363000 if the ring's 0x63000 latched.
\t\t */
\t\t{
\t\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
\t\t\tu32 scratch_before = RREG32(0x1f854 / 4);
\t\t\tu32 scratch_after, diag_status = 0;
\t\t\tint diag_ret = -EINVAL;

\t\t\tif (scratch_before == 0) {
\t\t\t\tWREG32(0x1f854 / 4, 0x5a13c0df);
\t\t\t\tif (RREG32(0x1f854 / 4) == 0x5a13c0df) {
\t\t\t\t\tdiag_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\t\t\t\tdiag_status = adev->psp.cmd_buf_mem->resp.status;
\t\t\t\t}
\t\t\t\tWREG32(0x1f854 / 4, scratch_before);
\t\t\t}
\t\t\tscratch_after = RREG32(0x1f854 / 4);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC cache oracle sentinel: ret=%d psp=%08x scratch=%08x rptr=%08x marker=%08x\\n",
\t\t\t\t diag_ret, diag_status, scratch_after,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9));
\t\t}

'''
OLD_SECOND = '''\t\tWRITE_ONCE(ring->ring[16], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[17], 0);
\t\tWRITE_ONCE(ring->ring[18], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[19], 0x33334444);'''
NEW_SECOND = '''\t\tWRITE_ONCE(ring->ring[16],
\t\t\t   PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[17], 0x64000);
\t\tWRITE_ONCE(ring->ring[18], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[19], 0);
\t\tWRITE_ONCE(ring->ring[20], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[21], 0x33334444);'''
BEFORE_SAMPLE = '''\t\t{
\t\t\tu32 first = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
'''
SAMPLE_RESTORED = '''\t\t/* Measure the restored value before the signed driver's ordinary
\t\t * map replay. Finally replay that map even if the ring result was
\t\t * unexpected, so the temporary size cannot persist in this boot.
\t\t */
\t\t{
\t\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
\t\t\tu32 scratch_before = RREG32(0x1f854 / 4);
\t\t\tu32 scratch_after, diag_status = 0;
\t\t\tint diag_ret = -EINVAL, replay_ret;

\t\t\tif (scratch_before == 0) {
\t\t\t\tWREG32(0x1f854 / 4, 0x5a13c0df);
\t\t\t\tif (RREG32(0x1f854 / 4) == 0x5a13c0df) {
\t\t\t\t\tdiag_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\t\t\t\tdiag_status = adev->psp.cmd_buf_mem->resp.status;
\t\t\t\t}
\t\t\t\tWREG32(0x1f854 / 4, scratch_before);
\t\t\t}
\t\t\tscratch_after = RREG32(0x1f854 / 4);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC cache oracle restored: ret=%d psp=%08x scratch=%08x rptr=%08x marker=%08x\\n",
\t\t\t\t diag_ret, diag_status, scratch_after,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9));
\t\t\treplay_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC cache oracle signed replay: ret=%d psp=%08x\\n",
\t\t\t\t replay_ret, adev->psp.cmd_buf_mem->resp.status);
\t\t}

'''


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN cache-readback anchor changed: {old[:55]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned cache-map source changed')
    source = data.decode()
    source = substitute(source, OLD_SIZE, NEW_SIZE)
    source = substitute(source, BEFORE_SECOND, SAMPLE_SENTINEL + BEFORE_SECOND)
    source = substitute(source, OLD_SECOND, NEW_SECOND)
    source = substitute(source, BEFORE_SAMPLE, SAMPLE_RESTORED + BEFORE_SAMPLE)
    source = source.replace('BC250 VCN RBC cache map ',
                            'BC250 VCN RBC cache oracle ')
    vcn = BUILD / 'vcn-rbc-cache-map-20260929/amdgpu_vcn.c'
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
