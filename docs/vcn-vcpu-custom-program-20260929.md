# BC250 VCN VCPU custom-program probes, 2026-09-29

The VCN VCPU has **not** yet been observed decoding an instruction. Two
temporary GPU-buffer canaries and a direct harvest-register trial completed
on the BC250 without any BIOS EEPROM, Pico QSPI, installed firmware or bootc
image write. The board returned to clean diagnostic boot
`b1dda54a-6aae-4695-8579-0d0c5f89ff02`, with `/boot` read-only, no
one-shot GRUB entry and no armed Pi PDU timer. The Pico's SRAM-only
`vcn-tmr-rbc-writer-stage` profile reports `fault=0`.

The pinned Linux 7.2.5 VCN 2.0 driver has a direct-load path that copies the
firmware payload into the VCPU's GPU buffer. For diagnostics, an opt-in module
can alter that **temporary buffer after the copy**. This does not require a
PSP write into the authenticated video TMR. It still requires the VCPU to
leave its upstream clock/reset/availability gate before any instruction can
run. The buffer layout and stack BAR come from the local
[`amdgpu_vcn.c`](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_vcn.c)
and [`vcn_v2_0.c`](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu/vcn_v2_0.c).

The firmware payload is SHA256
`a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5`.
Focused Xtensa disassembly found a plausible reset/bootstrap sequence at
payload offset `0x280`, with its first visible external store at `0x454`.
The code at `0x240` is a register-window underflow handler, so it must not be
treated as the reset entry. Offset `0xf208` is a separate `entry a1,0x70`
routine whose reachability at startup is unproven.

| Probe | Temporary buffer edit | Positive witness | Live result |
| --- | --- | --- | --- |
| [Write and loop](../tools/vcn-psp-diagnostics/prepare_vcn_vcpu_marker_stub.py) | At `0xf208`, `l32r a2,0xe200; l32r a3,0xe204; s32i a3,a2,0; j self`. Literals hold target `0x6100ffd0` and marker `0x7bc25001`. | Host sees `0x7bc25001` at the inferred stack buffer offset `0x73fd0`. | Program and literals read back correctly; target stayed zero before, after the calibrated RBC reset pulse and at the first wait. |
| [Early bootstrap store](../tools/vcn-psp-diagnostics/prepare_vcn_vcpu_early_store.py) | Keep the firmware's `s32i.n a3,a2,0` at `0x454`; change its `0x124` literal to `0x7bc25002`; replace the following instruction at `0x456` with `j self` (`06ffff`). | Host sees `0x7bc25002` at `0x73fd0`; the loop should prevent later firmware code from erasing it. | Changed bytes read back correctly; target stayed zero before, after reset pulse and at first wait. |
| [Harvest latch](../tools/vcn-psp-diagnostics/prepare_vcn_vcpu_harvest_try.py) | On the powered VCN, write `0` once to `CC_UVD_HARVESTING` while retaining the early-store canary. | `CC_UVD_HARVESTING` reads back `0` and/or early marker appears. | It read `3→3`; marker stayed zero. |

Ghidra assembled and decoded the custom `l32r/s32i/j` sequence, and
[`GhidraVcnEarlyStoreAsm.java`](../tools/vcn-psp-diagnostics/GhidraVcnEarlyStoreAsm.java)
verified that `06ffff` is `j 0x456` at the early trap address. The modules
read back the patched BO bytes before VCPU release. The RBC reset packets
reached `RPTR=16/32` and changed their scratch markers as expected. Yet
`UVD_STATUS` stayed at the driver's `4`, VCPU trace PC and PRID stayed zero,
and the VCN decode ring timed out. These are **negative observations**, not
proof that a VCPU fetch is impossible: the stack's VCPU-to-host mapping and
the precise reset vector remain inferred, and the PC trace lacks a positive
calibration on this board.

A blocked fetch has several possible meanings here. The VCPU might never
issue a request because a physical clock, internal reset or isolation gate
remains closed; it might issue a request that the instruction-cache/LMI path
cannot service; or it might run without reaching our observed store. The RBC
ring controller is a separate requester, so its proven packet fetch does
not prove VCPU instruction fetch. Earlier signed PSP readback confirmed the
VCPU soft-reset and VCLK-reset-status bits clear after release, the sixteen
cache-window values match, and the VCPU clock-enable control propagates.
Those facts narrow the simple register-programming mistakes, but do not
establish physical clock activity or a serviced instruction request. A
phase-matched LMI counter stayed zero during VCPU release and counted ring
traffic in the same boot; its event meaning for VCPU fetch is undocumented.

