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

The separate video-TMR profile moved the accepted firmware address to
`0xf41fa00000` and let graphics KIQ pass. The opt-in VCN ring then timed out
because VCN power/status registers read as all ones. The bound-GPU
`run_late_vcn_psp_probe.py` control confirmed status `0` at the same address
while VCN version/status/power stayed `0xffffffff` before and after loading.
The clock pulse must precede module insertion and `SETUP_TMR` on this profile.

`run_post_auth_native_cycle.py` repeats the host-tested, bounded SMU client-12
down/up sequence only after verifying that successful late PSP load in the
current diagnostic boot. Its default mode is read-only preflight; `--run`
requires a staged diagnostic recovery boot and active recovery timer. The live
sequence returned full PSP success for commands 7 and 6, restored its primary
control baseline, but did not expose VCN registers. Raw evidence is under
ignored `output/pico2/type51-live-20260927/post-auth-native-cycle/`. It makes
no BIOS EEPROM or Pico flash writes.

`run_post_auth_smn_read.py` verifies a fresh late load in the same boot, holds
the known VCN clocks/power state, and reads only the full-address
`0x0900c004` reset-page word after two known domain-6 controls. It requires
the inspected one-time diagnostic entry and a recovery timer because the
same target hung when read with clocks off in an older trial. With clocks on
after a successful firmware load, the target returned `0xffffffff`; the
domain controls returned their expected values, and clock restoration passed.
The board stayed in diagnostic mode. Raw evidence is under ignored
`output/pico2/type51-live-20260927/post-auth-smn-read/`.
`cleanup_unconsumed_diagnostic_boot.sh` removes an unused staged recovery entry
after checking its exact hash and GRUB flag; the older cleanup script applies
only after that one-time entry has actually been consumed by a reboot.
