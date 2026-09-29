# BC250 VCN PSP signature control

## Repeated diagnostic boots

[`iterate_diagnostic.py`](iterate_diagnostic.py) keeps the BC250 in the
isolated diagnostic boot across a batch of VCN trials. Run it from this
repository on the workstation, with SSH access to `root@192.168.0.49` and
`pi@192.168.0.27`:

```sh
python3 tools/vcn-psp-diagnostics/iterate_diagnostic.py status
python3 tools/vcn-psp-diagnostics/iterate_diagnostic.py enter
python3 tools/vcn-psp-diagnostics/iterate_diagnostic.py trial clock-gate-probe
# Repeat `trial MODULE_KIND` with a hash-pinned kind in run_late_vcn_native_clock_trial.py.
python3 tools/vcn-psp-diagnostics/iterate_diagnostic.py finish
```

`enter` loads the pinned RAM-only Pico profile once and boots diagnostics.
Each `trial` checks the board and module, arms a Pi PDU recovery timer, runs
the existing native-clock trial, saves its journal and `dmesg` under ignored
`output/video-decode-20260922/results/`, then cold-cycles directly into
diagnostics and removes the consumed one-shot GRUB entry. The Pico profile
stays in SRAM across those BC250 power cycles. `finish` restores Pico
CS-PASS and normal Fedora once after the batch. A cold cycle between trials
is still required because the SMU clock-table change is not rolled back.
On a timeout or unreachable board, the wrapper leaves the Pi recovery timer
armed and stops; inspect `status` and the Pi timer before resuming. No BIOS
EEPROM or Pico QSPI flash write is part of this workflow.

**Delayed PSP reset sample (2026-09-29):** The guarded
[`prepare_vcn_delayed_reset_read.py`](prepare_vcn_delayed_reset_read.py)
module made one scratch-marked PSP request after the first one-second VCPU
wait. With the corrected RAM-only PSP hook, the initial powered firmware
reload returned `ret=0/status=0`, then the delayed PSP read reported
`UVD_SOFT_RESET` low 28 bits `0` while `UVD_STATUS` remained `4`.
This rules out reset bits 3 and 19 reasserting during the observed wait,
but does not establish firmware fetch or VCPU execution. The three earlier
profiles that moved the signed driver's address table to `0xe19010` failed
the initial PSP request; a relocation-only control reproduced that failure.
Keep both map tables in their proven RX code locations for subsequent tests.
See [the investigation log](../../docs/video-decode-next-step.md) for
evidence and recovery. Normal Fedora is restored; neither flash device
was written and no frame decoded.

**Read-only alternate-cache survey (2026-09-29):** The guarded
[`prepare_vcn_dpg_bank_survey.py`](prepare_vcn_dpg_bank_survey.py) and
[`build_vcn_dpg_bank_survey.sh`](build_vcn_dpg_bank_survey.sh) sampled the
documented DPG VCPU cache bank around the same phase-matched host/PSP
scratch control. DPG BAR/offset/VMID words stayed zero, while conventional
cache-low and soft-reset host reads remained all ones. DPG mode was clear;
the clock/report value `5` does not show VCPU execution. The
[investigation log](../../docs/video-decode-next-step.md) has exact hashes,
limits, and recovery. The board is back on normal Fedora with `amdgpu`
bound. No flash write or decoded frame.

The build script overlays `vcn-psp-driver-20260927/amdgpu_vcn.c`, whose
firmware-path predicate uses PSP loading on this boot. Host startup therefore
tries to map the same TMR firmware address as the PSP replay. The unswapped
kernel-tree source selects a direct buffer for its experimental BC250 path,
but that source was not compiled into this survey; the generic kernel log
message saying "direct-load path enabled" does not distinguish the builds.

