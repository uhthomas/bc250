#!/usr/bin/env python3
"""Instrument JPEG/JRBC clock and reset status on an opt-in BC250 boot.

This builds on the pinned MMIO ring-readback probe. The extra register
accesses are reads before and after the existing bounded ring test; no
firmware or permanent hardware state is changed.
"""

import prepare_bc250_jpeg_probe as base
import prepare_bc250_jpeg_mmio_probe as mmio
import prepare_bc250_jpeg_readback_probe as readback


DEST = base.BUILD / 'bc250-jpeg-reset-clock-20260929'

STATE_ARGS = '''\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_SOFT_RESET_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_SOFT_RESET),
\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_CGC_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_SOFT_RESET2),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JPEG_POWER_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_CNTL),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_SIZE)'''


def state_log(phase: str) -> str:
    return f'''\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 JPEG {phase} state: reset=%08x jrbc_reset=%08x clock=%08x reset2=%08x power=%08x cntl=%08x size=%08x\\n",
{STATE_ARGS});
'''


def main() -> None:
    discovery_bytes = (base.SOURCE / 'amdgpu_discovery.c').read_bytes()
    jpeg_bytes = (base.SOURCE / 'jpeg_v2_0.c').read_bytes()
    assert base.digest(discovery_bytes) == base.PINNED['amdgpu_discovery.c']
    assert base.digest(jpeg_bytes) == base.PINNED['jpeg_v2_0.c']

    discovery = base.replace_once(discovery_bytes.decode(),
                                  base.DISCOVERY_OLD, base.DISCOVERY_NEW)
    jpeg = base.replace_once(jpeg_bytes.decode(), base.JPEG_OLD, base.JPEG_NEW)
    jpeg = base.replace_once(jpeg, base.JPEG_PGFSM_OLD, base.JPEG_PGFSM_NEW)
    jpeg = base.replace_once(jpeg, base.JPEG_POST_PG_OLD,
                             base.JPEG_POST_PG_NEW)
    jpeg = base.replace_once(jpeg, base.JPEG_END_OLD,
                             base.JPEG_END_NEW.replace('\treturn 0;\n}',
                                 state_log('pretest') + '\treturn 0;\n}'))
    jpeg = base.replace_once(jpeg, mmio.DOORBELL_OLD, mmio.DOORBELL_NEW)
    jpeg = base.replace_once(jpeg, mmio.HW_INIT_OLD,
                             readback.HW_INIT_NEW.replace('\treturn r;\n}',
                                 state_log('posttest') + '\treturn r;\n}'))
    jpeg = base.replace_once(jpeg, readback.POINTER_OLD,
                             readback.POINTER_NEW)
    for marker in ('BC250 JPEG pointer commit:',
                   'BC250 JPEG readback test:',
                   'BC250 JPEG pretest state:',
                   'BC250 JPEG posttest state:'):
        assert jpeg.count(marker) == 1, marker
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_discovery.c', discovery),
                          ('jpeg_v2_0.c', jpeg)):
        output = DEST / name
        output.write_text(content)
        print(name, base.digest(output.read_bytes()))


if __name__ == '__main__':
    main()
