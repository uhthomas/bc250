#!/usr/bin/env python3
"""Test whether the powered VCN ring can execute a scratch-register packet.

The control module demonstrated a fetch and a GPCOM stall with the kernel's
normal packet-start command. This variant removes that command and places a
scratch write first, testing the ring command processor independently of the
VCPU handshake. It retains the NO_FETCH negative control and all guards.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-control-20260929/vcn_v2_0.c'
SOURCE_SHA = 'bc12c248bff591e78c3f7f2a7ebc29610a4619c39c76995c46da1b9c705d86dd'
DEST = BUILD / 'vcn-rbc-direct-packet-20260929'
OLD = '''\t\t/* Match vcn_v2_0_dec_ring_test_ring(), then pad to the
\t\t * hardware's 16-dword WPTR granularity with valid NOP packets.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(adev->vcn.inst[0].internal.cmd, 0));
\t\tWRITE_ONCE(ring->ring[1],
\t\t\t   VCN_DEC_KMD_CMD | (VCN_DEC_CMD_PACKET_START << 1));
\t\tWRITE_ONCE(ring->ring[2], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[3], 0xdeadbeef);
\t\tfor (sample_i = 4; sample_i < 16; ++sample_i)
'''
NEW = '''\t\t/* Try the scratch write as the first packet, without the
\t\t * firmware-mediated GPCOM packet-start command. Pad to 16 dwords.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[1], 0xdeadbeef);
\t\tfor (sample_i = 2; sample_i < 16; ++sample_i)
'''


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned RBC control source changed')
    source = data.decode()
    if source.count(OLD) != 1:
        raise ValueError('RBC packet anchor changed')
    source = source.replace(OLD, NEW, 1)
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-rbc-control-20260929/amdgpu_vcn.c'
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