**VCN host/PSP shared-register control (2026-09-29):** The guarded
[`prepare_vcn_crosspath_scratch.py`](prepare_vcn_crosspath_scratch.py)
module and a RAM-only signed PSP hook sampled VCN `mmUVD_SCRATCH1` in the
same post-release firmware request. The host BAR accepted and read back
`0x5a13c0de`, and the PSP reported the matching low 28 bits; the host
restored zero. The earlier JPEG scratch trial was not a valid positive
control in the VCN-only startup path because that path does not start the
separate JPEG block. The shared VCN scratch result narrows the unresolved
host cache/reset readback failure to those controls or their gate. See the
[investigation log](../../docs/video-decode-next-step.md) for hashes and
limits. Normal Fedora was restored; no flash write or decoded frame.

**UVDW power control (2026-09-29):**
[`prepare_bc250_jpeg_uvdw_power_probe.py`](prepare_bc250_jpeg_uvdw_power_probe.py)
and [`build_bc250_jpeg_uvdw_power_probe.sh`](build_bc250_jpeg_uvdw_power_probe.sh)
guarded one volatile UVDW-on request by the exact observed JPEG-only PGFSM
baseline. Status changed from `0x00200000` to `0`, but JRBC scratch and ring
registers still ignored writes and the ring timed out. The local UVDW gate
is not sufficient to start JRBC. The [investigation log](../../docs/video-decode-next-step.md)
has hashes, limits and normal-boot recovery. No flash write or frame.

**JPEG JRBC scratch control (2026-09-29):** The opt-in
[`prepare_bc250_jpeg_scratch_probe.py`](prepare_bc250_jpeg_scratch_probe.py)
and [`build_bc250_jpeg_scratch_probe.sh`](build_bc250_jpeg_scratch_probe.sh)
extend the clock/reset probe with one volatile write/read/restore in each of
the JPEG decoder and JRBC scratch subblocks. Decoder scratch read
`0/0x5a13c0de/0`; JRBC scratch read `0/0/0` after a `0xa16bc250` write.
JRBC ring control, size and pointer likewise stayed zero; the ring timed out.
The [investigation log](../../docs/video-decode-next-step.md) records the
module/log hashes, limits and normal-boot recovery. No flash write or frame.

**JPEG clock/reset result (2026-09-29):** The opt-in
[`prepare_bc250_jpeg_reset_clock_probe.py`](prepare_bc250_jpeg_reset_clock_probe.py)
samples status before and after the existing ring test. Both snapshots read
`JPEG_SOFT_RESET_STATUS=0`, `UVD_JRBC_SOFT_RESET=0`,
`JPEG_SOFT_RESET2=0`, JPEG power `0`, and `JPEG_CGC_STATUS=0x1cf`
(documented JPEG decode/JRBBM clocks active), while ring control, size and
write pointer remained zero and the test timed out. This shifts the next
check toward JRBC register-path permission/availability or another internal
condition. The [investigation log](../../docs/video-decode-next-step.md)
records the hashes, limits and normal-boot recovery. No flash write or frame.

**JPEG ring readback result (2026-09-29):** Under the combined early/late
client-12 Pico policy, [`prepare_bc250_jpeg_readback_probe.py`](prepare_bc250_jpeg_readback_probe.py)
and [`build_bc250_jpeg_readback_probe.sh`](build_bc250_jpeg_readback_probe.sh)
produced a hash-pinned, opt-in JPEG-only module. The JPEG power request and
ring BAR read back, but `JRBC_RB_CNTL`, `JRBC_RB_SIZE`, and the MMIO write
pointer read zero; the latter was sampled immediately after writing `0x10`.
The ring test timed out. This narrows the fault to JRBC access/startup or an
upstream clock/reset/isolation condition, without proving which. The
[investigation log](../../docs/video-decode-next-step.md) has the trial,
limits, hashes and normal-boot recovery. No firmware flash was written and
no frame decoded.

