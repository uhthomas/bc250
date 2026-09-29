#!/usr/bin/env python3
"""Probe JPEG decoder and JRBC register reachability with restored scratch words.

The opt-in module starts from the pinned JPEG clock/reset readback variant.
It writes only the documented scratch registers after the JPEG power request,
reads them back, and restores their original values before the ring test.
This is a volatile diagnostic, not a bootc or BIOS change.
"""

from pathlib import Path

import prepare_bc250_jpeg_probe as base


SOURCE = base.BUILD / 'bc250-jpeg-reset-clock-20260929'
DEST = base.BUILD / 'bc250-jpeg-scratch-20260929'
PINNED = {
    'amdgpu_discovery.c': '16c93ca7f11286dfa8974d2a5e8bf40f9e8d8044a3a13a0780878e51c028dbfb',
    'jpeg_v2_0.c': '2389e67ec0030d764396ac569a0056f187be3283b0d8d30fbea5d442b44f235a',
}

ANCHOR = '''\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 JPEG pretest state: reset=%08x jrbc_reset=%08x clock=%08x reset2=%08x power=%08x cntl=%08x size=%08x\\n",'''

PROBE = '''\t/* The ring register block is distinct from JPEG decode and LMI.
\t * Compare two volatile scratch registers, then restore each word.
\t * Do not exercise either register if the expected power/clock state
\t * was not reached. This is only enabled in the BC250 opt-in module.
\t */
\tif (adev->pdev->device == 0x13fe &&
\t    (RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS) &
\t     UVD_PGFSM_STATUS__UVDJ_PWR_STATUS_MASK) == 0 &&
\t    (RREG32_SOC15(JPEG, 0, mmJPEG_CGC_STATUS) & 0x1c3) == 0x1c3) {
\t\tu32 dec_before, jrbc_before, dec_probe, jrbc_probe;
\t\tu32 dec_after, jrbc_after;

\t\tdec_before = RREG32_SOC15(JPEG, 0, mmUVD_JPEG_DEC_SCRATCH0);
\t\tjrbc_before = RREG32_SOC15(JPEG, 0, mmUVD_JRBC_SCRATCH0);
\t\tWREG32_SOC15(JPEG, 0, mmUVD_JPEG_DEC_SCRATCH0, 0x5a13c0de);
\t\tWREG32_SOC15(JPEG, 0, mmUVD_JRBC_SCRATCH0, 0xa16bc250);
\t\tdec_probe = RREG32_SOC15(JPEG, 0, mmUVD_JPEG_DEC_SCRATCH0);
\t\tjrbc_probe = RREG32_SOC15(JPEG, 0, mmUVD_JRBC_SCRATCH0);
\t\tWREG32_SOC15(JPEG, 0, mmUVD_JPEG_DEC_SCRATCH0, dec_before);
\t\tWREG32_SOC15(JPEG, 0, mmUVD_JRBC_SCRATCH0, jrbc_before);
\t\tdec_after = RREG32_SOC15(JPEG, 0, mmUVD_JPEG_DEC_SCRATCH0);
\t\tjrbc_after = RREG32_SOC15(JPEG, 0, mmUVD_JRBC_SCRATCH0);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 JPEG scratch: dec=%08x/%08x/%08x jrbc=%08x/%08x/%08x\\n",
\t\t\t dec_before, dec_probe, dec_after,
\t\t\t jrbc_before, jrbc_probe, jrbc_after);
\t} else if (adev->pdev->device == 0x13fe) {
\t\tdev_warn(adev->dev, "BC250 JPEG scratch skipped: power or clocks differ\\n");
\t}

'''


def main() -> None:
    sources = {}
    for name, expected in PINNED.items():
        path = SOURCE / name
        data = path.read_bytes()
        assert base.digest(data) == expected, path
        sources[name] = data.decode()
    jpeg = base.replace_once(sources['jpeg_v2_0.c'], ANCHOR, PROBE + ANCHOR)
    assert jpeg.count('BC250 JPEG scratch:') == 1
    assert jpeg.count('BC250 JPEG pretest state:') == 1
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_discovery.c', sources['amdgpu_discovery.c']),
                          ('jpeg_v2_0.c', jpeg)):
        path = DEST / name
        path.write_text(content)
        print(name, base.digest(path.read_bytes()))


if __name__ == '__main__':
    main()
