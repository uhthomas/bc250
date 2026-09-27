# BC250 VCN PSP signature control

`prepare_signature_control.py` generates a default-off Fedora 7.2.5 amdgpu
diagnostic source from pinned local inputs. Its debugfs probe accepts only
variant 4: it copies the installed, hash-checked `navi10_vcn.bin` payload,
changes its last signed byte at offset `0x6147f`, then submits one type-13
`LOAD_IP_FW` request. The candidate is invalid by construction and never
replaces the firmware file. The probe does not enable VCN startup or read VCN
registers. The module is loaded only on the isolated one-time boot described
in [the trial record](../../docs/pico2-type51-vcn-trial.md).

`run_signature_control.py` checks the one-time boot flags, module and firmware
hashes, disabled VCN startup, enabled probe, and absence of another PSP
response before issuing one request. It applies the previously measured
clock/power sequence and restores it afterward. The private built module and
raw logs are in ignored `output/` directories; the board BIOS was never
written for this control.

On 2026-09-27 the Pico verified all 138 changed key-database responses during
the boot. Both intact and signed-byte-tampered firmware requests returned
`0x80000029`. This does **not** prove that the PSP verified the intact
firmware's signature: the error may precede signature checking or mask a later
result. There is still no working VCN block or hardware decoded frame.

`prepare_rlc_comparison.py` and `run_rlc_comparison.py` compare two invalid
signed images on one PSP ring: graphics RLC type 8 produced `0xffff3072`, and
VCN type 13 produced `0x80000029`. The type-19 comparison timed out and was
aborted before its second request. `prepare_early_type13.py` builds a
default-off probe immediately after PSP TMR setup; `run_early_type13.py`
checks the diagnostic boot and pinned module/firmware before enabling clocks
and submitting the invalid type-13 payload. It can use the kernel's
`debug_mask=8` VRAM staging option. The early response was still
`0x80000029`; with VRAM staging the MMHUB fault address was outside the
logged firmware, command, fence, TMR, VRAM and GART ranges. A full log from a
late VCN load shows `0x80000029` without any MMHUB page fault, so the early
fault is not required for that status. The evidence and limits are recorded in
[the trial record](../../docs/pico2-type51-vcn-trial.md).

The early module deliberately aborts GPU probing after its single request.
The resulting upstream driver cleanup emits IRQ warnings; the board stays
reachable over SSH with its GPU unbound. The runner restores only the
temporary SMU clock controls after a completed PSP response. It leaves the
Fedora diagnostic boot in place and does not program either flash device.

# 2026-09-27 live result

The early type-13 probe under the RAM-only metadata-patched PSP driver now
separates signature failure from the preceding video-state failure. A signed
byte change returned `0xffff3072`; the intact firmware returned status `0x0`
with TMR address `0xf41f800000`. Both probes deliberately abort subsequent
graphics initialization, so neither demonstrates VCN execution or decoding.
`prepare_vcn_psp_driver.py` and `run_vcn_psp_driver.py` prepare a guarded,
default-off follow-up that registers VCN 2.0.3 but retains PSP loading.