**PSP TMR phase result (2026-09-29):**
[`prepare_vcn_psp_phase_probe.py`](prepare_vcn_psp_phase_probe.py) and
[`build_vcn_psp_phase_probe.sh`](build_vcn_psp_phase_probe.sh) add read-only
VCN snapshots around PSP startup calls. The partial VCN power-register
aperture appeared during `psp_tmr_load()`, which submitted
`GFX_CMD_ID_SETUP_TMR` with a real TMR buffer. PGFSM/power/version were
all ones after ring creation and TMR allocation, then `0x00200000`,
`0x801`, `0xdeadbeef` after TMR setup. The local VCN power sequence exposed
version `0x2001b` while `CC_UVD_HARVESTING` remained `3`, but the VCPU
still did not start. The [journal](../../output/video-decode-20260922/results/vcn-psp-phase-active-20260929.jsonl)
and [investigation log](../../docs/video-decode-next-step.md) give the
trace and normal-boot recovery. No flash device was written.

**GPU IP phase result (2026-09-29):**
[`prepare_vcn_ip_phase_probe.py`](prepare_vcn_ip_phase_probe.py) and
[`build_vcn_ip_phase_probe.sh`](build_vcn_ip_phase_probe.sh) add read-only
snapshots around PSP firmware loading and each GPU hardware-init block.
With 1,402 verified RAM-only Pico substitutions, VCN power-state registers
changed from all ones to `PGFSM_STATUS=0x00200000` and
`POWER_STATUS=0x801` during `psp_hw_init()`. Later SMU, display, GFX and
SDMA init did not change them. Local VCN power release exposed
`VERSION=0x2001b`, but VCPU ready never appeared. The [journal](../../output/video-decode-20260922/results/vcn-ip-phase-active-20260929.jsonl)
and [investigation log](../../docs/video-decode-next-step.md) give the
details and recovery. PSP ring setup, `psp_hw_start()` and non-PSP firmware
loading are the next boundaries to isolate. No flash device was written.

**Phase-matched startup result (2026-09-29):**
[`prepare_vcn_startup_phase_probe.py`](prepare_vcn_startup_phase_probe.py)
and [`build_vcn_startup_phase_probe.sh`](build_vcn_startup_phase_probe.sh)
add six read-only VCN register snapshots to the pinned direct-BO module.
With the verified 1,402-substitution RAM-only signed-driver Pico profile,
registers were all ones through VCN software init/resume. By VCN start
entry, `PGFSM_STATUS=0x00200000`, `POWER_STATUS=0x801`; the generic SMU
power call changed neither. The local static power-gating release made
`PGFSM_STATUS=0`, `POWER_STATUS=0x800`, and `VERSION=0x2001b`.
`CC_UVD_HARVESTING` remained `3` while these powered registers responded.
The VCPU still did not become ready and the ring timed out. Matched
CS-PASS controls returned all ones. The [active-profile
journal](../../output/video-decode-20260922/results/vcn-startup-phase-active-20260929.jsonl)
and [investigation log](../../docs/video-decode-next-step.md) record the
trial, its limits and normal-boot recovery. No flash device was written.

**Status-versus-control correction (2026-09-29):** Treat
`CC_UVD_HARVESTING=3` as a disable/availability indication, not a proven
writable VCN start control. It predates Linux VCN startup and guarded PSP
and powered-host clear attempts read back `3`. Cyan Skillfish supplies no
VCN/JPEG power callback to generic amdgpu, so the normal SMU power request
returns without issuing a command. A JPEG-only probe without VCPU firmware
timed out; a follow-up raw read showed both `UVD_PGFSM_CONFIG` and
`UVD_PGFSM_STATUS` were `0xffffffff` before and after the request. The
earlier wait's `0x00c00000` was **masked bits 22-23**, not a full-register
proof of an off tile. `JPEG_HWIP` aliases the mapped VCN base, so the next
question is what makes that host register aperture respond during the
fully powered VCN path. See the [investigation log](../../docs/video-decode-next-step.md)
for the traces, recovery and limits. No flash write or decoded frame.

**VCPU reset-stability readback (2026-09-28):** With the native VCLK code
16 applied, a RAM-only signed PSP hook wrote `UVD_SOFT_RESET=0` once and
read it 128 times. The final PSP value was still zero, yet `UVD_STATUS=4`
and the decode ring timed out. This excludes rapid reassertion during the
sample, not a later change or a separate firmware-fetch/isolation fault.
See the [journal](../../output/video-decode-20260922/results/native-reset-stability-20260929.jsonl)
and [investigation log](../../docs/video-decode-next-step.md). The BC250
was returned to normal boot; no flash write or decoded frame.

