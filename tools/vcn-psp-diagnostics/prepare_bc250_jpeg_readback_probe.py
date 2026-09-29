#!/usr/bin/env python3
"""Build an opt-in JPEG ring-register readback diagnostic for the BC250.

The MMIO-pointer trial ruled out a doorbell-only failure. This variant
records the pointer immediately after submission and the configured ring
registers after the bounded kernel ring test. It writes no firmware.
"""

import prepare_bc250_jpeg_mmio_probe as mmio
import prepare_bc250_jpeg_probe as base


DEST = base.BUILD / 'bc250-jpeg-readback-20260929'

POINTER_OLD = '''\t} else {
\t\tWREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR, lower_32_bits(ring->wptr));
\t}
}'''
POINTER_NEW = '''\t} else {
\t\tWREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR, lower_32_bits(ring->wptr));
\t\tif (adev->pdev->device == 0x13fe)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 JPEG pointer commit: wanted=%08x actual=%08x cntl=%08x size=%08x\\n",
\t\t\t\t lower_32_bits(ring->wptr),
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR),
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_CNTL),
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_SIZE));
\t}
}'''

HW_INIT_NEW = mmio.HW_INIT_NEW.replace(
    'bar=%08x:%08x\\n',
    'cntl=%08x size=%08x vmid=%08x cgc=%08x gate=%08x '
    'bar=%08x:%08x gpu=%016llx\\n',
).replace(
    '\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_64BIT_BAR_HIGH),',
    '''\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_CNTL),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_SIZE),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_VMID),
\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_CGC_CTRL),
\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_CGC_GATE),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_64BIT_BAR_HIGH),''',
).replace(
    '\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_64BIT_BAR_LOW));',
    '''\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_LMI_JRBC_RB_64BIT_BAR_LOW),
\t\t\t (unsigned long long)ring->gpu_addr);''',
).replace('BC250 JPEG MMIO test:', 'BC250 JPEG readback test:')


def main() -> None:
    discovery_bytes = (base.SOURCE / 'amdgpu_discovery.c').read_bytes()
    jpeg_bytes = (base.SOURCE / 'jpeg_v2_0.c').read_bytes()
    assert base.digest(discovery_bytes) == base.PINNED['amdgpu_discovery.c']
    assert base.digest(jpeg_bytes) == base.PINNED['jpeg_v2_0.c']
    assert HW_INIT_NEW != mmio.HW_INIT_NEW
    assert HW_INIT_NEW.count('BC250 JPEG readback test:') == 1

    discovery = base.replace_once(discovery_bytes.decode(),
                                  base.DISCOVERY_OLD, base.DISCOVERY_NEW)
    jpeg = base.replace_once(jpeg_bytes.decode(), base.JPEG_OLD, base.JPEG_NEW)
    jpeg = base.replace_once(jpeg, base.JPEG_PGFSM_OLD, base.JPEG_PGFSM_NEW)
    jpeg = base.replace_once(jpeg, base.JPEG_POST_PG_OLD,
                             base.JPEG_POST_PG_NEW)
    jpeg = base.replace_once(jpeg, base.JPEG_END_OLD, base.JPEG_END_NEW)
    jpeg = base.replace_once(jpeg, mmio.DOORBELL_OLD, mmio.DOORBELL_NEW)
    jpeg = base.replace_once(jpeg, mmio.HW_INIT_OLD, HW_INIT_NEW)
    jpeg = base.replace_once(jpeg, POINTER_OLD, POINTER_NEW)
    assert jpeg.count('BC250 JPEG pointer commit:') == 1
    assert jpeg.count('BC250 JPEG readback test:') == 1

    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_discovery.c', discovery),
                          ('jpeg_v2_0.c', jpeg)):
        output = DEST / name
        output.write_text(content)
        print(name, base.digest(output.read_bytes()))


if __name__ == '__main__':
    main()
