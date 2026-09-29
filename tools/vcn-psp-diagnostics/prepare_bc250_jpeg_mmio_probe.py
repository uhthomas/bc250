#!/usr/bin/env python3
"""Build a BC250 JPEG-only diagnostic using the standard MMIO ring pointer.

The existing JPEG-only probe establishes that client-12 policy opens the
register aperture, but its doorbell-fed ring times out. This opt-in variant
changes only BC250's ring pointer transport and records the post-test state.
It is a diagnostic module for an isolated boot, not a bootc image change.
"""

from pathlib import Path

from prepare_bc250_jpeg_probe import (
    BUILD, DISCOVERY_NEW, DISCOVERY_OLD, JPEG_END_NEW, JPEG_END_OLD,
    JPEG_NEW, JPEG_OLD, JPEG_PGFSM_NEW, JPEG_PGFSM_OLD,
    JPEG_POST_PG_NEW, JPEG_POST_PG_OLD, PINNED, SOURCE, digest, replace_once,
)


DEST = BUILD / 'bc250-jpeg-mmio-20260929'

DOORBELL_OLD = '''\tring->use_doorbell = true;
\tring->doorbell_index = (adev->doorbell_index.vcn.vcn_ring0_1 << 1) + 1;'''
DOORBELL_NEW = '''\t/* Diagnostic: use the standard register write-pointer path on BC250. */
\tring->use_doorbell = adev->pdev->device != 0x13fe;
\tring->doorbell_index = (adev->doorbell_index.vcn.vcn_ring0_1 << 1) + 1;'''

HW_INIT_OLD = '''\tadev->nbio.funcs->vcn_doorbell_range(adev, ring->use_doorbell,
\t\t(adev->doorbell_index.vcn.vcn_ring0_1 << 1), 0);

\treturn amdgpu_ring_test_helper(ring);
}'''
HW_INIT_NEW = '''\tint r;

\tadev->nbio.funcs->vcn_doorbell_range(adev, ring->use_doorbell,
\t\t(adev->doorbell_index.vcn.vcn_ring0_1 << 1), 0);

\tr = amdgpu_ring_test_helper(ring);
\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 JPEG MMIO test: ret=%d doorbell=%u sw_wptr=%llx pitch=%08x jrbc=%08x rptr=%08x wptr=%08x jmi=%08x bar=%08x:%08x\\n",
\t\t\t r, ring->use_doorbell,
\t\t\t (unsigned long long)ring->wptr,
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JPEG_PITCH),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_RPTR),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JMI_CNTL),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_64BIT_BAR_HIGH),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_64BIT_BAR_LOW));
\treturn r;
}'''


def main() -> None:
    discovery_bytes = (SOURCE / 'amdgpu_discovery.c').read_bytes()
    jpeg_bytes = (SOURCE / 'jpeg_v2_0.c').read_bytes()
    assert digest(discovery_bytes) == PINNED['amdgpu_discovery.c']
    assert digest(jpeg_bytes) == PINNED['jpeg_v2_0.c']
    discovery = replace_once(discovery_bytes.decode(), DISCOVERY_OLD, DISCOVERY_NEW)
    jpeg = replace_once(jpeg_bytes.decode(), JPEG_OLD, JPEG_NEW)
    jpeg = replace_once(jpeg, JPEG_PGFSM_OLD, JPEG_PGFSM_NEW)
    jpeg = replace_once(jpeg, JPEG_POST_PG_OLD, JPEG_POST_PG_NEW)
    jpeg = replace_once(jpeg, JPEG_END_OLD, JPEG_END_NEW)
    jpeg = replace_once(jpeg, DOORBELL_OLD, DOORBELL_NEW)
    jpeg = replace_once(jpeg, HW_INIT_OLD, HW_INIT_NEW)
    assert discovery.count('BC250 JPEG-only ring probe enabled') == 1
    assert jpeg.count('BC250 JPEG MMIO test:') == 1
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_discovery.c', discovery),
                          ('jpeg_v2_0.c', jpeg)):
        output = DEST / name
        output.write_text(content)
        print(name, digest(output.read_bytes()))


if __name__ == '__main__':
    main()