**Native-clock MMSCH reset readback (2026-09-28):** The guarded RAM-only
profile read PSP `UVD_SOFT_RESET2=0x00030000` after the signed driver's
cache-window replay and Linux's release sequence, with SMU VCLK clock code
16 applied. Bits 16/17 report MMSCH VCLK/SCLK still in reset; bit 0 is clear.
The VCPU still did not report ready (`UVD_STATUS=4`). This is a status
measurement, not evidence that writing those bits starts VCN. The [journal](../../output/video-decode-20260922/results/native-reset2-beforewrite-20260929.jsonl)
and [investigation log](../../docs/video-decode-next-step.md) record the
trial and normal-boot recovery. Neither flash device was written.

**Native-clock reset readback (2026-09-28):** The corrected RAM-only Pico
profile read PSP `UVD_SOFT_RESET=0x00080008` after Linux's VCPU release with
SMU slot `0x17` hardware clock code 16 applied. Bit 3 (`VCPU_SOFT_RESET`)
and bit 19 (`VCPU_VCLK_RESET_STATUS`) remained set; `UVD_STATUS=4` lacked
the VCPU-ready bit. The prior PSP result of zero came from a hook that wrote
zero before reading; it also failed to start the VCPU. The corrected
profile's native ARM model passed 28 cases and Pico verified 1,402/1,402
boot substitutions. The first build used an older TMR hook, gave all-ones
VCN reads and is inconclusive. Full evidence and the normal-boot recovery
record are in [the investigation log](../../docs/video-decode-next-step.md).
No BIOS EEPROM or Pico QSPI write was made; no frame decoded.

**Native-clock decoder trial (2026-09-28):**
`trial_smu_clock_callback_once.py` stages the 1250 MHz VCN request before
advancing the SMU clock-table generation. The periodic callback then applied
clock code 16, and normal-boot GPU metrics read VCLK 1250 MHz. The
`trial_smu_clocked_gate_probe.py` gate/domain follow-up still found VCN MMIO
all ones on that normal boot. On an opt-in diagnostic boot,
`run_late_vcn_native_clock_trial.py` combined the same SMU-native clock and
previously tested gate/power writes with the pinned RAM-only Pico interposer
and VCN module. PSP firmware loading succeeded and the powered tile reported
`UVD_VERSION=0x2001b`, but the VCPU trace PC sampled zero, host readbacks of
reset and firmware-cache registers stayed all ones, status stayed `4`, and
the VCN ring timed out. Earlier PSP-side trials did read/write those latter
registers; the host readback alone does not establish their hardware state.
Raw journals are under `output/video-decode-20260922/results/` with
`clock-callback-once`, `clocked-gate-probe`, and `native-clock-vcn-startup`
prefixes. This rules out the previously missing native VCLK request as a
complete fix. `CC_UVD_HARVESTING=3` remains an observation, not a proven
writable power-on control. No BIOS/Pico flash was written and no frame decoded.

**SMU native-clock result (2026-09-28):** The
[`trial_smu_clock_walker.py`](trial_smu_clock_walker.py) preflight and Q3
`0x1d` zero-request no-op passed on the board. A guarded RAM-only 1250 MHz
request for VCN slot `0x17` acknowledged, but the applied request, hardware
clock code and VCLK metric all stayed zero. Restoration of the table
generation stalled the SMU; isolated PDU outlet 8 recovered the board, and
the next boot matched the original table. `native-clock` is disabled at the
CLI until its generation race and rollback are understood. The three offline
rollback checks are in `test_trial_smu_clock_walker.py`; raw evidence is in
`output/video-decode-20260922/results/clock-walker-*-20260928.jsonl`.
No BIOS/Pico flash was written and no frame decoded. The accepted mailbox
reply is not evidence that VCN started.

