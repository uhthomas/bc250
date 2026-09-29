#!/usr/bin/env python3
"""Move the guarded VCN PSP readback to after the host programs cache BARs."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-postpower-reload-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-postcache-reload-20260927/vcn_v2_0.c'
SOURCE_SHA = 'b4a6f3600747f2a7ca28be50e8a2bb82cc49a02b9cc3e5e993e2672422cab612'
START = '\tvcn_v2_0_disable_static_power_gating(vinst);\n\n'
END = '\n\t/* set uvd status busy */'
MC = '\tvcn_v2_0_mc_resume(vinst);\n'


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(START) == source.count(END) == source.count(MC) == 1
    prefix, rest = source.split(START, 1)
    readback, suffix = rest.split(END, 1)
    assert readback.startswith('\tif (adev->pdev->device == 0x13fe) {')
    assert readback.count('psp_execute_ip_fw_load(&adev->psp, ucode)') == 1
    source = prefix + START + END.lstrip('\n') + suffix
    source = source.replace(MC, MC + '\n' + readback + '\n', 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