Evidence:

| Trial | Journal SHA256 | Kernel log SHA256 |
| --- | --- | --- |
| [Write and loop](../output/video-decode-20260922/results/bc250-vcn-vcpu-marker-stub-20260929T214638Z-87870a.jsonl) | `ee923e304f24d171712abe541b6574fc24bc3632c7667fa627ebf54e0091252a` | [`d5d994a9011240f08856798ea960c1a7c94ebd7492eadf24b9fbdf3f63a59583`](../output/video-decode-20260922/results/bc250-vcn-vcpu-marker-stub-20260929T214638Z-87870a.dmesg) |
| [Early store](../output/video-decode-20260922/results/bc250-vcn-vcpu-early-store-20260929T215554Z-b4e78e.jsonl) | `09673be8149d966672436f01a5ba4d0799f60138b8aadf8789c564e099090c5d` | [`642bb9831dc9c43a20fb61f4aa17cd09e078b26c3083d773c1fc29601a96854f`](../output/video-decode-20260922/results/bc250-vcn-vcpu-early-store-20260929T215554Z-b4e78e.dmesg) |
| [Harvest write](../output/video-decode-20260922/results/bc250-vcn-vcpu-harvest-try-20260929T220210Z-0ab7a4.jsonl) | `e0bf25d092568941de36fe4a2a39455d9dd5e0ab7620b918030bd4e13594151f` | [`b9fdb465951628cdd68b586861836ea4dfbf2945b88e0925597e58ca894b2409`](../output/video-decode-20260922/results/bc250-vcn-vcpu-harvest-try-20260929T220210Z-0ab7a4.dmesg) |

The attempted PSP-side TMR writer is a separate path. A stage-marker version
reached its hook (`UVD_SCRATCH1=0x7a000001`) but timed out at or after the
PSP `SVC 0x89` TMR-map call, before any confirmed write. Its
[journal](../output/video-decode-20260922/results/bc250-vcn-rbc-tmr-psp-writer-stage-20260929T212352Z-275891.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-rbc-tmr-psp-writer-stage-20260929T212352Z-275891.dmesg)
have SHA256 `29606e088cf9378849a70f770652b5b4cf71685aefd16cf4f91dfe75ed501cc1`
and `ad4efc3dad2de74c9c930154c6d9a2633943f1944a364543e3553453c34e9ffc`.
Thus the direct GPU-buffer route is the practical custom-program path for
now; the PSP TMR route has an unresolved map stall.

The next useful gate is the origin of `CC_UVD_HARVESTING=3`. The VCN 2.0
register header labels its bits 0 and 1 `MMSCH_DISABLE` and `UVD_DISABLE`.
The value was already present at ABL0's first instruction, before Linux
initialized the decoder. Previous [guarded ABL0, TOS and powered host-MMIO
writes](video-decode-next-step.md) of zero also read back `3`; this run
reconfirms the host result while observing the early-store canary. The ROM
IP-discovery record reports `harvest=0`, so that inventory and the
operational register disagree.
None of these refused writes distinguishes a physical fuse from an earlier
signed-policy, strap or SMU latch. A previous
[out-of-VRAM BAR trial](../output/video-decode-20260922/results/bc250-vcn-vcpu-pif-interrupt-20260929T201652Z-fd71be.jsonl)
latched both named PIF address-error enables yet saw no address-error status;
that route has no calibrated positive response for VCPU instruction fetch.
AMD has said that VCN was outside the [BC-250 product
definition](https://www.mail-archive.com/amd-gfx@lists.freedesktop.org/msg148015.html),
and that individual dies or missing platform power support could matter;
that statement does not identify the cause on this board.
Trace the producer of the pre-ABL0 disable indication before further buffer
variants or firmware flashes. If the VCPU starts, the early-store canary is
a short witness that can then be extended to a standalone minimal program
and a frame test.