**Interpretation update (2026-09-28):** The observed
`CC_UVD_HARVESTING=3` is a disable indication, but its writability and causal
role have not been proved. The VCN 2.0 Linux startup path does not read it.
That path's conditional SMU VCN power request returns success without a
hardware action because `cyan_skillfish_ppt_funcs` has no
`.dpm_set_vcn_enable` callback. The actual missing power/clock/isolation
sequence is the next target on an opt-in VCN 2.0.3 boot; the normal boot does
not register a VCN ring. See [the investigation
log](../../docs/video-decode-next-step.md) for source references and limits.

**Direct SMU-core VCN-clock trial (2026-09-28):**
`smu-direct-clock-read.py` found that a direct Xtensa read of Van Gogh's
`0x0116f200` address stalled on the BC250, while a known live direct-read
control returned. The separate `smu-direct-clock-write.asm` helper and
`smu-direct-clock-write.py` runner avoid reading that target. Six Ghidra
emulation cases passed for each helper. Under a recovery timer, volatile
stores `0`, `1`, `0` each returned SMU success. V2.2 GPU VCLK/DCLK metrics
remained `0/1111` MHz; the helper SRAM was restored and verified. No VCN
frame decoded. The ignored evidence is under
`output/video-decode-20260922/smu-direct-clock-20260928/`; neither SPI flash
was written. The Van Gogh VCN entry and inner function have no identical
16-byte code window in the captured BC250 SMU image, though other SMU
functions share exact code. That byte comparison cannot alone locate the
BC250's missing enable path; `compare_smu_vcn_windows.py` reproduces the
pinned 16-byte window report.

**Guarded LMI control trial (2026-09-28):**
`prepare_vcn_lmi_oracle_trial.py`, `build_vcn_lmi_oracle_trial.sh`, and
`run_late_vcn_lmi_oracle_trial.py` tested one volatile LMI_CTRL word derived
from an archived PS5 manufacturing-driver decompile. The original ELF is
unavailable, so the setting was a hypothesis. On a pinned diagnostic boot,
the write `0x00307340 → 0x00307108` read back correctly after a successful
PSP VCN firmware load. VCPU PC remained zero, status remained the driver's
BUSY value `4`, and the GPU did not bind; no frame was decoded. The module
SHA256 was `56343ccf27087c59e3f86fb22536decc365519b4d4e8c25bac0e027cfd8a89e1`.
The ignored evidence is under
`output/video-decode-20260922/results/late-vcn-lmi-oracle-v01-20260928.*`.
No BIOS EEPROM or Pico QSPI write occurred. The operational
`CC_UVD_HARVESTING=3` state remains unresolved.

**Powered VCN free counter (2026-09-28):**
`prepare_vcn_free_counter.py`, `build_vcn_free_counter.sh` and
`run_late_vcn_free_counter.py` sample `UVD_FREE_COUNTER_REG` before and
after a guarded VCPU clock-enable toggle. All four reads were zero, while
the adjacent VCPU control bit again cleared and restored on readback.
The free counter's enable conditions are undocumented in the available
register definitions, so this does not prove whether the physical clock is
oscillating. PSP firmware load succeeded, but the GPU did not bind.
Evidence is in ignored
`output/video-decode-20260922/results/late-vcn-free-counter-v01-20260928.*`.
No BIOS EEPROM or Pico flash write occurred, and no frame was decoded.

**VCPU clock readback (2026-09-28):**
`prepare_vcn_vcpu_clock_readback.py`, `build_vcn_vcpu_clock_readback.sh` and
`run_late_vcn_vcpu_clock_readback.py` form a guarded one-shot trial after a
successful PSP firmware load. Before Linux's VCPU reset-release step, they clear only
`UVD_VCPU_CNTL.CLK_EN`, read it, then restore the original word. The observed
sequence was `0x0ff20200 → 0x0ff20000 → 0x0ff20200`, so this host write is
effective at the register level. Harvest remained `3`, the reset/cache
registers read all ones, and the VCN ring did not start. Evidence is in
ignored `output/video-decode-20260922/results/late-vcn-vcpu-clock-readback-v01-20260928.*`.
Neither flash device was written; no frame was decoded.

