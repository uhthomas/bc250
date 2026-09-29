#!/usr/bin/env python3
"""Prepare one guarded, volatile VCN harvest write/readback diagnostic."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-harvest-mmio-20260928/vcn_v2_0.c'
DEST = BUILD / 'vcn-harvest-write-20260928/vcn_v2_0.c'
SOURCE_SHA = '988f047eb64134f1e19730606e461847dd634a71c37211fddb396a4364006b36'
START = '\t/* Read the actual PCI BAR VCN register only after the adjacent power\n'
END = '''\n\tif (adev->pdev->device == 0x13fe) {
\t\tstruct amdgpu_firmware_info *ucode =
'''
MATCH = '''\t\tdev_warn(adev->dev, "BC250 VCN postrelease allocation matched\\n");
'''
PROBE = '''\t\t/* One volatile host write after the exact allocation guard and
\t\t * only for the proven BC250 power and harvest state. The runner
\t\t * stages recovery before insertion; readback flushes the write.
\t\t */
\t\t{
\t\t\tu32 power = RREG32_SOC15(VCN, 0, mmUVD_POWER_STATUS);
\t\t\tu32 pgfsm = RREG32_SOC15(VCN, 0, mmUVD_PGFSM_STATUS);

\t\t\tif (power == 0x800 && pgfsm == 0) {
\t\t\t\tu32 before = RREG32_SOC15(VCN, 0, mmCC_UVD_HARVESTING);

\t\t\t\tif (before == 3) {
\t\t\t\t\tu32 after;

\t\t\t\t\tWREG32_SOC15(VCN, 0, mmCC_UVD_HARVESTING, 0);
\t\t\t\t\tafter = RREG32_SOC15(VCN, 0, mmCC_UVD_HARVESTING);
\t\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t\t "BC250 VCN harvest write: power=%08x pgfsm=%08x before=%08x after=%08x\\n",
\t\t\t\t\t\t power, pgfsm, before, after);
\t\t\t\t} else {
\t\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t\t "BC250 VCN harvest write skipped: unexpected before=%08x\\n",
\t\t\t\t\t\t before);
\t\t\t\t}
\t\t\t} else {
\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t "BC250 VCN harvest write skipped: power=%08x pgfsm=%08x\\n",
\t\t\t\t\t power, pgfsm);
\t\t\t}
\t\t}
'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(START) == source.count(END) == 1
    start = source.index(START)
    end = source.index(END, start)
    source = source[:start] + source[end:]
    assert source.count(MATCH) == 1
    source = source.replace(MATCH, MATCH + PROBE, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
