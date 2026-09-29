#!/usr/bin/env python3
"""Test whether the off UVDW tile isolates BC250 JPEG's JRBC subblock.

This opt-in source extends the pinned scratch-control module. Only on the
measured BC250 baseline, it requests UVDW power on through the standard
PGFSM config field, waits at most 1 ms for status, and restores the request
if the tile does not respond. The rest of the JPEG startup is unchanged.
The diagnostic module is never installed in the bootc image.
"""

import prepare_bc250_jpeg_probe as base


SOURCE = base.BUILD / 'bc250-jpeg-scratch-20260929'
DEST = base.BUILD / 'bc250-jpeg-uvdw-power-20260929'
PINNED = {
    'amdgpu_discovery.c': '16c93ca7f11286dfa8974d2a5e8bf40f9e8d8044a3a13a0780878e51c028dbfb',
    'jpeg_v2_0.c': 'c22863a3482eead92497e8849304672ccb24186a8e62b035b80be3fe41d33ba1',
}
ANCHOR = '\t/* JPEG disable CGC */\n'
PROBE = '''\t/* The prior BC250 run left UVDW off (status bits 21:20 == 2)
\t * while UVDJ was on. Test the one missing power request, guarded by
\t * the exact measured config/status/power baseline. The local PGFSM
\t * operation is volatile and isolated to this diagnostic boot.
\t */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 pg_config = RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG);
\t\tu32 pg_status = RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS);
\t\tu32 pg_after = pg_status;
\t\tunsigned int attempt;

\t\tif (pg_config == 0x00400000 && pg_status == 0x00200000 &&
\t\t    RREG32_SOC15(JPEG, 0, mmUVD_JPEG_POWER_STATUS) == 0) {
\t\t\tWREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG,
\t\t\t\t pg_config | (1u << UVD_PGFSM_CONFIG__UVDW_PWR_CONFIG__SHIFT));
\t\t\tfor (attempt = 0; attempt < 100; attempt++) {
\t\t\t\tpg_after = RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS);
\t\t\t\tif ((pg_after & UVD_PGFSM_STATUS__UVDW_PWR_STATUS_MASK) == 0)
\t\t\t\t\tbreak;
\t\t\t\tudelay(10);
\t\t\t}
\t\t\tif (attempt == 100)
\t\t\t\tWREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG, pg_config);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 JPEG UVDW request: before=%08x/%08x after=%08x/%08x attempts=%u\\n",
\t\t\t\t pg_config, pg_status,
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG), pg_after,
\t\t\t\t attempt);
\t\t} else {
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 JPEG UVDW skipped: config=%08x status=%08x power=%08x\\n",
\t\t\t\t pg_config, pg_status,
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JPEG_POWER_STATUS));
\t\t}
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
    jpeg = base.replace_once(jpeg, '#include "amdgpu.h"',
                             '#include <linux/delay.h>\n#include "amdgpu.h"')
    assert jpeg.count('BC250 JPEG UVDW request:') == 1
    assert jpeg.count('BC250 JPEG scratch:') == 1
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_discovery.c', sources['amdgpu_discovery.c']),
                          ('jpeg_v2_0.c', jpeg)):
        path = DEST / name
        path.write_text(content)
        print(name, base.digest(path.read_bytes()))


if __name__ == '__main__':
    main()