**Powered direct-buffer trial (2026-09-28):**
`prepare_vcn_direct_bo_powered.py`, `build_vcn_direct_bo_powered.sh` and
`run_late_vcn_direct_bo_powered.py` select the ordinary firmware BO path for
the pinned Navi 10 VCN image, with the VCN tile visibly powered and guarded
direct reset writes. The firmware BO was allocated, but harvest stayed `3`,
VCN status stayed `4`, and the GPU did not bind. The diagnostic never wrote
BIOS or Pico flash. Evidence is in ignored
`output/video-decode-20260922/results/late-vcn-direct-bo-powered-v01-20260928.*`.

**Powered version and direct-reset trials (2026-09-28):**
`prepare_vcn_version_probe.py`, `build_vcn_version_probe.sh`, and
`run_late_vcn_version_probe.py` measured `UVD_VERSION=0xdeadbeef` before
host VCN power-up and `0x0002001b` afterward, including both sides of VCPU
reset release. The PSP firmware request succeeded, but harvest stayed `3`
and `UVD_STATUS` stayed at the driver's own BUSY value `4`. Because
`UVD_SOFT_RESET` reads all ones,
`prepare_vcn_direct_reset_after_psp.py`,
`build_vcn_direct_reset_after_psp.sh`, and
`run_late_vcn_direct_reset_after_psp.py` then tested guarded direct reset
writes after a successful PSP load. These also left status at `4` and did
not bind the GPU. The board logs are in ignored
`output/video-decode-20260922/results/late-vcn-{version-probe,direct-reset-after-psp}-v01-20260928.*`.
These are volatile, one-shot diagnostic modules; neither flash device was
written. The working question is now where the live harvest state is
established or locked before the first VCN firmware request.

**Powered host-write result (2026-09-28):** The guarded module generated by
`prepare_vcn_harvest_write.py` checked the pinned allocations and adjacent
power registers, then wrote zero once to host-MMIO `CC_UVD_HARVESTING` only
when its initial value was exactly `3`. Immediate readback remained `3`; the
VCN ring still timed out. A later diagnostic PSP reload in that same run
failed, so the ring timeout is not an isolated effect of this write. A
separate clean PSP-load trial also left VCPU status at `4`.
`build_vcn_harvest_write.sh` and
`run_late_vcn_harvest_write.py` pin the build and one-time diagnostic runner.
Raw evidence is in ignored
`output/video-decode-20260922/results/late-vcn-harvest-write-v01-20260928.*`.
The unchanged readback does not distinguish a physical fuse from a locked
shadow or read-only register.

**Host-MMIO result (2026-09-28):** A guarded, default-off amdgpu probe read
the powered VCN 2.0 `CC_UVD_HARVESTING` through the GPU BAR and got `0x3`.
The adjacent `UVD_POWER_STATUS=0x800` and `UVD_PGFSM_STATUS=0` confirmed the
probe's expected power state. Bits 0 and 1 are named `MMSCH_DISABLE` and
`UVD_DISABLE` in the VCN register definition. This proves the live register's
disable state, but not whether physical fuses or an earlier latched setting
supplied it. The GPU still failed its VCN ring and no frame was decoded.
`prepare_vcn_harvest_mmio.py`, `build_vcn_harvest_mmio.sh`, and
`run_late_vcn_harvest_mmio.py` reproduce the pinned, one-shot diagnostic;
the raw dmesg line is in ignored
`output/video-decode-20260922/results/late-vcn-harvest-mmio-v01-20260928.dmesg`.

**Address-space qualification (2026-09-28):** PSP services `0x7b` and `0x7c`
use a page-selected SMN aperture. Run `verify_svc7b_address_space.py` with
the pinned private Trusted OS and Unicorn to reproduce that mapping offline.
Equal numeric SMN and GPU MMIO offsets do not alone prove an alias. However,
three same-boot PSP reads matched host-MMIO VCN values exactly (VCPU control,
LMI control 2 and LMI status), providing strong alias evidence for those
registers. The direct host read now independently corroborates the PSP-side
`0x1f81c → 3` measurement; physical disable-fuse provenance is unproven.

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
