# Next hardware-decode investigation step

**Update 2026-09-29, ring cache-size write verified through the PSP:**
The [guarded readback probe](../tools/vcn-psp-diagnostics/prepare_vcn_rbc_cache_readback_trial.py)
held VCPU reset and used `PACKET0(0x1c3,0)` to change the firmware-cache
size from the pinned `0x64000` to a temporary `0x63000`. After the first
ring marker executed (`RPTR=16`, scratch `0x11112222`), the signed,
RAM-only PSP pre-map hook compared all sixteen cache words **before** any
second-call write. It returned `0x71363000`: first mismatch at index 3,
with the observed value `0x63000`. The ring then restored size `0x64000`
(`RPTR=32`, scratch `0x33334444`), and the PSP returned `0x70000010`,
meaning all sixteen full-width values matched. A final unmarked signed
map replay returned `ret=0/status=0`. This is direct evidence that the
ring delivered the intended address **and data** to a VCPU cache register;
it also verifies restoration. The earlier clock-control calibration gives
an independent positive target readback at ring address `0x1d8`.

The [journal](../output/video-decode-20260922/results/bc250-vcn-rbc-cache-readback-20260929T173924Z-d16904.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-rbc-cache-readback-20260929T173924Z-d16904.dmesg)
have SHA256 `d60c52ec3028823911474d77e771740c08125907adec6087ee255fcb3a27ba48`
and `de5b9ab5e39e6df9376f49da2d0b36881d139eed9bf9ca9a3bbd07ab293ae39b`.
The BAR, offset and reset ring writes remain unproven individually because
their values were the pre-existing values and host reads return all ones.
The PSP-visible original map is correct, however, and `UVD_STATUS` still
remains `4`: the VCPU has not reported ready or a decoded instruction.
The BC250 recovered to clean diagnostic boot
`d561f7cc-a062-49d2-80a3-2dae84aea324`, `/boot` read-only, no pending
GRUB entry or Pi timer; the proven BO-premap Pico profile is active in
SRAM with no fault or mismatches. No BIOS EEPROM or Pico QSPI write occurred.
The next useful address check is a PSP-side read of the ring's reset
assertion/release, followed by upstream VCPU enable/fetch investigation.

**Update 2026-09-29, corrected VCPU ring address:** The in-tree VCN 2.0
driver uses ring-internal offsets `0x80` below host segment-1 offsets
(GPCOM DATA0 `0x584→0x504`, NO_OP `0x5bf→0x53f`). Thus host
`UVD_VCPU_CNTL=0x258` is ring address `0x1d8`. A guarded two-stage
`PACKET0(0x1d8,0)` calibration changed the host readback
`0x0ff20200→0x0ff20000→0x0ff20200`: the ring turned `CLK_EN` off and
then back on. `RPTR` advanced `0→16→32`, both distinct scratch markers
executed, and no host restore was used. This proves the ring fetched the
intended words and the corrected address reaches this VCPU control.
The [calibration journal](../output/video-decode-20260922/results/bc250-vcn-rbc-vcpu-clock-mapped-20260929T164745Z-3362ea.jsonl)
has SHA256 `3da18d5d009d9b76ca49622de24ab873ecb0ec355abc929183f5a6e6bef4e954`.

The same mapped route sent `TRCE_EN` but the bit did not latch; a direct
host write also failed to latch it. Ring packets for reset at `0x1e0`
and firmware-cache registers at `0x59e`, `0x59f`, `0x1c2`, `0x1c3`
completed to their following scratch markers. Their payloads were BAR high
`0xf4`, BAR low `0x1fc00000`, firmware offset `0x20`, and size `0x64000`,
matching the guarded ordinary firmware BO and Linux's programming sequence.
At this stage, only the clock-control write had positive target readback:
host reads of reset and cache registers returned all ones. Packet
completion did not establish that those particular writes latched. The
later PSP readback above resolves this for cache size. `UVD_STATUS`
remained `4` and no VCPU instruction or decoded frame is proven. The
[trace](../output/video-decode-20260922/results/bc250-vcn-rbc-vcpu-trace-mapped-20260929T165144Z-798b4e.jsonl),
[reset](../output/video-decode-20260922/results/bc250-vcn-rbc-vcpu-reset-mapped-20260929T165530Z-16dd07.jsonl), and
[cache](../output/video-decode-20260922/results/bc250-vcn-rbc-cache-map-20260929T170109Z-75d7e1.jsonl)
journals have SHA256 `348ee060574e8f0fbf60add625612d09fd25e4e01229681ea034f4aefd762a97`,
`b0ed9dbfdfbb3a07f0e5591b9a5571ec3e9b59582aea44668c4651c2f81efbff`,
and `7885d70b471f458944a5557dc2567d994690eb46b9cfc4e2978a73e83ccaf62f`.
After cold-cycle recovery, the BC250 is on clean diagnostic boot
`dec024bb-d50a-44a8-8e74-faf22c2ea5f2`, `/boot` read-only, no pending
GRUB entry or Pi timer, Pico RAM profile active. No BIOS EEPROM or Pico
QSPI write occurred.

**Earlier 2026-09-29 wrong-address ring controls:**
Two guarded, reversible clock-control probes used the working decode ring
to write the known host-writable `UVD_VCPU_CNTL.CLK_EN` bit off and back.
The first used `PACKET0(0xc258,0)`, the second `PACKET0(0x0258,0)`.
Each submitted two aligned packet groups: the hardware `RPTR` advanced
`0→16→32`, and distinct following scratch writes both executed
(`0x11112222`, then `0x33334444`). But `UVD_VCPU_CNTL` stayed
`0x0ff20200` throughout, with no host restore needed; `UVD_STATUS` stayed
`4`. Earlier guarded host writes did toggle this exact `CLK_EN` bit, so
these two ring address forms do not provide a working VCPU-control route.
The [prefixed-address trial](../output/video-decode-20260922/results/bc250-vcn-rbc-vcpu-clock-20260929T162641Z-a6fae4.jsonl)
and [plain-address trial](../output/video-decode-20260922/results/bc250-vcn-rbc-vcpu-clock-internal-20260929T162930Z-325f5c.jsonl)
have SHA256 `c458260e47c2884108da7955606492c0edc7144b326c56b03b85fc19bca34a1a`
and `e8e7df00afa5b4977b997947923083f49090512b15ef720387e0716c5e0010c3`.
The later positive `0x1d8` calibration above resolves the address error.
After the second cold cycle, clean diagnostic boot was
`dec66d26-7753-4dff-a1d5-d2260969a66c`, with `/boot` read-only, no
pending GRUB entry or Pi timer, and the Pico SRAM profile active. No BIOS
EEPROM or Pico QSPI write occurred.

**Update 2026-09-29, VCN ring packet execution and VCPU trace attempt:**
The guarded [direct-packet probe](../tools/vcn-psp-diagnostics/prepare_vcn_rbc_direct_packet_trial.py)
placed `PACKET0(0xc01d,0), 0xdeadbeef` first in the decode ring, with NOP
padding to the 16-dword pointer alignment. With `RB_NO_FETCH=1`, `WPTR=16`
left `RPTR=0` and `SCRATCH9=0xcafedead`; after clearing only `RB_NO_FETCH`,
`RPTR=16` and `SCRATCH9=0xdeadbeef`. This **proves that the powered VCN
ring command processor fetched, decoded and executed a register-write
packet from GPU memory**. The VCPU did not report ready (`UVD_STATUS=4`),
so this is not proof of a VCPU firmware instruction or video decode. The
[raw kernel log](../output/video-decode-20260922/results/bc250-vcn-rbc-direct-packet-20260929T161426Z-ae625d.dmesg)
has SHA256 `0e248777c35e8fdf1ed09b2ae7d2ab4054c27f30a2bb4ad20e3c03a8fad1a8db`.
The runner's strict parser returned 1 because driver recovery invoked the
probe a second time; the second invocation's guard skipped all writes.
The first invocation completed, and the BC250 was PDU-recovered normally.

The follow-up [trace-control probe](../tools/vcn-psp-diagnostics/prepare_vcn_rbc_vcpu_trace_trial.py)
used the same ring path to submit `PACKET0(0xc258,0), 0x0ff20600`, adding
only `UVD_VCPU_CNTL.TRCE_EN` to the pinned control value, then wrote the
known scratch marker. The marker executed (`SCRATCH9=0xdeadbeef`), but
`UVD_VCPU_CNTL` read `0x0ff20200` before, during and after fetch;
`UVD_VCPU_TRCE=0` and `UVD_STATUS=4` also persisted. The trace bit did
not latch through this packet path. The clock-control calibration above
found that `0xc258` also fails to change `CLK_EN`, so this attempt does
not tell whether `TRCE_EN` could latch through another route.
The [structured trial](../output/video-decode-20260922/results/bc250-vcn-rbc-vcpu-trace-20260929T162151Z-9793ee.jsonl)
has SHA256 `fcce381021c2fef467792b36386db4e65e4b531d9b9bd4cb3bac17d5e6659b98`.
The BC250 returned to clean diagnostic boot
`dc4820d9-16eb-4897-b95f-68b29b28b84b`, `/boot` read-only, no pending
GRUB entry or Pi recovery timer; Pico remained SRAM-only. No BIOS EEPROM
or Pico QSPI was written. Next calibrate the ring packet route against a
VCN control with a known writable bit, then investigate VCPU startup.

**Update 2026-09-29, positive decode-ring memory-fetch evidence:** A guarded
[ring probe](../tools/vcn-psp-diagnostics/prepare_vcn_rbc_fetch_trial.py)
placed 16 dwords of valid NOP packets in the already allocated decode-ring
GPU BO at `0x264000`. Writing aligned `WPTR=16` with `RB_NO_FETCH=0` made
the hardware `RPTR` read 16; `UVD_STATUS` remained `4`. The
[control probe](../tools/vcn-psp-diagnostics/prepare_vcn_rbc_control_trial.py)
then used the kernel's own ring-test command packet, padded to 16 dwords.
With `RB_NO_FETCH=1` and `RB_NO_UPDATE=0`, `WPTR=16` left `RPTR=0` and
`SCRATCH9=0xcafedead`. Clearing only `RB_NO_FETCH` moved `RPTR` to 16;
`UVD_STATUS`, which was `4` before the control, read `0x00010005`: the VCN 2.0
register table identifies the newly set bits as `RBC_BUSY` and
`RBC_ACCESS_GPCOM`. The NOP-only ring had not set those bits. The
fetch-enable control and packet-dependent status give **positive evidence
that VCN's ring controller read command data from GPU memory**. The static
LMI status and latency registers in both trials are therefore insufficient
to rule out all VCN memory reads.

`SCRATCH9` stayed `0xcafedead`, VCPU PC and page-fault registers remained
zero, the firmware never reported ready, and the decode ring still timed
out. The GPCOM command appears to stall before the later scratch write;
this is not evidence that the VCPU fetched its firmware or decoded video.
The [NOP trial](../output/video-decode-20260922/results/bc250-vcn-rbc-fetch-20260929T155301Z-7209cb.jsonl)
and [command/control trial](../output/video-decode-20260922/results/bc250-vcn-rbc-control-20260929T160539Z-95ec84.jsonl)
have SHA256 `a8516ac18e1333ce1c4518fb6e65df9ba14bd7fb7b8909de7f56f2500baeaf43`
and `ffa106f7b3a268ec96a1638a0a4e035d429bf8334a8e68887c7b96e603ca1f82`.
After the first trial, the first PDU cycle did not restore SSH; a second
authorized cycle did. After the control trial, the BC250 returned normally
to clean diagnostic boot `aa8c0e5c-428b-4be8-bfa9-110e45483b49`, with
the Pi recovery timer stopped, `/boot` read-only, and no pending GRUB entry.
The Pico remained on its pinned SRAM profile. Neither BIOS EEPROM nor Pico
QSPI was written. The next problem is the **VCPU firmware-start path**,
not proving that the decode ring can request memory.

**Update 2026-09-29, VCN-local cumulative-counter trial:** A guarded
[kernel probe](../tools/vcn-psp-diagnostics/prepare_vcn_lmi_perfmon_probe.py)
armed `UVD_LMI_PERFMON_CTRL` with selector 0 and `PERFMON_STATE_START=1`
before VCPU reset release, then froze it after the 4,096-sample LMI-status
window. Both count words remained zero. It then reset, started and froze
each selector 1–31 for about 2 ms; all 31 count pairs were zero, while every
selector and state write read back exactly. `UVD_LMI_MC_CREDITS` remained
`0x10101010`, `UVD_LMI_SPH` remained zero, the LMI-status value stayed
`0x007c337f`, and the enabled latency counter remained `0x0000ff00`. The
PSP load again returned `ret=0/status=0`, but the VCPU stayed unready with
`UVD_STATUS=4` and the decode ring timed out. The
[trial journal](../output/video-decode-20260922/results/bc250-vcn-lmi-perfmon-20260929T152805Z-68a7b7.jsonl)
has SHA256 `bb2491b68fc071082e7f42aacdd6ce2851f8b05f6e57a4f4c04a5df8430d5100`.
This gives no positive evidence of VCN memory traffic, but the available
VCN 2.0 headers do not define the selector events or provide a known-good
counter baseline. Even all-zero counts cannot prove that no request was
attempted. The next useful experiment needs an independently calibrated
VCN memory-request event or an upstream execution/clock/isolation signal.
The BC250 returned to clean diagnostic boot
`b62834b4-a5e8-495a-b205-44f45cf78800`; the PDU timer was stopped and
the pinned Pico SRAM profile remained armed. No BIOS EEPROM or Pico QSPI
write occurred. No frame decoded.

**Update 2026-09-29, early `0x1f8a4=0xf` and VCN memory-request check:**
The [RAM-only profile generator](../tools/pico2-interposer/prepare_vcn_policy_1f8a4_trial.py)
added the previously verified first-read `0xf` substitution to a signed
ordinary-BO VCN profile. The Pico verified 1,860/1,860 substitutions on the
diagnostic boot with zero mismatches or timing faults. The powered VCN startup
used native VCLK code 16, opened the VCN power aperture, and received PSP
firmware-load `ret=0/status=0`, but VCPU PC and page-fault status stayed zero,
`UVD_STATUS` stayed `4`, and the decode ring timed out. Eight key register
trace checkpoints match the earlier `0xb` ordinary-BO run exactly, including
powered version/harvest, post-power reload, VCPU release, first wait and last
wait. Thus `0xf` demonstrably changed the early firmware read in the prior
ABL0 control, but has **no observed VCN-start effect** under this tested late
profile. The [trial journal](../output/pico2/vcn-bo-fetch-early-1f8a4-f-20260929/vcn-trial.jsonl)
has SHA256 `f3c77574dd31e3659b046929203c110703923de477b15083ba9114a18db7abb6`.

The new [VCN-local probe](../tools/vcn-psp-diagnostics/prepare_vcn_memory_request_probe.py)
retained the enabled LMI latency monitor and sampled `UVD_LMI_STATUS` 4,096
times during roughly 29 ms immediately after VCPU release. Every sample was
`0x007c337f` (AND=OR=same, transitions=0), with the read-clean bits set.
Latency remained `0x0000ff00` and VCPU PC/page-fault status stayed zero. This
finds **no in-flight LMI request in that window and no completed transaction
observed by the latency monitor**; it cannot exclude a brief request before
the first sample, a different memory path, or an uncalibrated counter. The
[memory-request journal](../output/pico2/vcn-bo-fetch-early-1f8a4-f-20260929/vcn-memory-requests.jsonl)
has SHA256 `6ba6f9fa6f91b676d6e929eb618454c30ac5edfa01ac60946ba7f14d6ad46800`.
The root-PCI SMN alternative stalled the board even on an idle diagnostic
boot; it was PDU-recovered and is marked unsafe in its script. The machine
returned directly to clean diagnostic boot
`70823f2c-811e-4f94-8e4b-323e35c5c545`, with `/boot` read-only and no
recovery timer or pending GRUB entry. The pinned `vcn-psp-bo-fetch` profile
was restored in Pico SRAM. Neither BIOS EEPROM nor Pico QSPI was written.
No frame decoded.

**Update 2026-09-29, Deck-specific early gasket rows did not start VCPU:**
The [pinned hybrid-table generator](../tools/pico2-interposer/prepare_deck_gasket_hybrid.py)
kept the four Cezanne client-12 windows whose removal had individually made
the BC250 VCN aperture read all ones. It replaced seven first-window values
with the authenticated Deck values and added the Deck's two absent rows,
giving 53 early TOS-entry writes. The late signed PSP driver retained the
previously tested 51-row Cezanne replay plus PSP-side cache/reset release;
this is an **early Deck delta**, not a full Deck-policy transplant. The ARM
compiler reproduced the prior 51-row TOS hook byte for byte; the new hook
changed only its loop count and table. Both new signed image views verified,
and the Pico UF2 contained RAM blocks only. The native Unicorn execution
check could not run in this workstation environment because `unicorn` is
absent; exact hook-code comparison, row parsing, signature verification,
Pico readback and the actual diagnostic boot were used instead.

The BC250 reached diagnostic boot `09fd9028-1c95-43ff-a60b-4f2f1f7dcfd1`.
Pico verified **1,870/1,870** substitutions over two passes with no fault,
mismatch, late decision or RX stall. The guarded VCN runner applied native
VCLK code 16 and all three slot enables; `UVD_POWER_STATUS=0x800` and
`UVD_PGFSM_STATUS=0` were responsive. The post-release
PSP firmware load returned `ret=0/status=0`, but `UVD_STATUS` stayed at the
driver's BUSY value `4`, VCPU PC and page-fault status read zero, and the
decode ring timed out with `-110`. The [Pico boot trace](../output/pico2/deck-hybrid-gasket-20260929/boot.log),
[runner journal](../output/pico2/deck-hybrid-gasket-20260929/vcn-runner.jsonl)
and [kernel log](../output/pico2/deck-hybrid-gasket-20260929/dmesg.log)
have SHA256 `1d7c5efc51f0fb1563e0fe73d28f6093e8e462c11da370a0ce4e6c77e3b54c43`,
`3a18db82e50b3bffc4ed6acd4545cf08c2bb45b3ee93a8dd870484e13893dc9b`
and `e6beee584a00c3c511bd00267a2b56bb26b3e72e00802383df21a3323e34d765`.
This excludes the tested early Deck-specific rows, with the established late
policy and module, as a sufficient VCN-start fix. It does not establish that
the untested full Deck late policy would behave the same. The SMU state was
cold-reset directly into clean diagnostic boot
`7ec6d4e6-444a-48a9-b6e4-4744421d11a8`; the pinned Pico
`vcn-psp-bo-fetch` RAM profile is armed, `/boot` is read-only, no one-shot
entry or Pi recovery timer remains, and neither BIOS EEPROM nor Pico QSPI
was written. No frame decoded.

**Update 2026-09-29, authenticated Deck policy comparison and live BC250
control:** The new [offline audit](../tools/pico2-interposer/audit_deck_video_policy.py)
pins the local BC250 ROM and Steam Deck firmware, verifies both early
`SEC_GASKET` signatures and the Deck TOS-policy signature under their
respective usage-31 public keys, and rejects a changed-record signature
control. Its private [report](../output/video-decode-20260922/results/steamdeck-bc250-video-policy-20260929.json)
finds no client-12 `0x0900cxxx` rows in BC250's early policy, 27 in the
Deck's, and 51 in the previously tested Cezanne policy. Eighteen of the
Deck's 27 rows match Cezanne exactly; nine differ. The early `0x1f8a4`
setting is `0xb` on BC250 and `0xf` on Deck. These are signed-policy
differences, not identified VCN start controls.

The [one-read profile generator](../tools/pico2-interposer/prepare_policy_one_shot.py)
now supports a pinned `--set-1f8a4-f` trial. Two Pico **SRAM-only** images
substituted only the first physical read of that BC250 tuple, leaving its
second read, ROM bytes, signing key and signature unchanged. The first
image's ABL0 hook read back `0xf` on both firmware passes
(`diag0=diag1=0x03c4003c`), with 1,396/1,396 substitutions verified, zero
faults or mismatches, and Fedora boot `79d6a7da-70c5-43e8-9110-69663ad8cd3b`.
The paired image read `CC_UVD_HARVESTING=3` on both passes
(`diag0=diag1=0x03c4000c`) with the same substitution count and zero faults;
Fedora boot `eb859bdb-8575-43ba-911e-0f7ec1fdaacd`. The private Pico
[policy trace](../output/pico2/early-policy-live/policy-first-read-1f8a4-f-policy-20260929.log)
and [harvest trace](../output/pico2/early-policy-live/policy-first-read-1f8a4-f-harvest-20260929.log)
have SHA256 `0e160a6c35b91d7a9c9a4ab85d00dea4bf5c125e0b878ea76f74a2ab17392390`
and `a6da1a8e6b841ffeb66fe4f7b35c873aab06f13eeb7334e32c8aa9f02db9b7c7`.
The two UF2 files were checked to contain only `0x20000000..0x2000c2ff`
RAM blocks. This excludes the Deck's single `0x1f8a4` bit difference as a
way to clear the **early** BC250 harvest indication; it does not test the
Deck's 27 client-12 windows or prove the later VCPU would remain idle under
every policy combination. The prior 51-row Cezanne replay had opened the
VCN aperture without starting VCPU, so no further blind policy replay is
justified yet. After the tests, the pinned `vcn-psp-bo-fetch` profile was
reloaded into Pico SRAM and the machine returned directly to clean diagnostic
boot `60d876f3-8bd5-441a-afec-89ba6a7c1728`, with `/boot` read-only, no
pending GRUB entry or Pi recovery timer. Neither BIOS EEPROM nor Pico QSPI
flash was written; no frame decoded.

**Update 2026-09-29, faster diagnostic iteration:** The new
[`iterate_diagnostic.py`](../tools/vcn-psp-diagnostics/iterate_diagnostic.py)
keeps the BC250 in its isolated diagnostic boot between guarded VCN trials.
Each trial still cold-cycles outlet 8 to reset the native SMU clock-table
change, but the one-shot GRUB entry returns directly to diagnostics; the
normal Fedora and CS-PASS restoration happen once at the end of a batch.
The wrapper pins the Pi RAM-only Pico images, checks the current boot and
module before a trial, arms a Pi PDU recovery timer, archives evidence, and
removes the consumed diagnostic entry after the next boot. The initial live
`enter` succeeded: current diagnostic boot
`36efe766-cc86-4b4a-8ca5-33480ba72911` passed the read-only native-clock
and module preflight. One previously pinned clock-gate probe then exercised
the new cycle end to end: the trial returned zero, cold-cycled directly to
diagnostic boot `3b8d6f2f-58f1-4b25-9076-abfbc09f5b5e`, and stopped its Pi
timer. That boot has `amdgpu` unbound, `/boot` read-only, and no pending GRUB
entry; Pico profile `vcn-psp-bo-fetch` remains armed with 3,716/3,716 verified
substitutions and zero faults. The repeated probe again showed PSP reload
`ret=0/status=0`, unchanged VCPU clock-status readback and no VCPU-ready or
decoded frame. This repetition validates the iteration path, not a new VCN
finding. The archived [trial report](../output/video-decode-20260922/results/bc250-vcn-clock-gate-probe-20260929T135931Z-6af419.json)
points to the full journal and `dmesg`. Neither BIOS EEPROM nor Pico QSPI
flash was written.

**Update 2026-09-29, VCPU clock-gate calibration:** A first guarded probe
stopped before any clock-control write because its overly strict baseline
expected `UVD_CGC_CTRL=0x0000018c`. The revised module logged the live word
as `0x8000018c`; bit 31 is the named `MMSCH_MODE` field, which the Linux VCN
2.0 `disable_clock_gating()` path leaves unchanged. After the signed PSP
hook had already requested `UVD_SOFT_RESET=0`, but before Linux's own
reset-release writes, the revised probe briefly cleared
`UVD_VCPU_CNTL.CLK_EN` and restored it
(`0x0ff20200 → 0x0ff20000 → 0x0ff20200`), then set and restored only
`UVD_CGC_GATE.VCPU` (`0x00100000 → 0x00140000 → 0x00100000`). Both controls
read back each change. `UVD_CGC_STATUS` stayed `0xbfffffff` at every point,
including after Linux's reset-release writes and a full VCPU wait. Its VCPU
SCLK/VCLK bits did **not** respond to either controlled perturbation. This
denies us a positive calibration for interpreting that status word; it does
**not** prove whether the physical VCPU clock oscillates. The signed PSP firmware request
again returned `ret=0/status=0`, the ordinary BO and payload guards passed,
but `UVD_STATUS` stayed at the driver's BUSY value `4` through ten waits and
no frame decoded. `CC_UVD_HARVESTING=3` remains an early availability
indication, not a demonstrated writable start control.

The [probe generator](../tools/vcn-psp-diagnostics/prepare_vcn_clock_gate_probe.py),
[pinned builder](../tools/vcn-psp-diagnostics/build_vcn_clock_gate_probe.sh)
and [guarded runner](../tools/vcn-psp-diagnostics/run_late_vcn_native_clock_trial.py)
record the measurement. Revised module SHA256
`608377257401f9dd599101ba71ae5a9a46a2c196237adaca62706d3798ae0de6`.
The [journal](../output/video-decode-20260922/results/bc250-vcn-clock-gate-probe-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-clock-gate-probe-20260929.dmesg)
have SHA256 `6bc97e507eafcc105bd10bc90ff2380a4bc28f2e09e7888def88d68715147f75`
and `cd52fd8aa4700855d2a2ff40bb675296a384c2b405ccf10c50de33ff6a253250`.
The Pico verified 3,716/3,716 substitutions across the two trial boots,
with zero fault, mismatch, late decision or RX stall. Normal Fedora boot
`2ba47304-cb6d-40f8-81af-c74d31aefd51` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, CS-PASS v2 armed in Pico SRAM and no
Pi recovery timer. No BIOS EEPROM or Pico QSPI flash was written.

**Source and memory-placement cross-check:** The ordinary-BO PSP profile
was generated from the already signed PSP reset-release profile (base ROM
SHA256 `e8cfd3d91eeab51d7cf0bec1e5d213a59a4160d369c2f58a3433bd09336da581`).
Its generator changes only the 17 cache-map values, body hash and randomized
RSA-PSS signature, so the earlier ordinary-BO trials already combined the
BO map and signed reset-release logic. A newly generated semantic equivalent
passed 26 native ARM post-cache cases offline; it was **not** deployed.
The diagnostic boot reported VRAM `0xf400000000..0xf41fffffff`; its pinned
VCN BO `0xf41fc00000` lies inside that interval. These checks remove a
redundant BO-plus-reset boot and a GTT-placement hypothesis, but cannot
prove a VCPU fetch from that BO.

**Update 2026-09-29, VCPU arbiter is not disabled:** A second guarded,
read-only ordinary-BO trial sampled `UVD_RB_ARB_CTRL` before VCPU reset
release, immediately afterward, and after the first full wait. It read
`0x00000000` all three times: the documented `VCPU_DROP` (bit 2) and
`VCPU_DIS` (bit 3) were clear. The adjacent `UVD_MPC_CNTL=0x10` and
`UVD_LMI_VM_CTRL=0` were stable. `UVD_CGC_STATUS=0xbfffffff` has no
validated clock-state polarity on this board and must not be interpreted
as proof that VCPU clocks run or stop. The signed PSP request again returned
`ret=0/status=0`, the pinned BO/payload guard passed, and `UVD_STATUS`
stayed `4`; no frame decoded. This excludes the VCPU arbiter's named
disable/drop bits as the simple cause, while leaving the early harvest
source and VCPU fetch/clock route unresolved.

The [arbiter kernel generator](../tools/vcn-psp-diagnostics/prepare_vcn_arbiter_probe.py),
[pinned builder](../tools/vcn-psp-diagnostics/build_vcn_arbiter_probe.sh),
and [guarded runner](../tools/vcn-psp-diagnostics/run_late_vcn_native_clock_trial.py)
record the trial. Module SHA256
`dfba2a1b327c57f19d5347444c361bf3a6c9893e5f26a7ca6b9ce778de5f3614`.
The Pico verified 1,858/1,858 RAM-only substitutions across two firmware
passes, with zero fault, mismatch, late decision or RX stall. The archived
[journal](../output/video-decode-20260922/results/bc250-vcn-arbiter-probe-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-arbiter-probe-20260929.dmesg)
have SHA256 `e34f3602aaf5e0f28c571c7cc8cd5a0cdc5cf7e6cd9283afa35c9459f7f9c60c`
and `a8d89eb3f6d3ace78f50031cce89bf23edf79f40b4346b03522cc1fc130a35e2`.
Normal Fedora boot `bf616234-f163-4541-ab4e-b2ad2afc3dd7` has
`amdgpu` bound, `/boot` read-only, no diagnostic entry, Pico CS-PASS v2
armed in SRAM and no Pi recovery timer. No BIOS EEPROM or Pico QSPI write.

**Update 2026-09-29, powered VCN LMI latency counters:** A guarded
ordinary-BO trial armed the VCN 2.0 `UVD_LMI_LAT_CTRL` MAX/MIN/AVG START
fields (`0x00000000 -> 0x00000700`) after the signed PSP VCN request
returned `ret=0/status=0` and before VCPU reset release. Readback retained
`0x700` through the first full VCPU wait. During that interval,
`UVD_LMI_LAT_CNTR` stayed `0x0000ff00` (maximum zero, minimum `0xff`),
`UVD_LMI_AVG_LAT_CNTR` stayed zero, and `UVD_MPC_PERF0/1` stayed zero.
`UVD_STATUS` stayed at Linux's BUSY value `4`, so no ready VCPU or decoded
frame was observed. `UVD_LMI_PERFMON_CTRL` was zero throughout; its separate
count registers were **not enabled** and their zero values must not be used
as evidence of no traffic. The armed latency counters did not observe a
completed transaction, but without an independently demonstrated positive
transaction the unchanged readings cannot prove that the VCPU made no fetch
attempt. This strengthens the case for tracing the VCPU's clock/reset/fetch
route, not treating `CC_UVD_HARVESTING=3` as a writable start command.

The [kernel generator](../tools/vcn-psp-diagnostics/prepare_vcn_lmi_latency_probe.py),
[pinned builder](../tools/vcn-psp-diagnostics/build_vcn_lmi_latency_probe.sh)
and [guarded runner](../tools/vcn-psp-diagnostics/run_late_vcn_native_clock_trial.py)
reproduce the volatile measurement. Module SHA256
`2102f14853045acc9a1ea80aebfd86a85264903ab3f3f01745bf2de6f34e72c3`;
Pico reused the already verified RAM-only `vcn-psp-bo-fetch` UF2 SHA256
`0922b436f613cfa9af982a505b752232527fb8ba18164cfe1f6779693c3915bb`.
It verified 1,858/1,858 substitutions across two firmware passes with zero
fault, routing mismatch, late decision, or RX stall. The archived
[journal](../output/video-decode-20260922/results/bc250-vcn-lmi-latency-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-lmi-latency-20260929.dmesg)
have SHA256 `159f0c3582baf0b2bb7754f698d491fa35a4d5a2a57aa862d06f7590927f2de7`
and `e0eb22debeb1a6f589f1932cf9b22e310c06c80b716ca6c1463e64a98f46bdf3`.
The diagnostic boot was cleaned and cold-cycled; normal Fedora boot
`7a846d8c-9d95-4373-809a-022d9829f0dc` has `amdgpu` bound, `/boot`
read-only, no one-time diagnostic entry, CS-PASS v2 armed in Pico SRAM and
no Pi recovery timer. No BIOS EEPROM or Pico QSPI flash was written.

**Update 2026-09-29, ordinary-BO map retained but VCPU still idle:** The
follow-up kept the guarded ordinary firmware BO at `0xf41fc00000` and added
one marked PSP request after the first full VCPU wait. Its signed hook read
all sixteen firmware, stack, context and shared-memory cache-window words
through the powered PSP service **before** any second-call map replay. It
returned `0x70000010`: all sixteen matched the new BO values at full 32-bit
width. The seventeenth `GFX10_ADDR_CONFIG` word was excluded because its
`0x40` bit is masked on readback. The first powered firmware request had
returned `ret=0/status=0`, the BO address and payload-prefix guards passed,
and VCN power/PGFSM/version were `0x800/0/0x2001b`. Yet `UVD_STATUS`
remained `4`, VCPU PC and page-fault status remained zero, and no frame
decoded. This rules out loss of the sixteen PSP-visible BO mappings over
that wait; it **does not prove** that the VCPU made a memory transaction or
fetched the BO payload. The remaining investigation should isolate that
fetch/enable condition and the source of `CC_UVD_HARVESTING=3`, rather than
try to force that indication as a start switch.

The [PSP profile generator](../tools/pico2-interposer/prepare_delayed_vcn_cache_premap_trial.py),
[delayed kernel generator](../tools/vcn-psp-diagnostics/prepare_vcn_psp_bo_premap.py),
and [runner](../tools/vcn-psp-diagnostics/run_late_vcn_native_clock_trial.py)
pin the measurement. Twenty-three native PSP instruction cases passed. The
signed RAM-only ROM SHA256 is
`cc49c19df92c394c4a8af791839f4eee7d695cd14b75918b30dae9159d225eec`;
its no-flash Pico UF2 SHA256 is
`b9a9768bbaacc4f7957f964cec52ed3640c31ce6af12ec2c99e98dff393502a2`.
Pico verified 1,982/1,982 substitutions across two BIOS passes, with zero
fault, mismatch, late decision, or RX stall. The archived
[journal](../output/video-decode-20260922/results/bc250-vcn-psp-bo-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-psp-bo-premap-20260929.dmesg)
have SHA256 `0671799a23255a9f030b4a122a24f77f63620fc047e6d6362647a4ff952196f0`
and `e3334945a4d0161534ed65906d6b2782b05f7c0480a06ef34d7622967949460b`.
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`92865f1e-597d-44fa-b1e2-ebbea6d6c786` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and the
Pi timer inactive.

**Update 2026-09-29, guarded ordinary-BO VCN trial:** A matched RAM-only
Pico profile redirected the signed PSP driver's 17 powered VCN cache-window
writes to the same ordinary GPU buffer that an opt-in kernel module had
allocated and filled with the authenticated Navi10 VCN payload. The module
verified the exact buffer and shared-memory addresses, firmware size, and
first 16 payload bytes before its powered PSP reload. The signed request
returned `ret=0/status=0`; VCN power/PGFSM/version were `0x800/0/0x2001b`.
The VCPU program counter and page-fault status remained zero, `UVD_STATUS`
remained the driver's busy value `4` through ten waits, and the decoder ring
timed out. Linux's reads of cache and soft-reset registers still returned
`0xffffffff`, so this run **did not verify** that all new PSP-visible map
values persisted or that VCN fetched the ordinary-memory payload. The PSP
firmware destination still reported TMR address `0xf41fa00000`; the ordinary
BO address was `0xf41fc00000`. `CC_UVD_HARVESTING` remained `3`, an observed
availability indication rather than a proven writable start control.

The [BO map generator](../tools/pico2-interposer/prepare_vcn_psp_bo_fetch_trial.py),
[kernel source generator](../tools/vcn-psp-diagnostics/prepare_vcn_psp_bo_fetch.py),
and [runner](../tools/vcn-psp-diagnostics/run_late_vcn_native_clock_trial.py)
pin the addresses and guards. The signed RAM-only ROM SHA256 is
`c1064547359793e27904a7c97800fe5f2636007cc9ed419193eeef913e7fa51a`;
its no-flash Pico UF2 SHA256 is
`0922b436f613cfa9af982a505b752232527fb8ba18164cfe1f6779693c3915bb`.
Pico verified 1,858/1,858 substitutions across two BIOS passes with zero
fault, mismatch, late decision, or RX stall. The archived
[journal](../output/video-decode-20260922/results/bc250-vcn-psp-bo-fetch-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-psp-bo-fetch-20260929.dmesg)
have SHA256 `ccaefee5ebe1cf141dc97500acdc7d5ac64216bfe44fe5e8b38dbf37aed20587`
and `56446df61c696d27da29ba0a9f211fa9ce2b4ae05cb254662c8cdef4871531a6`.
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`d58beb90-cb96-41cf-a83b-a643495fcd01` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and the
Pi timer inactive. The immediate next measurement checks all sixteen
PSP-visible cache-window values after the first VCPU wait and before replay.

**Update 2026-09-29, signed read-attribute control also fails:** The prior
PSP mapping control used helper attribute `0xfffffffe`, whereas the signed
driver's own ordinary read path at `0xe0e734` supplies `0xffffffff`. A new
RAM-only hook changed just that attribute and asked the same signed helper
to map the PSP bookkeeping address `0xf400162ec0` after the first VCPU
wait. It still returned a nonzero result whose preserved low 28 bits were
`0x0000000f`; no mapped pointer or payload bytes were observed. The first
powered VCN `LOAD_IP_FW` returned `ret=0/status=0`, while `UVD_STATUS`
remained the driver's busy value `4`. This removes the differing attribute
as the simple explanation for the equal failures, but does not determine
the helper's mapping context or the VCN firmware TMR contents. The matching
firmware-address image was built and checked offline, then deliberately not
run because a failing control would not make its result diagnostic.

The [mapping hook](../tools/pico2-interposer/driver-delayed-vcn-tmr-premap.S)
now has an explicit attribute override, and the [native check](../tools/pico2-interposer/test_delayed_vcn_tmr_premap_trial.py)
verifies the exact argument word. Ten instruction cases passed for each
new image and both archived images. The Pico substituted and verified
2,090/2,090 control words across two BIOS passes with zero fault,
mismatch, late decision or RX stall. The signed control ROM SHA256 is
`07743ae65659b1dcc24c2dbd765379626f33d81c962a10ce75c367f69726a45b`;
its no-flash Pico UF2 SHA256 is
`12556daf8f0912617274fbddf2b81f731ceda0a1272c3ea9f5c5978739067b29`.
The archived [journal](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-readattr-control-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-readattr-control-20260929.dmesg)
have SHA256 `2f2ab5912cdea526cc1530f7ac199c636f6540d45dcb2d8b0653a1fe3cd61010`
and `ae7b4513e957586758d727cf7ce8326fdaa00d219c84853c177ef1e1badbe2e8`.
Neither BIOS EEPROM nor Pico QSPI was written. The BC250 returned to
normal Fedora boot `5a579a67-f939-4bc4-ae7d-5fdf0a75709b` with
`amdgpu` bound, `/boot` read-only, no diagnostic GRUB entry, Pico CS-PASS
v2 armed in SRAM, and the Pi recovery timer inactive. No frame decoded.

**Update 2026-09-29, direct PSP TMR read remains inconclusive:** A signed
RAM-only hook called the driver's own mapping helper after the first VCPU
wait, asking to read the first page at the PSP-reported VCN firmware TMR
address `0xf41fa00000`. The intended comparison was the first four words
of the installed VCN payload (`POWERED BY AMD` followed by CR/LF). The
helper declined the mapping before any payload word was read. A corrected
diagnostic preserved its return value's low 28 bits as `0x0000000f`;
its high four bits were not transmitted. A third, otherwise identical
positive control asked the same helper to map `0xf400162ec0`, the PSP
bookkeeping address that the signed driver maps in another call path. It
also returned low 28 bits `0x0000000f` at this delayed call site. The
equal failure means this helper invocation does **not** distinguish
protected VCN TMR contents from a mapping-context, permission, argument,
or timing issue. It cannot establish that the VCN firmware bytes are
missing, nor that the VCPU can fetch them. The initial powered PSP
`LOAD_IP_FW` still returned `ret=0/status=0`, and `UVD_STATUS` stayed `4`.

The [read hook](../tools/pico2-interposer/driver-delayed-vcn-tmr-premap.S),
[linker script](../tools/pico2-interposer/driver-delayed-vcn-tmr-premap.ld),
[generator](../tools/pico2-interposer/prepare_delayed_vcn_cache_premap_trial.py),
and [native check](../tools/pico2-interposer/test_delayed_vcn_tmr_premap_trial.py)
record the guarded call and cleanup. Native Unicorn executed ten cases
for each target, including four mismatch indices, an upper-bit-only
mismatch, mapping rejection, and the unmarked path. The final no-flash
Pico images verified 2,086/2,086 substitutions on the firmware-address
trial and 2,090/2,090 on the bookkeeping control, each over two BIOS
passes with zero fault, mismatch, late decision, or RX stall. The Linux
runner's inherited `cache-size0` event label refers to the PSP status
carrier, not the TMR mapping result's origin. The corrected firmware
[journal](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-error-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-error-premap-20260929.dmesg)
have SHA256 `b0ff5bc917107480f5b22895744500fbedb2f9481dd5157b91b106f93fc1fcea`
and `ce522c1e82c348cc73e7480f935eaa22013ac139df973eb669c057c656eb40ae`;
the control [journal](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-map-control-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-map-control-20260929.dmesg)
have SHA256 `556015a15a248d6bd2b7a420ad21f8e87e28a22e6a98b8f036a350fad75055e6`
and `40e92e75a94ad68a31679ae708a23445c6c0a72d8164f626b671cbf4c00121b4`.
The first firmware-address attempt, whose diagnostic preserved only 24
result bits, is archived as
[`bc250-vcn-delayed-tmr-prefix-premap-20260929.*`](../output/video-decode-20260922/results/bc250-vcn-delayed-tmr-prefix-premap-20260929.jsonl).
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`e8d08497-33f8-4f87-befb-d26a04cd0d98` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and
the Pi recovery timer inactive. Do not infer a missing VCN firmware copy
from these map failures; pursue the VCPU memory path or a source-backed
upstream enable/isolation control by a different method.

**Update 2026-09-29, VCPU fetch muxes retained:** Linux's static VCN 2.0
startup writes `UVD_MPC_SET_MUXA0=0x040c2040`,
`UVD_MPC_SET_MUXB0=0x040c2040`, and `UVD_MPC_SET_MUX=0x88` before
releasing VCPU reset. A signed RAM-only PSP hook compared all three at full
32-bit width after the first VCPU wait, before any second-call cache-map
replay. It returned `0x72000003`: **all three PSP-visible words matched**.
The first powered PSP firmware load returned `ret=0/status=0`, but
`UVD_STATUS` stayed at the driver's busy value `4`; VCPU-ready and a decoded
frame remain absent. This rules out loss of these three programmed mux
values over that interval, not a VCPU memory transaction, successful
firmware fetch, or an upstream enable/isolation issue. The reused kernel
runner labels its event `cache-size0`; in this boot the signed hook compared
the three MPC muxes. Ten native instruction cases passed, including each
first-mismatch position, an upper-bit-only mismatch, PSP read errors and
the unmarked path. Pico verified 2,010/2,010 substitutions over two BIOS
passes without fault, mismatch, late decision or RX stall.

The [hook](../tools/pico2-interposer/driver-delayed-vcn-mux-premap.S),
[generator](../tools/pico2-interposer/prepare_delayed_vcn_cache_premap_trial.py),
and [native check](../tools/pico2-interposer/test_delayed_vcn_mux_premap_trial.py)
preserve the comparison. The ignored
[journal](../output/video-decode-20260922/results/bc250-vcn-delayed-mpc-mux-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-mpc-mux-premap-20260929.dmesg)
have SHA256 `b31db302b86ecbc39b5faebb42962aa2e14382851308133f11f37021ba0771f6`
and `8e2f6858b5063d34b018ebe4a2473e27a02827df0df9c007980e642221d4d87d`.
The signed RAM-only ROM SHA256 is
`285fce3e27b9f563723adcdf3a30185de5a645e5e9ff3828e9d29ee55a44720a`;
the Pico no-flash UF2 SHA256 is
`270712866eaef223123b2af65fdd8c1f873bdc4faade4505b6cfb19653bc9dd3`.
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`ae0f6a38-2e7c-4be3-af63-b9cb9d45dac1` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and
the Pi recovery timer inactive. Next isolate whether the VCPU can read its
firmware address through the configured memory path, or whether a distinct
upstream enable blocks execution. `CC_UVD_HARVESTING=3` remains an
availability indication; its origin and writability are not established.

**Update 2026-09-29, MPC replacement-mode control:** The Linux VCN 2.0
startup reads `UVD_MPC_CNTL`, changes its replacement-mode field to 2,
and writes the complete word back. A poisoned all-ones host read could
therefore have damaged this memory-fetch control. A signed RAM-only PSP
hook sampled `UVD_MPC_CNTL` at `0x200dc` after the first VCPU wait,
before any second-call cache-window replay. It returned low 28 bits
`0x00000010`, exactly the replacement-mode-2 setting; the hypothetical
all-ones propagation would have yielded low bits `0x0fffffd7`. Thus that
specific host read-modify-write failure was **not** observed. The
diagnostic encoding discards the top four bits and does not establish
that the MPC muxes, memory transactions, or VCPU execution work.
`UVD_STATUS` stayed `4`, with no decoded frame. The inherited Linux runner
labels the event `cache-size0`; the signed PSP hook actually sampled
`UVD_MPC_CNTL`. Twelve native instruction cases passed; Pico verified
1,934/1,934 substitutions over two BIOS passes without fault, mismatch,
late decision or RX stall.

The ignored [journal](../output/video-decode-20260922/results/bc250-vcn-delayed-mpc-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-mpc-premap-20260929.dmesg)
have SHA256 `7af4e1de02a00af3d293e74e02953c4b83042953139fdeac69d5ce3a8d494175`
and `36a0ddeae19f73704f83e89c62e68ccb68ca438cb0eafd106369be02c9ca6950`.
The signed RAM-only ROM SHA256 is
`9fe48b51ae7a16888f8a906266fcaf51a367ef63d9e00079339ce1ce691a42ab`;
the Pico no-flash UF2 SHA256 is
`a43f302da93e9e602cac7fd2ad39b350aceb3cc3470471ed670cf5abe1804f8d`.
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`a1f29978-e69a-4df7-8155-03e35733675d` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and
the Pi recovery timer inactive.

**Update 2026-09-29, VCN2 firmware selection control:** The opt-in BC250
module currently requests `navi10_vcn.bin` for its reported VCN 2.0.3 IP.
On the running BC250 Fedora image, `navi12_vcn.bin.xz` and
`navi14_vcn.bin.xz` are symlinks to `navi10_vcn.bin.xz`; `renoir_vcn.bin.xz`
is a symlink to `green_sardine_vcn.bin.xz`. After decompression, Navi10's
SHA256 is `a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5`
and Green Sardine's is
`ff1cbd575ae59ee317c6027ba57be7fc8861ac51fd6da44411ec8a1bbdfc7f26`.
Both are 405,952 bytes. A byte-for-byte comparison found **exactly one
difference, at header offset 14**: the IP minor version is `0` versus `2`.
Their microcode payloads, including the signature area, are byte-identical;
both headers report the same ucode version, payload size and CRC. Thus
switching among these packaged VCN2 names cannot provide a different
decoder program. This does not prove the common payload matches BC250's
2.0.3 implementation or that it reached the VCPU. It avoids a redundant
live firmware-selection trial and directs work to fetch and enable state.

**Update 2026-09-29, all VCPU cache windows persist:** A signed RAM-only
PSP hook compared the full 32-bit values of all sixteen firmware, stack,
context and shared-memory cache-window registers with the values from the
first successful powered PSP VCN load. It ran after the first full Linux
VCPU wait and **before** the second call replayed any window write. The
diagnostic returned `0x70000010`, meaning all sixteen matched; the
seventeenth `GFX10_ADDR_CONFIG` word was excluded because bit `0x40` is
masked on readback. The first load returned `ret=0/status=0`, while
`UVD_STATUS` stayed `4` and VCPU-ready never appeared. This rules out loss
of those sixteen PSP-visible mappings over that interval as the immediate
cause. It does not show that the VCPU fetched or executed the firmware, or
identify an upstream enable or isolation gate. The reused Linux runner
labels the diagnostic `cache-size0`; its **PSP hook compared all sixteen
window words** in this run. The 23-case native instruction check covered
every mismatch index, an upper-bit-only mismatch, PSP read errors and the
unmarked startup path. Pico verified 1,978/1,978 substitutions over two
BIOS passes, with zero fault, mismatch, late decision or RX stall.

The [hook](../tools/pico2-interposer/driver-delayed-vcn-map-premap.S),
[generator](../tools/pico2-interposer/prepare_delayed_vcn_cache_premap_trial.py)
and [native check](../tools/pico2-interposer/test_delayed_vcn_map_premap_trial.py)
preserve the exact comparison and unmarked path. The ignored
[journal](../output/video-decode-20260922/results/bc250-vcn-delayed-map-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-map-premap-20260929.dmesg)
have SHA256 `c275d03801f81ca21bf68364ca5fa6e830b1702866c352186c303823b93bb526`
and `afa55d42031262ca32bc2294c4bd1ca367fd2bd10a3d2dade735f7113736f2f3`.
The signed RAM-only ROM SHA256 is
`5afbf628d2ac39c90c8e2c9b802e94f5b661ac970c6978b8c17c1d0b677e1366`;
the Pico no-flash UF2 SHA256 is
`29c9ce8694345c40184d684fc6107c5654139e370d56deb61fc05314282fdee3`.
Neither BIOS EEPROM nor Pico QSPI was written. The user reports VCN is
not fused off; continue tracing the firmware-fetch path and remaining
enable/isolation controls rather than trying to force a read-only
harvesting indication. Normal Fedora boot
`cf21392a-bff7-4f74-829c-d747bd9115da` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and the
Pi recovery timer inactive.

**Update 2026-09-29, delayed firmware BAR control:** The same pre-map
diagnostic hook read PSP `UVD_VCPU_CACHE_BAR_LOW0` at `0x2107c` after the
first full VCPU wait, **before** the second call replayed any cache-window
writes. Its encoded low 28 bits were `0x0fa00000`, matching the low 28 bits
of the first PSP load's firmware BAR value `0x1fa00000`. The first powered
load returned `ret=0/status=0`; `UVD_STATUS` stayed `4` and VCPU-ready did
not appear. Together with the pre-map size read below, two key PSP-visible
cache settings retained their values through the wait. The diagnostic
encoding discards the BAR's upper four bits, and neither result proves the
other map words, memory fetch, or execution. The reused kernel module and
runner call this event `cache-size0`; **in this boot the signed PSP hook
sampled BAR low `0x2107c`**, as pinned by the hook build and ROM generator.
Ten native ARM cases passed. Pico verified 1,934/1,934 substitutions across
two BIOS passes without fault, mismatch, late decision or RX stall.

The ignored [journal](../output/video-decode-20260922/results/bc250-vcn-delayed-barlow-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-barlow-premap-20260929.dmesg)
have SHA256 `8a64f31848d95875e51edf5d5add48b89b1f4898f54fd293b937121ce0ca73c5`
and `e5622d02f3e5b21a33a5c0c86d3573b4bc776f84caa59ae28eac7d9c353139f2`.
The signed RAM-only ROM SHA256 is
`e23083ed27a5bebdd1a3e6decab8aa29b33c6a4a0ae2c0ea2ce546fcc9ba084e`;
the Pico no-flash UF2 SHA256 is
`4ce2827f00dc4ac6919d3e3efd965d949a9573565b15489f7cb1317654d31377`.
Neither BIOS EEPROM nor Pico QSPI was written. The read narrows the
remaining cause to another mapping/fetch or VCPU enable/isolation issue,
or a disabled implementation. It does not make
`CC_UVD_HARVESTING=3` a writable start switch. Normal Fedora boot
`2ba7b9a9-7819-420e-971c-4e85a0daf1e7` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and the
Pi recovery timer inactive.

The pre-map full-width comparison above closes the remaining cache-window
retention question. Next examine VCPU firmware fetch and upstream
enable/isolation state rather than writing the harvesting indication.

**Update 2026-09-29, delayed pre-map cache read:** A second signed,
RAM-only PSP hook sampled `UVD_VCPU_CACHE_SIZE0` at `0x2010c` after the
first full Linux VCPU wait, but **before** the diagnostic call replayed any
of the 17 cache-window writes. It returned `0x64000`, the firmware-cache
size programmed by the first successful PSP load. The first load returned
`ret=0/status=0`; `UVD_STATUS` remained `4` and VCPU-ready did not appear.
The native ARM model checked ten paths, including that the marked path
performs only the two pre-map control writes. The Pico verified all
1,934/1,934 substitutions across two BIOS passes, with zero fault,
mismatch, late decision or RX stall. This establishes that this one cache
size register retained its value through the observed wait. It does **not**
establish persistence of the other 16 cache-window words, successful
firmware fetch, or a running VCPU. An earlier delayed cache-size read used
a hook **after** all 17 writes had been replayed, so that result alone
could not test persistence; this pre-map hook corrects the timing.

The [pre-map hook](../tools/pico2-interposer/driver-delayed-vcn-cache-premap.S),
[ROM generator](../tools/pico2-interposer/prepare_delayed_vcn_cache_premap_trial.py),
and [native check](../tools/pico2-interposer/test_delayed_vcn_cache_premap_trial.py)
pin the sample order. The ignored [journal](../output/video-decode-20260922/results/bc250-vcn-delayed-cache-premap-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-cache-premap-20260929.dmesg)
have SHA256 `aa2ca86269207ff8396b7bfde326d1e35f196aca3a06599e122d5209717f1ffb`
and `97d98c1b3b965d8b5d5549b95e0efbdbceb2d9ab1589e2fea9a6fb94f636814f`.
The signed RAM-only ROM SHA256 is
`03fad9151af973ea93bf9f384bf70e0703aa847a31bd54567fe458bfbe211fe5`;
the Pico no-flash UF2 SHA256 is
`14918996cbd1ee3a3df2ed5415cfe6b9bd4b9e0ae12cc9cf0a938903433c450b`.
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`31482e99-748c-48e1-9e60-927e4ab9ce75` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and the
Pi recovery timer inactive. The BAR low pre-map measurement above closes
the next gap. PSP-side fetch and VCPU status remain open;
`CC_UVD_HARVESTING=3` is not a demonstrated start control.

**Update 2026-09-29, delayed PSP reset read:** A signed RAM-only PSP hook
kept both known-working VCN cache-map tables in the driver's executable
region and put its new dispatch in the pinned zero cave at `0xe00200`.
The Pico verified 1,926/1,926 substitutions across two BIOS passes with no
fault, mismatch, late decision or RX stall. The first powered PSP VCN
firmware reload returned `ret=0/status=0`. After Linux waited one full
second for VCPU-ready (`UVD_STATUS=4`), a second, scratch-marked PSP call
read `UVD_SOFT_RESET` **without writing it** and reported low 28 bits `0`.
This includes the VCPU reset bit 3 and its VCLK reset-status bit 19: neither
had reasserted during the observed interval. The host's conventional reset
read remained `0xffffffff`, so host readback still cannot describe that
latch. VCPU-ready never appeared and no frame decoded. The result narrows
the failure to firmware fetch, another reset/clock/isolation gate, or a
disabled implementation; it does not prove which. `CC_UVD_HARVESTING=3`
remains an availability indication, not a demonstrated start command.

The earlier delayed-read profiles put their original 17-word address table
at `0xe19010`. All three stalled the first powered `LOAD_IP_FW` before the
delayed sample. A relocation-only control, which changed no executable
instructions, stalled at the same step (`ret=-22`, PSP response status `0`).
An earlier writable-data table experiment at that address had likewise
stalled, whereas the executable-region table worked. The offline PSP model
had copied and mapped that data area, but it did not reproduce the live
failure; its success was insufficient evidence for this address. Retain the
address and value tables at `0xe17d98` and `0xe17fb8` in any later live
profile. The [code-only generator](../tools/pico2-interposer/prepare_delayed_vcn_reset_code_trial.py)
pins that constraint, and its nine native-instruction cases passed.
The ignored [journal](../output/video-decode-20260922/results/bc250-vcn-delayed-reset-code-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/bc250-vcn-delayed-reset-code-20260929.dmesg)
have SHA256 `c018d33963325ddb6dd058a87d427275c891dae17d95e1a17a194a44f892afb2`
and `b0d0fbcf8cfbc86ee22950bc7595bcd55d602a36e04fcab827417e0beb37b3e0`.
The signed interposer ROM SHA256 is
`858ab76da6cab427fe83df1ff3b906f3a8fe5eb0e75d6ac8a545b23feb0461a0`;
its Pico no-flash UF2 SHA256 is
`1eac254c03fb7796a6376740ee80c59ab1c78aa44913d666e106a32d9ac3bc44`.
Neither BIOS EEPROM nor Pico QSPI was written. Normal Fedora boot
`f9330749-003d-404b-bc7e-a46343dd5a17` has `amdgpu` bound, `/boot`
read-only, no diagnostic GRUB entry, Pico CS-PASS v2 armed in SRAM, and the
Pi recovery timer inactive.

**Update 2026-09-29, harvest is a status clue and the alternate cache bank is
not the missing start switch:** `CC_UVD_HARVESTING=3` names the
`MMSCH_DISABLE` and `UVD_DISABLE` bits in AMD's VCN 2.0 register header.
It was already `3` before Linux VCN startup, stayed `3` when the local
power sequence changed `PGFSM_STATUS` to `0` and exposed
`UVD_VERSION=0x2001b`, and guarded host and PSP clear attempts did not
change its readback. The pinned VCN 2.0 driver never uses this register to
start the VCPU. These facts make it an availability indication, but do not
prove what drives it or whether it is physically read-only. Forcing the
displayed value is not a justified VCN start operation.

A guarded, read-only [DPG-bank survey](../tools/vcn-psp-diagnostics/prepare_vcn_dpg_bank_survey.py)
measured the alternate VCPU cache words at the same post-release phase as
the proven shared host/PSP scratch control. `UVD_DPG_LMI_VCPU_CACHE_*`
low, high, offset0 and VMID read `0` both before and after PSP; the DPG
clock/report word read `5`. Its low bit says clock enabled and its report
field is `2`, consistent with the driver's own `UVD_STATUS=4` busy value;
it is not evidence of firmware execution. The conventional VCPU cache low
and soft reset words still read `0xffffffff`, while `SOFT_RESET2=0x30000`
and `VCPU_CNTL=0x0ff20200`. `UVD_POWER_STATUS=0x800` has DPG mode clear,
and the pinned Linux startup takes the static path, so the zeroed DPG bank
is not a demonstrated route around the conventional register problem.
The scratch sentinel again matched the PSP's low 28 bits. The diagnostic
PSP hook intentionally returned status `0x7a13c0de`; the GPU did not bind
and no frame decoded. The ignored
[runner](../output/pico2/tos-entry-gasket12-prepspmap-vcn-scratch-20260929/physical-dpg-survey/vcn-runner.jsonl),
[kernel](../output/pico2/tos-entry-gasket12-prepspmap-vcn-scratch-20260929/physical-dpg-survey/dmesg.log)
and [Pico](../output/pico2/tos-entry-gasket12-prepspmap-vcn-scratch-20260929/physical-dpg-survey/pico-usb.log)
traces have SHA256 `8a37f8bdb1f714546c7ff0668fd2fa848b4b393cc8e131ed3a5eec23be82a682`,
`6a0cd13b90260cb3a66e0480bc25ab5063744f2d58ed797c5fda9ee27d63c4f5`
and `f3826ecb069d02227bed52fb940929ffe632bf84f6e04f8889380e3c1800065f`.
The module SHA256 is
`f39444e89677689f359b31925697481fe9a999c3e53fe5eb275a6605557c1a85`.
The Pico verified 3,308/3,308 RAM-only substitutions across four BIOS
passes, with no fault, mismatch, stall or late decision. No BIOS EEPROM or
Pico QSPI was written. After a CS-PASS recovery cold boot, normal Fedora
boot `1368e887-01dc-4869-b59d-cf3db1a7db4e` has `amdgpu` bound,
`/boot` read-only, no diagnostic GRUB entry and the Pi recovery timer
inactive.

**Build-source correction:** The survey's
[build script](../tools/vcn-psp-diagnostics/build_vcn_dpg_bank_survey.sh)
overlays `vcn-psp-driver-20260927/amdgpu_vcn.c` (SHA256
`6fc1584109ef3b782b37a211a84585e21b1a8268e624adff86370dbdaaa8d983`),
whose `amdgpu_vcn_fw_load_via_psp()` returns true for this PSP-loaded
system. The diagnostic module therefore registers VCN firmware with the
PSP and its host startup attempts to map the same TMR firmware address
`0xf41fa00000` used by the signed PSP replay. The separate *baseline*
`linux-7.2.5/amdgpu_vcn.c` selects a direct buffer on BC250; reading that
file as if it had been compiled into the survey was a mistake. The generic
"direct-load path enabled" log text does not establish which firmware path
the built module uses. The PSP can read back its TMR cache-map write, while
the host conventional cache read remains `0xffffffff`. Next work should
identify why that register subblock and VCPU reset are inaccessible or
ineffective from the host despite the authenticated PSP load.

**Update 2026-09-29, phase-matched host/PSP VCN scratch control:** A
RAM-only signed-driver hook read VCN-owned `mmUVD_SCRATCH1` at BAR byte
offset `0x1f854` during the post-release `LOAD_IP_FW` call. Immediately
before that call, the guarded kernel module read the register as zero
through both `SOC15(VCN)` and its absolute BAR offset, wrote
`0x5a13c0de`, and read back the same value. The PSP hook reported
diagnostic status `0x7a13c0de`: its low 28 bits `0x0a13c0de` exactly
match the host's sentinel low bits. The host restored the original zero
afterward. This establishes a shared, writable register visible to both
initiators at the same phase; a blanket host/PSP VCN address-route failure
or a blanket PSP-only shadow is not a sufficient explanation for the
cache/reset mismatch. It does **not** establish that the PSP and host see
the same latch at `UVD_SOFT_RESET` or the VCPU firmware-cache words, nor
does it prove whether their host readback failure is an access gate,
isolation, register alias, or BC250-specific implementation. The PSP hook
intentionally returned a diagnostic status, so VCN did not bind and no
frame decoded. `CC_UVD_HARVESTING=3` remains an availability indication,
not a demonstrated power/start command.
The archived runner's inherited `reset_low28` field names the scratch
diagnostic in this trial; its `psp_host_scratch_comparison` event identifies
the actual register and decoded value.

The first two candidate boots used a JPEG decoder scratch word at
`0x1e224`; in the full-VCN probe it read `0xdeadbeef` even through the
absolute BAR offset, so its guard skipped the PSP read. The earlier live
JPEG scratch control used a **JPEG-only** driver, which starts that
separate block. It was not a valid positive control for the full-VCN path.
The VCN-owned control above corrects that experimental mismatch. Its Pico
completed two BIOS passes with 1,654/1,654 verified substitutions and no
fault, mismatch, late decision or RX stall. The [signed RAM-only view
generator](../tools/pico2-interposer/prepare_cache_route_trial.py),
[guarded module generator](../tools/vcn-psp-diagnostics/prepare_vcn_crosspath_scratch.py),
[build script](../tools/vcn-psp-diagnostics/build_vcn_crosspath_scratch.sh),
and ignored [runner](../output/pico2/tos-entry-gasket12-prepspmap-vcn-scratch-20260929/physical/vcn-runner.jsonl),
[Pico](../output/pico2/tos-entry-gasket12-prepspmap-vcn-scratch-20260929/physical/pico-usb.log),
and [kernel](../output/pico2/tos-entry-gasket12-prepspmap-vcn-scratch-20260929/physical/dmesg.log)
traces preserve the trial. Their SHA256 values are, respectively,
`128341c24bbb316f38444ec15f87731fca21eed881ca297c5e8e3436769c9cc6`,
`fa1de644e7f86473ecca83c5e7a0f8b751f97ccf788ee2a37d6e53bd52a20781`,
and `436bf96c59dc85712e8ecbd76b09f0de2a10feddb4a939cd0eb920189b5a8faa`.
The module and Pico UF2 SHA256 values are
`3ed185f9952c93ac8acd2d52457f844b719f0860e0ed61e4149b734c72076155`
and `5434ac9be9b08fb2aa61f1c87cffc859b84a8568966b11527f1c457141aa7ebe`.
No BIOS EEPROM or Pico QSPI was written. The BC250 is back on normal
Fedora boot `d2a18690-dd65-4d01-b358-c3dd774d76a3`, `amdgpu` bound,
`/boot` read-only and no diagnostic GRUB entry; the Pico is CS-PASS v2
in SRAM and the Pi recovery timer is inactive.

**Update 2026-09-29, before/after PSP firmware-cache BAR read:** Two
signed, RAM-only interposer profiles reused the *same* 51-row early
client-12 policy and the same guarded native-VCLK startup module. Both PSP
hooks checked live `UVD_POWER_STATUS=0x800`. The pre-map hook read PSP
address `0x2107c` **before any PSP cache-window write** on diagnostic boot
`ad6cb862-f3c3-4a73-aeb6-e55717158fd0`; it reported status
`0x70000000`, encoding low 28 read bits `0`. Linux had already tried to
program the firmware-cache BAR low word to `0x1fa00000`, but host MMIO
read back `0xffffffff`. The post-map hook on boot
`b9459d49-61ae-4cbd-a928-ee969903ff52` wrote the 17 pinned windows via
the PSP, then read the same word and reported `0x7fa00000`, encoding low
28 bits `0x0fa00000`, matching the low 28 bits of the PSP's own
`0x1fa00000` write. The diagnostic return intentionally makes
`LOAD_IP_FW` fail; these two boots were access probes, not decoder-success
tests. The runner's generic `reset_low28` field represents the **cache BAR**
read in these trials. The 28-case post-map and 8-case pre-map native PSP
models passed. Pico substitution counts were 1,858/1,858 and 1,654/1,654,
respectively, with zero faults, mismatches, late decisions or RX stalls.

This shows the PSP can read back its own cache programming, while the
host's attempted write was **not reflected in the PSP-visible low 28 bits**
at the pre-map probe point. On its own, that probe did not distinguish an
inaccessible host VCN window, an address-route difference, or a private PSP
register shadow; the diagnostic encoding discards the top four bits. The
newer phase-matched VCN scratch control above shows that the host and PSP
*can* share a writable VCN register. A blanket route split is therefore
insufficient, although cache/reset-specific gating or aliasing remains
possible. The earlier successful PSP cache/reset replay and firmware reload
still failed to produce
`UVD_STATUS & 2`, so fixing host cache access alone is not a demonstrated
VCN start sequence. `CC_UVD_HARVESTING=3` remains an observed disable
indication, not a verified writable start control. The next causal work is
to identify the cache/reset-specific access gate or upstream isolation
control from the pinned address maps and SMU/PSP code, then verify VCPU-ready
and an actual decoded frame. The [RAM-only generator](../tools/pico2-interposer/prepare_cache_route_trial.py)
and ignored [pre-map trace](../output/pico2/tos-entry-gasket12-prepspmap-cache-route-20260929/physical/vcn-runner.jsonl)
and [post-map trace](../output/pico2/tos-entry-gasket12-cache-route-20260929/physical/vcn-runner.jsonl)
preserve the controls. The pre-map Pico/journal/kernel SHA256 values are
`37fcbce7750a9ae6c505806ac3417e38449c419f6e443b87b7d09691c28ddc86`,
`e8740eb2317891b50083721da27dd724d1c0a0c3c520016d5e1a9bfff30fcc3e`,
`9fc686df70e30f7d058438433d7dc967841cf5a177073b4eb45abb7cdb8e51ca`;
the post-map values are
`3722715fe4e8a5d1936915685b2a6fec017ceb7567354f1cbcf9cd1e802518f7`,
`75b18a75206bc8681d4e06ab8ba7618561a69794966c7157be2052bafbc84f66`,
`9eb2f9b9b518c60a97e19f70b05f28ad9412b095fd7f64cfe608904683ee4758`.
Neither BIOS EEPROM nor Pico QSPI was written. The BC250 is back on
normal Fedora boot `9ce1c8eb-de37-4d7b-b159-22974eee2bb4` with
`amdgpu` bound, `/boot` read-only, no diagnostic GRUB entry, PDU on and
Pi recovery timer inactive. No frame decoded.

The [offline PSP SVC address model](../tools/vcn-psp-diagnostics/verify_svc7b_address_space.py)
passed for this target: SVC `0x7b` maps argument `0x2107c` to its
`0x0102107c` aperture. The pinned [Linux register helper](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_reg_access.c)
uses a BAR `writel`/`readl` when the register falls inside `rmmio_size`.
The [captured boot](../output/video-decode-20260922/results/native-direct-bo-dmesg-20260929.txt)'s
GPU BAR 2 spans `0xd0000000`-`0xd01fffff` (2 MiB), so
both cache offset `0x2107c` and reset offset `0x20180` are inside the host
MMIO aperture; the host failure is not explained by falling through to
the driver's indirect PCI register path. The live IP-discovery segment-1
base is `0x7e00` dwords, and the cache-low register offset is `0x61f`
dwords, yielding the same host byte offset `0x2107c`. PSP service `0x7b`
addresses that offset through the `0x01000000` aperture instead. These
are different initiators and access mechanisms; matching nominal offsets
alone does not prove they hit a single physical latch.

**Update 2026-09-29, successful PSP reload after PSP-side reset release:**
The earlier reset-stability trial returned a diagnostic `0x70000000` status
from its signed PSP hook, so its subsequent `LOAD_IP_FW` failure did not test
firmware reload and reset release together. A new RAM-only profile combined
the verified early 51-row client-12 gasket replay with the late signed VCN
key/TMR driver. Its post-cache hook replayed 17 pinned memory-window writes,
wrote zero to PSP address `0x20180` (`UVD_SOFT_RESET` in the VCN 2.0 register
map), read it back with the relevant reset bits clear, and returned success.
The Pico verified all 1,854 substitutions across two BIOS passes, with zero
faults, mismatches, late decisions or RX stalls. On diagnostic boot
`5d0cb821-d07d-4a75-9634-1d7c77aa659d`, native SMU VCLK code 16 and
the guarded gate/power sequence applied. The second, post-release PSP
`LOAD_IP_FW` returned `ret=0`, `psp_status=0`, yet `UVD_STATUS` remained `4`
through ten waits and the GPU did not bind. Linux itself sets the `0x4`
`UVD_BUSY` bit before VCPU release; that value does not establish VCPU
execution. The required VCPU-ready bit `0x2` never appeared. This closes the
specific earlier test gap, but PSP-side reset readback still does not prove
the host VCN reset/cache path is responsive: host reads of those words were
`0xffffffff`. It also does not prove whether harvest `3` is physically
read-only or which upstream control produces it. The phase-matched VCN
scratch comparison at the top of this document has since confirmed that
the host and PSP can share a live VCN register. The cache/reset-specific
access or isolation control is still unknown. Rewriting harvest `3` is not
a supported start sequence. The ignored [Pico trace](../output/pico2/tos-entry-gasket12-postcache-success-20260929/physical/pico-usb.log),
[runner journal](../output/pico2/tos-entry-gasket12-postcache-success-20260929/physical/vcn-runner.jsonl),
and [kernel log](../output/pico2/tos-entry-gasket12-postcache-success-20260929/physical/dmesg.log)
have SHA256 values `556fc11097922b4ce2efa430718e14346d4c47f20211004e4ec198c7ec1c701e`,
`0ac23c7a81c7d2f07a7f18afcbfcca3941f11127515d62886d4a0e38b830beda`,
and `e170cb4da488667b66f6b6d1c48a2d2688f4c05cf966a08d7396f420f745ef1c`.
No BIOS EEPROM or Pico QSPI flash write occurred. The diagnostic entry was
cleaned, CS-PASS v2 restored in Pico SRAM, and normal Fedora boot
`de61e637-8f17-4c48-b9c9-e8b4e810433d` has `amdgpu` bound, `/boot`
read-only, the PDU on and recovery timer inactive. No frame decoded.

An offline, read-only [SMU Queue-3 call-graph audit](../output/video-decode-20260922/results/smu-msg-reachability-20260929.txt)
(SHA256 `8bc825fefc553a229b8291dd9c9d705fed8cd5318daf13edae67258eb780b7bf`)
of the pinned 256-KiB BC250 SMU snapshot found five dispatchable message handlers with
direct static-call paths to its generic slot-clock routine, including the
already tested `0x1d` clock request, and six paths to the generic domain
power routine. This only covers Ghidra-recognized direct calls;
callbacks and computed dispatch may be missing. It supplies no justified
VCN-specific power-up opcode, so another guessed PMFW message is not the
next board test. The audit uses the captured dispatcher's actual Queue-3
count `0xa9`: earlier counts of nine and eleven included table entries
at opcodes `0xb4`-`0xbd`, past that dispatch bound. More specifically,
the BC250 snapshot's Queue-3 dispatch
entry `0x09` at table offset `0x74ac` is `(handler=0, flags=0)`, while Van
Gogh's public SMU 11.5 header calls opcode `0x09` `PowerUpVcn`. Sending that
Van Gogh opcode to the BC250 cannot invoke a normal Queue-3 handler in the
captured firmware; it is not a substitute for identifying this chip's
power or isolation control.

**Update 2026-09-29, BC250 Queue-0 VCN opcode claim rejected:** A public
BC250 message atlas calls Queue-0 `0x0c` `PowerUpVcn` and `0x0b`
`PowerDownVcn`, but its own kernel-message-map record disagrees. The
[pinned SMU 11.8 header](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_8_ppsmc.h)
and the [original BC250 SMU client](../output/video-decode-20260922/sources/bc250-smu-unlock/bc250_smu/api_q0.py)
identify `0x0b` as `RequestCorePstate` and `0x0c` as `QueryCorePstate`.
The captured SMU image (SHA256
`b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0`)
has Queue-0 table base `0x706c`, with `0x0b -> 0x229dc` and
`0x0c -> 0x22ab4`. The [decompiled `0x22ab4` handler](../output/video-decode-20260922/smu-direct-clock-20260928/bc-smu-decompile.txt)
rejects a low-byte argument above core ID 7 and returns the selected
per-core state. It performs no VCN power action. A new
[read-only Queue-0 call-graph audit](../output/video-decode-20260922/results/smu-q0-reachability-20260929.txt)
(SHA256 `e8df9dbff9433860b5ea67644b2e49d53c84095f9c588a5d1f826095bd5d27dc`)
found no direct static-call path from any Queue-0 handler to the previously
identified generic domain-power or slot-clock routines. As with the
Queue-3 audit, computed callbacks may be missing; this does not prove no
VCN control exists elsewhere. It does rule out the proposed Queue-0
`0x0c` power-up experiment on this firmware.

The [SHA-pinned all-queue audit](../output/video-decode-20260922/results/smu-all-queue-reachability-20260929.txt)
(SHA256 `002930c285ea9432c26c9d26049a38f89069925b8c141d95d7acef22c5cdd2f4`)
also checked the declared dispatch bounds for Queues 1, 2 and 4. Queue-1
`0x10` does reach generic power code, but its decompiled handler
`0x2c10c` does not consume the message argument and calls
`0x246c8`, which explicitly operates on **domain 7**. It is not a
justified VCN/domain-6 power command. Queue-2 `0x27/0x28` call the same
clock handlers as Queue-3 `0x5c/0x5d`; their explicit slot indices are
`0x0e`-`0x12`, outside the identified VCN slots `0x16`-`0x18`. The
captured code has an explicit domain-6 shutdown helper `0x24764` with no
Ghidra-recognized direct callers and no matching explicit domain-6-up
helper. Computed calls and firmware-internal events remain possible, so
these are exclusions of specific guessed commands, not proof that VCN
cannot be powered.

**Current causal model (2026-09-29):** `CC_UVD_HARVESTING=3` is an observed
availability indication, not a demonstrated start control. The value is
already `3` before Linux VCN initialization; guarded PSP and host writes of
zero read back `3`; and local VCN power/version become live while it remains
`3`. Those controls do not prove that the register is physically read-only or
that the upstream disable source is harmless to the VCPU. The pinned VCN 2.0
startup does not write the register. It requests SMU power, configures local
power and clocks, maps firmware, releases reset, then waits for
`UVD_STATUS & 2`. On Cyan Skillfish, the SMU VCN power callback is absent and
the generic request returns success without a PMFW command. This is a real
startup gap, although the proper BC250 power/isolation command remains
unidentified. The authenticated firmware load, responsive local PGFSM and
version, and even a native VCLK request have not made the VCPU ready. PSP
reads/writes of VCN cache and reset words also do not match host MMIO
visibility. A delayed PSP read now confirms that reset bits 3 and 19 stayed
clear through the first full VCPU wait, so rapid reassertion of those bits
is not a complete explanation. The phase-matched PSP/host `mmUVD_SCRATCH1`
control passed, so a blanket host/PSP VCN route split is insufficient to
explain that mismatch;
the cache/reset-specific access gate, alias, or upstream isolation remains
unidentified. Separately, JPEG decoder scratch accepts a host sentinel while
JRBC scratch does not. The next useful causal control is a verified action
on the cache/reset access or upstream VCN isolation path that changes VCPU
readiness, followed by an actual decoded frame. Forcing the harvest readback
to zero would not satisfy those checks.

**Update 2026-09-29, UVDW power is not the missing JRBC start step by itself:**
The scratch control revealed one powered-state difference worth testing:
JPEG-only `UVD_PGFSM_STATUS=0x00200000` reports `UVDW_PWR_STATUS=2` (off)
while the local JPEG `UVDJ` field is on. A sixth isolated boot, under the
same verified RAM-only Pico profile, guarded an explicit UVDW-on request by
the exact measured `PGFSM_CONFIG/STATUS=0x00400000/0x00200000` and JPEG
power `0`. Writing config `0x00500000` changed status immediately to `0`;
thus the UVDW power field is a working control. Nevertheless JRBC scratch
still read `0 -> 0 -> 0` after its sentinel write, `JRBC_RB_CNTL/SIZE/WPTR`
stayed zero, and the JPEG ring again timed out. The JPEG decoder scratch
control remained live (`0 -> 0x5a13c0de -> 0`). A missing UVDW local
power request alone therefore does not explain JRBC isolation. This still
does not tell whether a different SMU/PSP route, availability gate, mapping,
or implementation is responsible. It also does not establish a writable
role for `CC_UVD_HARVESTING=3`.
The replayed 51-row client-12 PSP gasket policy has no segment-0
`0x1e2xx` or `0x1e4xx` window, yet host MMIO can write decoder scratch
at `0x1e224`. Therefore the missing JRBC row in that **PSP-client** table
cannot by itself be treated as a host-MMIO allowlist explanation; any PSP
readback comparison must first establish what that access path permits.

The [guarded UVDW generator](../tools/vcn-psp-diagnostics/prepare_bc250_jpeg_uvdw_power_probe.py)
and [build script](../tools/vcn-psp-diagnostics/build_bc250_jpeg_uvdw_power_probe.sh)
produced module SHA256 `cc6b465448eb9df13bffe589eebd17c95fb0482d2e575e09021fe3bcdfbf2ce0`.
Its ignored [Pico trace](../output/pico2/jpeg-uvdw-combined-20260929/pico-usb.log),
[runner journal](../output/pico2/jpeg-uvdw-combined-20260929/jpeg-runner.jsonl),
and [kernel log](../output/pico2/jpeg-uvdw-combined-20260929/dmesg.log)
have SHA256 values `5328e1067b7bbc99b4f1170d9ea6f995c61f2d39b40a76a98f39f17e965e59d7`,
`6b98bafcecea2aabb20c91f0bbfde7a3a826bacbbb1d70d52cfbc98d6428e6c3`,
and `4b9f55666a61cc26690f5e54ed3d36766cd29d0fd1c6627081453a72d003dd7f`.
The Pico verified 1,558/1,558 substitutions, with zero faults, mismatches,
late decisions and RX stalls. No BIOS EEPROM or Pico QSPI write occurred.
The diagnostic GRUB entry was cleaned, CS-PASS v2 restored in Pico SRAM,
and normal Fedora boot `c4b24c9c-1609-4f5b-9e55-dd82c20bc98d` has
`amdgpu` bound, `/boot` read-only and the Pi recovery timer inactive.
No hardware-decoded frame exists.

**Update 2026-09-29, JRBC register block fails a scratch control:** A fifth
isolated JPEG boot used the same verified RAM-only Pico profile and native
VCLK setup, then wrote distinct sentinels to two documented segment-0 scratch
registers and restored both original values before the ring test. JPEG
decoder `UVD_JPEG_DEC_SCRATCH0` at BAR byte offset `0x1e224` read
`0 -> 0x5a13c0de -> 0`; `UVD_JRBC_SCRATCH0` at `0x1e450` read
`0 -> 0 -> 0` despite a `0xa16bc250` write. This is a direct control for
the adjacent JRBC `WPTR/CNTL/SIZE` zero readbacks (`0x1e400/0x1e404/0x1e44c`):
the host can program JPEG decode and the LMI ring BAR, but neither the JRBC
scratch word nor its ring registers show a write. The ring still timed out.
The documented `JRBBM` clock-active and reset-clear indicators remained as
before. This strongly localizes the failure to the JRBC subblock access or
implementation, but does **not** distinguish an upstream isolation/disable
source, a BC250-specific register mapping, or absent hardware. It also does
not make `CC_UVD_HARVESTING=3` a start command. The next discriminating step
is to compare a PSP-side read of this specific JRBC word with the host view,
then trace the upstream availability/route control if the two differ.

The [scratch probe generator](../tools/vcn-psp-diagnostics/prepare_bc250_jpeg_scratch_probe.py)
and [build script](../tools/vcn-psp-diagnostics/build_bc250_jpeg_scratch_probe.sh)
produced module SHA256 `9123b4ed385203e19449c5e18466171fc9bb7e6e29409a5b881daac7eb663000`.
Its ignored [Pico trace](../output/pico2/jpeg-scratch-combined-20260929/pico-usb.log),
[runner journal](../output/pico2/jpeg-scratch-combined-20260929/jpeg-runner.jsonl),
and [kernel log](../output/pico2/jpeg-scratch-combined-20260929/dmesg.log)
have SHA256 values `61043cd34eb884a4c52c4be6ab9c88f2b14a01f57c114fe640cf9b59a5626f69`,
`f3f9b9693dc36757f46bdfc553d30398a7370ec764e5e59820ebba82c2c8c060`,
and `067cc4dc7dd8c625e4d8b4557eb0a9d33b99fdec257ffdfd36d12e1d13a20326`.
The Pico verified 1,558/1,558 substitutions with no fault, mismatch, late
decision or RX stall. Neither BIOS EEPROM nor Pico QSPI flash was written.
The diagnostic GRUB entry was cleaned; CS-PASS v2 was restored in Pico SRAM;
normal Fedora boot `bef7fc63-e767-4d39-b2a9-b773133243b5` has `amdgpu`
bound, `/boot` read-only, and the Pi recovery timer inactive. No frame decoded.

**Update 2026-09-29, harvest is an indication; JPEG ring remains inert:**
`CC_UVD_HARVESTING=3` is not established as a writable VCN start command.
The VCN 2.0 register header names its bits `MMSCH_DISABLE` and `UVD_DISABLE`,
and the pinned VCN 2.0 driver does not use it to start the engine. A guarded
write of zero read back `3`; more decisively, the combined early/late
client-12 policy changed VCN PGFSM/power/version to `0/0x800/0x2001b` while
the value remained `3`. That rules out clearing it as a prerequisite for
those tile-power transitions. It does not establish that the register is
physically read-only or that its upstream disable source cannot block later
VCPU execution.

With the same RAM-only Pico profile, a JPEG-only module (no VCN VCPU firmware)
found a responding JPEG power aperture: PGFSM config/status started at
`0/0x00200000`, the UVDJ-on request read back as `0x00400000`, and JPEG power
read `0`. The standard doorbell-fed ring still timed out. A second isolated
boot used the MMIO write-pointer path; its ring test also timed out with
software write pointer `0x10`, hardware read/write pointers `0`, an unchanged
pitch marker, and JMI reset bit clear. Its ring BAR readback was
`0x00000000:0x00264000`. Thus a doorbell-only fault does not explain the
failure. In the pinned Linux source, Cyan Skillfish supplies neither
`dpm_set_vcn_enable` nor `dpm_set_jpeg_enable`; generic SMU requests return
success without issuing a power command. Van Gogh implements those callbacks
with separate VCN/JPEG power-up messages, but the Cyan Skillfish message map
does not list their equivalents. This missing BC250 upstream step is a
specific candidate, not proof that a Van Gogh opcode is safe or supported.
A third isolated boot compared ring register write/readback. Immediately
after MMIO submission, `JRBC_RB_WPTR` read `0` instead of the written
`0x10`; `JRBC_RB_CNTL` and `JRBC_RB_SIZE` also read `0` despite standard
nonzero initialization. The programmed ring BAR *did* read back as
`0x264000`, exactly matching `ring->gpu_addr`; JPEG clock-control and JMI
registers were also readable. The ring test again timed out. Thus this is
not a blanket JPEG address-base failure: power/BAR registers respond, but
the JRBC ring-control subblock does not show the expected state. It may
still be held in clock/reset/isolation or have a different BC250 access
condition; these readbacks alone cannot prove physical absence or that
every zero-valued register write was ignored. A fourth isolated boot sampled
the documented clock and reset status registers before and after the ring
test. Both snapshots read `JPEG_SOFT_RESET_STATUS=0`,
`UVD_JRBC_SOFT_RESET=0`, `JPEG_SOFT_RESET2=0`,
`UVD_JPEG_POWER_STATUS=0`, and `JPEG_CGC_STATUS=0x1cf`. In the VCN 2.0
register definitions, the latter reports active JPEG decode and JRBBM
VCLK/SCLK bits. `JRBC_RB_CNTL` and `JRBC_RB_SIZE` still read zero, and the
MMIO write pointer read zero immediately after `0x10` was submitted. The
documented clock/reset status therefore does **not** explain this ring
failure. These are host-visible indicators, not proof that every internal
clock or reset is correct. The next question is why the JRBC register block
does not accept/show its configuration while adjacent BAR and clock/status
registers respond; compare a PSP-visible view or trace the upstream
isolation/availability routing before another write. For VCN, the decisive
question remains whether the VCPU can fetch firmware and assert
`UVD_STATUS` ready bit 1 after reset release. Do not substitute a forced
harvest readback for those checks.

The [JPEG-only log](../output/pico2/jpeg-early-late-combined-20260929/dmesg.log)
has SHA256 `509692673bfd2236463b930c6c08a6b36c0e9a8c4f7cbbfa37d97b32e2813cc6`;
the [MMIO-pointer log](../output/pico2/jpeg-mmio-combined-20260929/dmesg.log)
has SHA256 `8a7d3e939d76b7076a26a6b6b1df436085a8db47a8c801f0660f0cd58b85ef87`.
The [MMIO probe generator](../tools/vcn-psp-diagnostics/prepare_bc250_jpeg_mmio_probe.py)
produced module SHA256 `5b83d4d4a5ee78055022ac7873a8621c18b031fae7ea39ea4454e2e7809914e3`.
The [ring-readback probe](../tools/vcn-psp-diagnostics/prepare_bc250_jpeg_readback_probe.py)
produced module SHA256 `64a6b56569354182248245ca943c11b7571fb32444d3636c833ea94ba899ef87`;
its [Pico log](../output/pico2/jpeg-readback-combined-20260929/pico-usb.log),
[runner journal](../output/pico2/jpeg-readback-combined-20260929/jpeg-runner.jsonl),
and [kernel log](../output/pico2/jpeg-readback-combined-20260929/dmesg.log)
have SHA256 values `45faf96eefb88fa569b6cdadada9ec5509d571bb2ab24fcb3aeaaf6c7e1a8f85`,
`884218cce7c47facbfeb09933be4ab57a3afe79e78f95d0d4f3e7094bfe8acc4`,
and `43d6cabc1fc7638073970cac95645f91237250ce441d427b6ed61019584c074b`.
The [clock/reset probe](../tools/vcn-psp-diagnostics/prepare_bc250_jpeg_reset_clock_probe.py)
produced module SHA256 `f45a7a2f5ff2e759afb0c41b962981c1c1cc50696cb04ffc9c5d5dda0275333d`;
its [Pico log](../output/pico2/jpeg-reset-clock-combined-20260929/pico-usb.log),
[runner journal](../output/pico2/jpeg-reset-clock-combined-20260929/jpeg-runner.jsonl)
and [kernel log](../output/pico2/jpeg-reset-clock-combined-20260929/dmesg.log)
have SHA256 values `aef1d15913a9682fdbbd9e08c9e4f23b4fc2fc585bc3d7f85c527172c3e942e5`,
`7554b8835a1ef030218be36ddc8e5a9c1b447d0f27f48dcc2db323f06a97f71e`,
and `54694894e3161b5cd772274359a3c0d7acf44a0ada57213714ac8763b79a3b32`.
The Pico verified 1,558/1,558 substitutions in each boot with no fault,
mismatch, late decision or RX stall. Neither BIOS EEPROM nor Pico QSPI flash
was written. The diagnostic boot entry was cleaned, CS-PASS v2 restored in
Pico SRAM, and normal Fedora boot `9ff6237f-410f-45ea-8ea1-ace333b67bb3`
has `amdgpu` bound, `/boot` read-only, and the Pi recovery timer inactive.
No hardware-decoded frame has been produced.

**Update 2026-09-29, early-plus-late policy test:** The signed Trusted-OS
entry hook replayed all 51 client-12 `SEC_GASKET` writes before Trusted OS
continued. Its bounded readback encoded the descriptor at `0x0900c9a0` as
low 16 bits `0x0180`, matching the expected `0x20180`; this proves the early
write reached that aperture, but the marker does not measure the upper half.
A second, diagnostic boot combined that early hook with the late signed PSP
driver, authentic VCN key, TMR load and native SMU VCLK code 16. The Pico
verified 1,558/1,558 substitutions across two BIOS passes with zero faults,
mismatches, late decisions or RX stalls. VCN power/PGFSM/version reached
`0x800/0/0x2001b`, and PSP `LOAD_IP_FW` returned success. Nevertheless,
`CC_UVD_HARVESTING` was still `3`, host firmware-cache and soft-reset reads
were `0xffffffff`, the diagnostic PC sample was zero, `UVD_STATUS` stayed
`4`, and the decode ring timed out. The PC sample cannot prove lack of
execution because trace enable has not been shown to latch; the host
all-ones reads also cannot establish the PSP-visible register values. The
early policy timing by itself did **not** make the VCPU report ready. Treat
harvest as an availability indication until its upstream source is
identified, and investigate the VCPU firmware-fetch/isolation path before
claiming a decoded frame.

The [combined profile generator](../tools/pico2-interposer/prepare_early_and_late_gasket_trial.py),
[native early-hook check](../tools/pico2-interposer/test_tos_entry_gasket12_replay.py),
and ignored [Pico log](../output/pico2/tos-entry-gasket12-combined-20260929/physical/pico-usb.log),
[VCN journal](../output/pico2/tos-entry-gasket12-combined-20260929/physical/vcn-runner.jsonl)
and [kernel log](../output/pico2/tos-entry-gasket12-combined-20260929/physical/dmesg.log)
record the trial. Their log SHA256 values are respectively
`6af3605566a7a4918f7008a256c1b8b07f0417179e5416218637adba59a8d3bd`,
`e253bfd4aa83675374152fd34cdd9d52744974933cd0d355a08972bbef0c2d2c`
and `701c0c2a6eab5343b278db6409f56aac37d1c3fb9f2531250ecddcd510`.
This was a Pico SRAM-only trial. Neither BIOS EEPROM nor Pico QSPI flash was
written; no hardware-decoded frame was produced.

**Update 2026-09-29, early VCN policy baseline:** A read-only, RAM-only
Trusted-OS entry hook sampled the direct PSP aperture before Trusted OS ran.
It read the client-12 gasket transaction word `0x0900c234=0`, the descriptor
word `0x0900c9a0=0`, and `CC_UVD_HARVESTING` at `0x1f81c=3`. The marker and
six encoded value reads occurred in the expected order. The Pico completed
both firmware passes with 620/620 substitutions verified, zero fault,
mismatch, late decision or RX stall, and Fedora booted with `amdgpu` bound.
The [captured Pi log](../output/pico2/tos-entry-gasket-read-20260929/live.log)
has SHA256 `03d159ee969cdbce96599fc6ca12fe911dbd11a40867e659e28ffa452e240ccd`;
the [signed-view native check](../tools/pico2-interposer/test_tos_entry_vcn_policy_read.py)
passed with both full SMN addresses. This compares with the later full-policy
PSP-side descriptor readback of `0x20180`, suggesting that client-12 policy
setup is absent at TOS entry but can be applied later. It does **not** prove
the two access routes have identical semantics, that the early zero is a
hardware default rather than a power-dependent read, or that timing causes
the VCPU failure. The early policy replay and powered host checks were run
as reported above. The early `harvest=3` remains an observation, not a known
start control.

**Update 2026-09-29, matched SEC_GASKET policy controls:** A RAM-only Pico
profile replaying all 51 pinned client-12 policy writes, with no extra
post-cache/readback hooks, made VCN `PGFSM_STATUS`, `POWER_STATUS` and
`VERSION` readable immediately after PSP `SETUP_TMR`:
`0x00200000`, `0x801`, `0xdeadbeef`. Linux's local power-gating release then
gave `0`, `0x800`, and `0x2001b`. In that same powered run,
`CC_UVD_HARVESTING` **remained `3`** and `UVD_STATUS` remained `4`; VCPU-ready
bit 1 and a decoded frame never appeared. This is a matched confirmation that
the `3` is not a switch that must become zero before the VCN tile can power.
It does not prove the register is physically read-only or rule out an upstream
availability gate affecting the VCPU.

The same signed driver, TMR hook, VCLK request and kernel module were used
for controls selecting policy rows. Global rows alone (9 rows), the driver's
`0x1f844..0x1f84f` window plus globals (14), all early windows (31), all
late windows (29), and two 41-row profiles pairing all early windows with
either half of the late windows each left VCN power/version reads at
`0xffffffff` after `SETUP_TMR`. Four further profiles each omitted just one
five-write window from the full policy: `0x20108..0x20117`,
`0x21078..0x2107f`, `0x20eb0..0x20eb7`, or `0x1f860..0x1f863`. Each also
left the aperture all-ones. The Pico verified every expected substituted
read over two BIOS passes with zero fault, mismatch, late decision or RX
stall. Thus all four of these late policy windows are necessary **in this
replayed policy** to reproduce the partial aperture; the result does not
show that each individually controls a specific VCN register. The leading
next step is to understand how PSP `SETUP_TMR` consumes the complete policy
and why host reset/cache registers stay all-ones after tile power-up, then
measure a real VCPU firmware fetch or completed decode-ring job. Do not try
to force `CC_UVD_HARVESTING` to zero as a substitute for those checks.

The [51-row control journal](../output/video-decode-20260922/results/vcn-gasket-full-20260929.jsonl)
(SHA256 `b472688f12dbd7dc513f3a9add04804540e49ef62c9a91ca160eae7213b8b599`),
[kernel log](../output/video-decode-20260922/results/vcn-gasket-full-20260929.dmesg)
(SHA256 `79fcaecb279a87b5b7ba0a54e3cd828d616eb9878d37ee6a00348b7f660c81cd`),
and [row-selection generator](../tools/pico2-interposer/prepare_gasket12_global_control.py)
make this comparison reproducible. Each omission has its own `vcn-gasket-*`
journal and kernel log in the same results directory. These were Pico SRAM
trials; neither the BIOS EEPROM nor the Pico QSPI flash was written.

**Address-path check and failed live sampler, 2026-09-29:** Linux's Cyan
Skillfish UVD segment 1 base is `0x7e00` dwords. With the VCN 2.0 offsets,
`(0x7e00 + 0x260) * 4 = 0x20180` for `UVD_SOFT_RESET`, and
`(0x7e00 + 0x61f) * 4 = 0x2107c` for the firmware-cache BAR low word.
These are the exact byte addresses previously read through PSP services, so
the all-ones host reads are not explained by a simple Linux base-offset
mistake. A two-sweep idle-boot root-SMN control returned all ones at VCN
addresses while the known-live GFX control returned `0x48140880`; this was
after a failed VCN probe and cannot locate the failure within startup. Its
transient file did not survive the subsequent reboot, so only the terminal
readout remains. A 600-sample root-SMN monitor started before a
full-policy VCN run, but the BC250 then stopped responding before either
monitor or runner produced a saved result. The PDU restored it. Concurrent
root-SMN polling is therefore unsuitable here; do not repeat that trial.
The [idle-only reader](../tools/vcn-psp-diagnostics/read_vcn_root_smn.py)
now does just two reads and restores the PCI SMN index.

The first post-hang normal boot with the full experimental Pico profile had
an unbound GPU. Loading the verified Pico CS-PASS v2 RAM image and cold
cycling outlet 8 restored normal Fedora boot
`68d4b697-5877-49db-93ae-57df30a7905e`: `amdgpu` is bound,
`schedutil` is active, `/boot` is read-only and the Pi recovery timer is
stopped. No BIOS EEPROM or Pico QSPI flash write occurred. VCN hardware
decoding is still unverified.

**Control versus indication, 2026-09-29:** Do not treat
`CC_UVD_HARVESTING=3` as the VCN start switch. The VCN 2.0 register header
names its bits `MMSCH_DISABLE` and `UVD_DISABLE`; Linux's VCN 2.0 startup
does not write or test that register. Linux's VCN 2.5 driver reads its
`UVD_DISABLE` bit to mark an instance harvested, which is evidence for an
availability indication, although it does not prove how this BC250's
hardware generates or uses the bits. Guarded PSP and powered-host writes of
zero read back `3`, yet the active-profile run moved VCN PGFSM from
`0x00200000` to `0`, power from `0x801` to `0x800`, and version from
`0xdeadbeef` to `0x2001b` while harvest remained `3`. This proves that
clearing the indicator is unnecessary for those tile-power transitions; it
does not prove the register is physically read-only or rule out an upstream
disable gate affecting VCPU execution. The actual boot sequence requests
power, releases local power gating, enables VCPU clock, maps firmware/cache,
releases reset, and waits for `UVD_STATUS` ready bit 1. The present failure
is at that last step: status stays `4` and the ring times out.

The partial host aperture appeared during `psp_tmr_load()` only with the
active RAM-only PSP-driver profile. A CS-PASS control also issued a real
`SETUP_TMR` for a real TMR buffer but still saw all-ones VCN registers;
an earlier client-12 RSMU-only profile likewise left VCN MMIO all ones.
The profile's reference client-12 gasket writes are therefore the leading
candidate for opening the partial aperture, but the precise row and any
missing BC250-specific step remain unproved. Next isolate which profile
operation makes the power/version registers readable, then measure whether
host reset/cache writes reach the same hardware values visible to the PSP
and whether the VCPU fetches firmware. A completed decode-ring job and an
actual decoded frame remain the success criteria. No further blind harvest
write or BIOS EEPROM flash is justified by the current evidence.

**Update 2026-09-29 02:34 UTC, the partial aperture appears during PSP
`SETUP_TMR`:** A third hash-pinned module added read-only snapshots inside
`psp_hw_start()` and `psp_load_fw()` under the same verified RAM-only Pico
profile. VCN `PGFSM_STATUS`, `POWER_STATUS` and `VERSION` stayed
`0xffffffff` after PSP ring creation, firmware reservation and TMR buffer
allocation. Immediately after `psp_tmr_load()` they were `0x00200000`,
`0x801` and `0xdeadbeef`. In this boot, `psp_tmr_load()` submitted
`GFX_CMD_ID_SETUP_TMR`; the source and diagnostic log both show a real
TMR buffer. Non-PSP firmware loading and later GPU IP init left this state
unchanged. This brackets the host aperture transition to the TMR setup
call. It does not prove what PSP does internally, or whether a delayed
effect of an earlier command completes during that call. The VCN driver's
local static power-gating release again produced PGFSM `0`, power `0x800`
and `VERSION=0x2001b` while `CC_UVD_HARVESTING=3`; reset/cache host reads
remained all ones, `UVD_STATUS=4` never gained VCPU-ready bit 1, and the
decode ring timed out. A `3` to `0` harvest change is therefore **not
required for these tile-power transitions**. It could still reflect an
upstream permission relevant to VCPU startup; its causal source is not
identified. Do not infer physical read-only behavior or a fuse from it.

The [PSP phase journal](../output/video-decode-20260922/results/vcn-psp-phase-active-20260929.jsonl)
(SHA256 `d25fe5c271eb4fcbade12e808e4a034061ff5ac770f7d72445afee0547ed7b79`)
and [kernel log](../output/video-decode-20260922/results/vcn-psp-phase-active-20260929.dmesg)
(SHA256 `07addbec8113af12cdce15fe8461ea478f22f26342e88a4ed1a845955e19b315`)
record diagnostic boot `f647d903-f5e8-4576-a889-f54509269b3a`, with
1,402/1,402 Pico substitutions and zero fault/mismatch/RX stall. The
consumed GRUB entry was removed; a cold cycle with Pico CS-PASS v2 restored
normal Fedora boot `e26c4953-89c6-4c08-a660-b2bf18b76e28`.
`amdgpu` is bound, `schedutil` and GPU DPM `auto` are active, `/boot` is
read-only and the Pi recovery timer is inactive. No BIOS EEPROM or Pico
QSPI flash write occurred; no frame decoded. The next investigation should
isolate which operation inside the active `SETUP_TMR` hook opens the partial
aperture, determine whether host reset/cache writes reach VCN, and identify
why the VCPU never reports ready. A static version read is not a decode test.

**Update 2026-09-29 02:23 UTC, PSP hardware init opens the partial VCN
aperture:** A second opt-in module bracketed GPU IP hardware initialization
with read-only raw VCN register snapshots under the same verified RAM-only
Pico profile. `PGFSM_STATUS`, `POWER_STATUS` and `VERSION` were all
`0xffffffff` after software init, phase 1, and immediately before PSP
hardware init. Immediately after `psp_hw_init()` they were `0x00200000`,
`0x801` and `0xdeadbeef`, respectively. They did not change during the
following SMU firmware call or SMU, display, graphics and SDMA hardware
init. The VCN driver's local static power-gating release then changed the
first two to `0` and `0x800` and exposed `VERSION=0x2001b`; the VCPU still
did not become ready. This locates the first host-visible transition
inside PSP hardware init, not in the generic VCN SMU callback, and further
supports treating `CC_UVD_HARVESTING=3` as an availability observation,
not a switch to force. It does **not** yet identify which PSP operation
opens the aperture or why host VCPU reset/cache reads stay all ones. The
later PSP-phase probe above narrows this to `psp_tmr_load()`.

The [GPU IP phase journal](../output/video-decode-20260922/results/vcn-ip-phase-active-20260929.jsonl)
(SHA256 `dda802c1ffcca67a7b8f31273707bcfd8b7fd8009a4f2219551141acc35b897f`)
and [kernel log](../output/video-decode-20260922/results/vcn-ip-phase-active-20260929.dmesg)
(SHA256 `41f47f3e2b65a66b01547cf44f971d6e831f62cf87eff4b9900a9fe5a7e49c5f`)
record diagnostic boot `ba3a466a-65f8-4ce6-a8b8-bbabad36b041` and
1,402/1,402 Pico substitutions with zero faults. The Pico temporarily
stopped enumerating during recovery; stopping the Pi timer, restarting the
Pi, and reloading the known CS-PASS v2 image into Pico SRAM restored it.
The consumed GRUB entry was removed before the cold cycle. Normal Fedora
boot `e32a0c03-5b7c-43d2-ae6d-725d6c92bbd3` has `amdgpu` bound,
`schedutil`, GPU DPM `auto`, `/boot` read-only, and the Pi timer inactive.
No BIOS EEPROM or Pico QSPI flash write occurred; no frame decoded.

**Update 2026-09-29 02:10 UTC, phase-matched VCN startup:** A module with
six read-only phase snapshots ran with the exact RAM-only Pico profile that
previously exposed a powered VCN register block. The Pico verified 1,402/1,402
substitutions over two BIOS passes, with zero mismatch, late decision, RX
stall or fault. At VCN software init and resume, raw `PGFSM_CONFIG`,
`PGFSM_STATUS`, `POWER_STATUS`, `VERSION`, `SOFT_RESET` and cache BAR reads
were all `0xffffffff`. By the entry to `vcn_v2_0_start`, after other GPU
IP blocks had initialized, PGFSM was `0x00200000`, power `0x801`, and
config `0`; the version still returned `0xdeadbeef`. The generic SMU VCN
power call changed none of these values. The driver's local
`vcn_v2_0_disable_static_power_gating()` then produced PGFSM `0`, power
`0x800`, and a real version `0x2001b`. `CC_UVD_HARVESTING` nonetheless
remained `3` throughout the powered stage. This is direct evidence that
`3` is **not the register value to force for basic VCN tile power-up**;
it remains an availability/disable indication whose producer and causal
role are unresolved. It is not proof of a fuse or physical read-only
implementation.

The VCPU did not start: `UVD_STATUS=4` without ready bit 1, host reset and
cache BAR reads stayed `0xffffffff`, ten waits and the decode ring timed
out. Under CS-PASS, both the same phase module and the older direct-BO
control saw all-ones VCN registers at startup, so the signed Pico profile
is a prerequisite for the responsive aperture in these trials. The next
useful probe should bracket PSP hardware-init steps between
`after-vcn-resume` and `start-entry`, then compare PSP-side reset
and cache observations with host reads after local power-up. Do not repeat
a blind harvest write. [Active-profile journal](../output/video-decode-20260922/results/vcn-startup-phase-active-20260929.jsonl)
(SHA256 `788571bf257be7bc7e63c48680eef8210b13a75d90e7bc1cc1522aed6e3ea4f9`)
and [kernel log](../output/video-decode-20260922/results/vcn-startup-phase-active-20260929.dmesg)
(SHA256 `466e44cccb2fde9991c088543e19a7e164a710db6fdb423cce20884e89d98c38`)
record diagnostic boot `569545b2-f3ed-47a0-b4de-b22a6331f282`.
The CS-PASS [phase control](../output/video-decode-20260922/results/vcn-startup-phase-20260929.jsonl)
and [direct-BO control](../output/video-decode-20260922/results/vcn-direct-control-20260929.jsonl)
are preserved separately. The temporary boot entry was consumed and
removed, and the Pico returned to RAM-only CS-PASS v2. Normal Fedora boot
`b9c16e83-47ff-49bf-af34-31c5667c6fb2` has `amdgpu` bound,
`schedutil`, GPU DPM `auto`, `/boot` read-only and the Pi recovery timer
stopped. Neither BIOS EEPROM nor Pico QSPI flash was written; no frame
decoded.

**Update 2026-09-29 01:45 UTC, treat `CC_UVD_HARVESTING=3` as an
indication, and investigate the missing power request:** The value was
already `3` before Linux VCN startup, and guarded PSP and powered-host
write-zero attempts both read back `3`. AMD's VCN register header names its
bits `MMSCH_DISABLE` and `UVD_DISABLE`; other amdgpu paths read the latter
as an availability check, while VCN 2.0 startup neither reads nor writes
this register. These observations do **not** prove that the register is
physically read-only or that VCN is fused off. They do make another attempt
to force it to zero a poor startup test. In the pinned kernel,
`smu_dpm_set_vcn_enable()` and `smu_dpm_set_jpeg_enable()` return success
without sending a power command when the chip-specific callback is absent.
Both callbacks are absent from `cyan_skillfish_ppt_funcs`, and the public
SMU 11.8 message table exposes no named PowerUpVcn/PowerUpJpeg message.
Copying a Van Gogh or Navi 10 opcode would therefore be unjustified.

An opt-in JPEG-only module registered JPEG v2.0 without VCN/VCPU firmware.
Native SMU VCLK reached code 16 (1250 MHz); the three tested domain-6 slot
enables and domain gate/power controls took their requested values. The
standard JPEG start attempted to request the UVDJ tile on through
`UVD_PGFSM_CONFIG`; the wait timed out and printed masked
`UVD_PGFSM_STATUS=0x00c00000`. We initially interpreted field value 3 as
"tile off," but the wait prints **only bits 22-23**, so an all-ones raw
read would produce the same line. A second opt-in boot added full-register
readbacks before the request, immediately after it and on timeout: both
`UVD_PGFSM_CONFIG` and `UVD_PGFSM_STATUS` read `0xffffffff` every time.
The JPEG ring timed out and `amdgpu` did not bind. This is an inaccessible
or unresponsive host JPEG register aperture in that boot, **not** a proven
powered but off UVDJ tile. It also does not prove a physical fuse. The
initial masked `3` is a *different register field* from
`CC_UVD_HARVESTING=3`. An offline address check rules out an absent JPEG
base mapping as the immediate explanation: `JPEG_HWIP` aliases `VCN_HWIP`,
Cyan Skillfish maps that block to `UVD0_BASE`, and the PGFSM registers use
its nonzero segment 1 (`0x7e00`). The next useful investigation is the upstream
power/isolation and host-aperture enable path under the actual BC250 SMU
11.8 firmware, with a raw, non-all-ones register read as the first success
criterion. Only then should we use JPEG/VCN reset and ring tests.

The [JPEG trace](../output/video-decode-20260922/results/jpeg-only-native-20260929.jsonl)
(SHA256 `9aebaf987536ccd675728d154090f7761d198f41cdc0d661a0dc90051403f246`)
and [kernel log](../output/video-decode-20260922/results/jpeg-only-native-dmesg-20260929.txt)
(SHA256 `98b9ac8b21445dd74f2981366f214f8b6e9c44973ee8776e8f96f9df2589e108`)
record diagnostic boot `91ba45f6-1f10-4e9d-be0b-cf4819fe9262`.
After consuming and removing the one-time GRUB entry, a second outlet-8
cycle restored normal Fedora boot `23702a59-4b6e-4d29-844e-687a66a5fb09`:
`amdgpu` bound, governor active, GPU DPM `auto`, `/boot` read-only and no
diagnostic entry. Pi recovery timer is inactive. No BIOS EEPROM or Pico
QSPI flash write occurred, and no frame has decoded.

The [raw PGFSM readback trace](../output/video-decode-20260922/results/jpeg-pg-readback-20260929.jsonl)
(SHA256 `bdc0b70cc6b12db35236e1048dfd1485b1989c3977c5aecd8b7e212b41ad2582`)
and [kernel log](../output/video-decode-20260922/results/jpeg-pg-readback-20260929.dmesg)
(SHA256 `321981cad66a94dd746d0476cf5c5d918a4c7172026889d28f01a3ccaccd2b7a`)
record diagnostic boot `5aa7fe6f-c25e-4ccf-9243-58028cb6df97`. The
previous paragraph's normal-boot ID belongs to the first JPEG test. After
the second test, the consumed GRUB entry was removed and a separate cold
cycle restored normal Fedora boot `2404ff70-bf48-4cbe-aaf6-94122c95ba40`:
`amdgpu` bound, governor active, DPM `auto`, `/boot` read-only, no diagnostic
entry and Pi timer inactive. This test also wrote neither flash device.

**Update 2026-09-29 00:31 UTC, direct firmware BO under native VCLK still
does not start the VCPU:** The opt-in diagnostic used the pinned 405,952-byte
`navi10_vcn.bin` package and copied its declared microcode payload to an
ordinary GPU buffer at `0xf41fc00000`, rather
than the PSP TMR VCN firmware BAR. The guarded SMU callback applied the
1250 MHz VCLK request (hardware code 16); the three domain-6 slot enables,
domain gate and power commands also took their tested values. The powered
VCN register file returned `UVD_VERSION=0x2001b`, `UVD_POWER_STATUS=0x800`
and `UVD_PGFSM_STATUS=0`. Nevertheless, host cache and reset readbacks stayed
`0xffffffff`, `UVD_STATUS` stayed `4` through ten VCPU waits, the decode ring
timed out, and `amdgpu` did not bind. The observed `CC_UVD_HARVESTING=3` was
unchanged. Thus substituting an ordinary firmware BO for the protected PSP
firmware source, even with native VCLK and the tested power sequence, is not
sufficient to start this VCPU. It does **not** establish that the BO contents
were fetched, or rule out a separate host register-aperture, reset or
isolation fault. A zero VCPU PC sample is also inconclusive because trace
enable has not been shown to latch. The [trial trace](../output/video-decode-20260922/results/native-direct-bo-20260929.jsonl)
(SHA256 `867f9a69e1b1c579d27797619395eaab0d7827a6fcca8da71db16cbac807b2f6`)
and [kernel log](../output/video-decode-20260922/results/native-direct-bo-dmesg-20260929.txt)
record diagnostic boot `4018fab4-02a7-41e9-b116-d524410ec3cb`.
After the consumed one-time GRUB entry was removed and a second PDU cycle,
normal Fedora boot `73a2a974-9bc7-4db2-9fe7-dd523ff7f081` has `amdgpu`
bound, the governor active, DPM `auto`, `/boot` read-only and no diagnostic
entry. Pico CS-PASS v2 is armed from RAM and the Pi fallback timer is stopped.
Neither BIOS EEPROM nor Pico QSPI was written, and no frame has decoded.

**Update 2026-09-29 00:12 UTC, the Van Gogh clock-enable candidate did not
latch on BC250:** A read-only root-PCI SMN baseline returned
`0x0116f200=0`, the known-live GFX clock control `0x0115a820=0x48140880`,
and native VCN clock code `0x6d128=0`. The pinned BC250 SMU periodic
callback then applied a 1250 MHz VCLK request (hardware code 16; GPU metrics
1250 MHz), but the independent root-SMN read of `0x0116f200` stayed zero.
A separately preflighted, write-only SMU SRAM helper made one direct store of
`1` to that address while VCLK was active. The helper returned success, yet
two successive root-SMN reads still returned zero; the GFX control and VCN
clock code stayed at `0x48140880` and 16. The helper next stored zero,
restored every saved SRAM word and passed liveness checks. This particular
SMU-core store has no observed effect on the root-visible candidate. It does
**not** prove that the BC250 uses the Van Gogh register the same way, nor
that its root-SMN mirror reports the SMU-internal value. We should not treat
`0x0116f200` as a validated BC250 VCN start switch or repeat this store
without a new discriminator.

The [guarded runner](../tools/vcn-psp-diagnostics/trial_smu_clock_enable_after_vclk.py),
[root-SMN reader](../tools/vcn-psp-diagnostics/read_vcn_clock_enable.py),
and [live trace](../output/video-decode-20260922/results/clock-enable-after-vclk-live-20260929.jsonl)
record the test; trace SHA256 is
`9c1d37cc3d599877a598d6dc4dc7650969b3514eca8fd69cf8ca551acd3e9410`.
The Pi PDU fallback was active, then canceled after a deliberate outlet-8
cold cycle. Normal Fedora boot `0b30e353-070b-4d6f-9e37-71968eb39e1c`
has `amdgpu` bound, the governor active and DPM `auto`. Neither BIOS EEPROM
nor Pico QSPI flash was written, and no frame has decoded. The remaining
question is whether the VCPU can fetch firmware when the verified PSP cache
map and native VCLK are present; the `CC_UVD_HARVESTING=3` indication alone
does not answer it.

**Update 2026-09-28 23:39 UTC, VCPU reset release is insufficient:** A
RAM-only PSP-driver hook used the already tested powered VCN map, wrote zero
once to `UVD_SOFT_RESET` at `0x20180`, then read that register through PSP
service `0x7b` 128 consecutive times without another write. The final read
returned `0x00000000` with native SMU VCLK code 16 and the tested domain
gate/power sequence active. The module still reported `UVD_STATUS=4` without
the VCPU-ready bit, and the decode ring timed out. This excludes a rapid
reset reassertion **during those consecutive reads** as a sufficient account
of the failure; it does not establish that reset stayed clear after the
hook returned or that the VCPU fetched any instruction. We should now
measure the post-release control/firmware-fetch path or identify the
upstream availability gate, instead of repeating a single reset clear.

The [journal](../output/video-decode-20260922/results/native-reset-stability-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/native-reset-stability-20260929.dmesg)
record diagnostic boot `cb9b66df-a5b2-44c8-a605-075edd918dae`. The Pico
completed 1,414/1,414 substitutions over two boot passes with zero fault,
mismatch or RX stall. The profile's 29-case native ARM model passed, and
its ROM view differs from the previous verified diagnostic only in this
readback cave, the driver's body hash and the two signatures. Its 187 UF2
blocks target RP2350 SRAM `0x20000000..0x2000ba00`; neither flash device was
written. The runner calls the reported low-28-bit value `reset_low28`; it
is the last PSP `UVD_SOFT_RESET` read in this profile. The BC250 was
restored to normal Fedora boot `8e5cc91a-8355-4f3e-adee-716d66b7c255`
with `amdgpu` bound, `schedutil`, GPU DPM `auto`, `/boot` read-only, no GRUB
diagnostic entry and the Pi watchdog stopped. No frame has decoded.

**Update 2026-09-28 23:09 UTC, distinguish the disable indication from the
startup failure:** A new guarded, RAM-only diagnostic read the separate VCN
2.0 `UVD_SOFT_RESET2` word at PSP byte address `0x1ff98` *without writing it*
after Linux's VCPU release and the signed driver's 17 cache-window replays.
With the native SMU 1250 MHz VCLK request applied (slot `0x17`, hardware code
16), the PSP returned `0x00030000`: `MMSCH_VCLK_RESET_STATUS` bit 16 and
`MMSCH_SCLK_RESET_STATUS` bit 17 were set, while the writable
`ATOMIC_SOFT_RESET` bit 0 was clear. Powered VCN registers showed
`UVD_POWER_STATUS=0x800`, `UVD_PGFSM_STATUS=0` and `UVD_STATUS=4`; the VCPU
ready bit stayed clear and the decode ring timed out. The [runner journal](../output/video-decode-20260922/results/native-reset2-beforewrite-20260929.jsonl)
and [kernel log](../output/video-decode-20260922/results/native-reset2-beforewrite-20260929.dmesg)
record diagnostic boot `cfc23eb5-8534-41d8-b9d7-7843b150fbdd`. The runner
calls its parsed low-28-bit field `reset_low28`, but in this profile that
field is `UVD_SOFT_RESET2`, not `UVD_SOFT_RESET`. The Pico completed
1,402/1,402 substitutions with zero faults. Its native ARM model passed 28
cases. No BIOS EEPROM or Pico QSPI write was made.

`CC_UVD_HARVESTING=3` is an observed **disable indication**, not an
established software start control. AMD's VCN 2.0 register definitions name
its bits `MMSCH_DISABLE` and `UVD_DISABLE`; the VCN 2.5 driver reads the latter
to decide whether an instance is available. Our guarded PSP and powered host
writes of zero both read back `3`, and earlier captures found `3` before the
Linux VCN driver ran. That strongly argues against trying another runtime
clear. It does **not** establish whether this is a fuse mirror, a boot-latched
firmware setting, or a status indication driven by an upstream gate, nor
which direction any causal link takes. The `MMSCH` reset-status bits may
simply accompany `MMSCH_DISABLE`; ordinary VCN 2.0 startup uses the VCPU
path rather than the SR-IOV MMSCH path. They do not independently explain
why the VCPU never starts. The previous `UVD_SOFT_RESET=0x00080008` reading
is more directly relevant: it includes VCPU reset bit 3 and VCPU VCLK
reset-status bit 19. Compare VCPU reset state before and after the tested
SMU power/clock stages, and trace the BC250's own SMU and early-firmware
control flow before proposing another write. These status bits are
observations, not bits to force to zero. The separate pinned Van Gogh SMU
path is a reference, not proof of BC250 behavior.
The BC250 was restored to normal Fedora boot
`a6329fe6-db36-4bc7-9965-94152bfef2b6`: `amdgpu` bound, `schedutil`, GPU
DPM `auto`, `/boot` read-only and no diagnostic GRUB entry. Pico CS-PASS v2
was armed in RAM and the Pi recovery timer was stopped. No frame has decoded.

**Update 2026-09-28 22:46 UTC, reset status with native VCLK:** The latest
guarded diagnostic applied the SMU's native 1250 MHz VCN clock request (slot
`0x17` and hardware code 16), opened the previously measured gates, and
entered the opt-in VCN 2.0 startup. A PSP-side read of `UVD_SOFT_RESET` at
`0x20180`, **without first writing that register in the hook**, returned
`0x00080008`: VCPU soft-reset bit 3 and `VCPU_VCLK_RESET_STATUS` bit 19 were
still set after Linux's release sequence. The hook did replay the pinned 17
VCN memory-window values and the signed driver's other post-load requests, so
this is a post-release PSP observation, not an untouched snapshot of Linux
alone. Powered host registers reported `UVD_VERSION=0x2001b`, power `0x800`
and `UVD_STATUS=4`; bit 1 of status, the VCPU-ready condition, remained clear.
The [journal](../output/video-decode-20260922/results/native-reset-beforewrite-v2-20260928.jsonl)
and [kernel log](../output/video-decode-20260922/results/native-reset-beforewrite-v2-20260928.dmesg)
record boot `3a30b9c9-1a56-4303-98cb-80cdcacbc56e`. Pico verified
1,402/1,402 substitutions over two firmware passes, with no faults or stalls.

The preceding native-clock [reset-clear
trial](../output/video-decode-20260922/results/native-postrelease-reset-20260928.jsonl)
reported zero because its [PSP hook](../tools/pico2-interposer/driver-gasket-postcache-map-rx.S)
explicitly wrote zero to `0x20180` before reading it. The VCPU still failed
to report ready after that clear. Together, these measurements show that
native VCLK, the tested gates, and a PSP reset clear are insufficient; they
do not show that `CC_UVD_HARVESTING=3` is a writable start control or prove
why reset remains asserted. An initial version of the readback profile used
an older 40-byte TMR hook and produced all-ones VCN reads; that run is
inconclusive and was discarded. The corrected profile uses the proven
52-byte hook and differs from the prior powered profile only in the
reset-read hook, hashes and signatures. Its 28-case native ARM test passed.
The BC250 was restored to normal Fedora boot
`50c0acbb-fabc-4fb0-9640-be56480064f0`: `amdgpu` bound, governor active,
DPM `auto`, `/boot` read-only, passive CS-pass Pico relay armed, and recovery
timer canceled. Neither BIOS EEPROM nor Pico QSPI was written. No frame has
been decoded.

**Update 2026-09-28 22:05 UTC, native VCLK plus decoder startup:** The
periodic SMU callback table entry 24 at `0xc760` points to the native
clock-table walker at `0x2e448`. The earlier failed clock trial advanced
the generation before staging its VCN request, so the callback could consume
the zero request. The guarded [one-shot
trial](../tools/vcn-psp-diagnostics/trial_smu_clock_callback_once.py) staged
1250 MHz first and advanced the generation last. On a normal boot, the SMU
applied the 1250.0 MHz request, set slot `0x17` and hardware clock code 16,
and GPU metrics reported **VCLK 1250 MHz**. Releasing the three VCN slot
gates and reissuing the measured domain-6 power-up command still left
`UVD_VERSION`, `UVD_STATUS` and `UVD_POWER_STATUS` at all ones on that
normal boot. The [clock journal](../output/video-decode-20260922/results/clock-callback-once-20260928.jsonl)
and [gate journal](../output/video-decode-20260922/results/clocked-gate-probe-20260928.jsonl)
record the result.

The [combined diagnostic
trial](../tools/vcn-psp-diagnostics/run_late_vcn_native_clock_trial.py) then
used the same native SMU callback, previously measured gates, a RAM-only Pico
VCN interposer and the pinned opt-in Fedora VCN module. The SMU again
applied clock code 16; the gates and domain commands acknowledged. Linux
powered the VCN tile sufficiently to read `UVD_VERSION=0x2001b`, and the PSP
VCN firmware request returned success. Nevertheless,
`CC_UVD_HARVESTING=3`, while **host-MMIO readbacks** of `UVD_SOFT_RESET` and
firmware-cache registers remained all ones. The VCPU trace PC sampled zero
(trace enable has not been shown to latch), and `UVD_STATUS` stayed
at the driver's BUSY value `4` through all ten waits, and the decoder ring
timed out with `-110`. The [trial
journal](../output/video-decode-20260922/results/native-clock-vcn-startup-20260928.jsonl)
and [full kernel
log](../output/video-decode-20260922/results/native-clock-vcn-startup-20260928.dmesg)
preserve the evidence. Pico reported 1,402/1,402 verified substitutions over
two firmware passes, with zero faults or stalls. No BIOS EEPROM or Pico QSPI
write occurred, and no frame was decoded.

This strengthens the user's control-versus-status point: `3` is an observed
disable/availability indication, but its writability or causal role is still
unproved. A real clock and a successful PSP firmware request are insufficient
to make the VCPU report ready. Earlier trials showed the PSP can write/read
the cache map and reset register even while host readbacks are all ones. A
useful next discriminator was the PSP-visible reset state *after*
Linux's release sequence with native VCLK active; the newer update above
records it. Evidence of actual VCPU firmware fetch or a specific isolation
fault remains useful. Forcing a harvest
readback to zero would not test those mechanisms. The diagnostic Pico profile
later made a normal boot's PSP
`SETUP_TMR` fail, so the known-good CS-pass relay was restored in Pico RAM
before a recovery cold boot.

**Update 2026-09-28 21:08 UTC, native SMU clock experiment:** The
[pinned clock-walker trial](../tools/vcn-psp-diagnostics/trial_smu_clock_walker.py)
first passed an exact live firmware/table/slot preflight and a Q3 `0x1d`
no-op message. The no-op returned `(status=1, argument=0x100000)` and left
all measured state unchanged. An offline rollback model passed three cases.
The guarded volatile live run then set five other zero clock requests to the
firmware's skip sentinel, advanced the generation request, and sent Q3
`0x1d` for index 16 (VCN slot `0x17`) at 1250 MHz. The message acknowledged
`(1, 0x1004e2)`, and the requested float changed to 1250.0, but its
**applied** float stayed zero, the physical clock code and GPU VCLK metric
stayed zero, and the VCN slot cache was unchanged. Generation read back
`[1,1]`. This is evidence that the accepted mailbox response did **not**
start the VCN clock; it is not evidence that 1250 MHz reached the hardware.

Restoration then attempted to return the first generation word from 1 to 0.
The write did not hold on immediate readback, and the SMU stopped answering.
This is consistent with the firmware processing a generation mismatch while
host restoration was in progress, but the exact sequence is not proven.
The local background watchdog did not survive its launcher; we noticed this
and manually cold-cycled isolated PDU outlet 8. The next boot
`a18b3616-72bc-404f-8954-6e891592b460` passed the same read-only
preflight with the original table hash, VCLK 0, the governor active, GPU
DPM `auto`, and `/boot` read-only. The CLI's `native-clock` mode is now
disabled to avoid repeating this unsafe restoration. Its source remains for
review, and the [preflight](../output/video-decode-20260922/results/clock-walker-preflight-20260928.jsonl),
[no-op](../output/video-decode-20260922/results/clock-walker-noop-20260928.jsonl),
[live trial](../output/video-decode-20260922/results/clock-walker-native-20260928.jsonl)
and [post-recovery](../output/video-decode-20260922/results/clock-walker-after-recovery-20260928.jsonl)
journals preserve the observations. No BIOS EEPROM or Pico QSPI write was
made. The next candidate needs an identified firmware power/isolation path
and a rollback that cannot race the SMU's generation processing; a mailbox
acknowledgement or a static version register cannot count as VCN startup.

**Update 2026-09-28, control-versus-status conclusion:** The user's
distinction is supported by the evidence. `CC_UVD_HARVESTING=3` decodes as
`MMSCH_DISABLE | UVD_DISABLE` in the VCN 2.0 register masks, but no experiment
has shown that writing this register starts anything. It was already `3` at
ABL0 before VCN firmware loading, and guarded PSP and host writes of zero
read back `3`. In the pinned Linux AMDGPU driver, every use of
`CC_UVD_HARVESTING` reads it; none writes it, and VCN 2.0 startup does not
consult it. This supports a status/availability interpretation without
proving the hardware register is physically read-only. Do not use a
forced-zero readback as the next power-on experiment or treat `3` alone as
proof of a blown VCN fuse. The ROM discovery record says `harvest=0`, while
the live VCN availability register says `3`; the relationship between them
on this board is unresolved. Useful intermediate evidence is a VCN
`UVD_SOFT_RESET` or firmware-cache register that responds to a bounded
write/read trial, followed by a running VCPU and a completed decode ring.
The final success criterion is an actual decoded frame. The static
`UVD_VERSION` response alone is insufficient.

The source-derived startup path has a more concrete gap: Cyan Skillfish
provides no `.dpm_set_vcn_enable`, so the generic power call returns success
without a PMFW request. A public suggestion that Q3 message `0x21` might be
the missing power-up call is not supported as a *direct* domain-6 path in
our pinned SMU SRAM dump (SHA256
`b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0`).
The Q3 table at `0x7464 + 8 * 0x21` points to `0x249dc`. Its decompiled
handler calls `0x2494c`, which stores the message argument and a derived
value in SMU state; it does not call the domain-6 power or slot-clock
routines. An indirect later effect is still possible, so this only lowers
the priority of that particular message. [AMD's July 2026 response to a
BC250 VCN inquiry](https://www.mail-archive.com/amd-gfx@lists.freedesktop.org/msg148015.html)
also says video was outside this product's definition, that dies may vary,
and that PMFW or VBIOS support might be absent. Those are informed caveats,
not a measurement proving this individual die is defective. The current
investigation therefore remains focused on the actual power/isolation path
and direct VCPU/ring behavior, with no flash writes justified yet.

**Update 2026-09-28 20:17 UTC, SMU fabric-window trial:** The pinned
[read-only comparison](../tools/vcn-psp-diagnostics/compare_smu_fabric_window.py)
showed the SMU debug window and host root-SMN view agree exactly at the
domain-6 controls (`0x6d0f8=0x02`, `0x6d190=0x01010101`), core mask
(`0x5a870=0xff`) and candidate fabric gate (`0x50d6c=0xf0`). The
[guarded volatile trial](../tools/vcn-psp-diagnostics/probe_smu_fabric_bit11.py)
then sent an idempotent `0xf0` write and one `0x8f0` candidate write through
the SMU's secure debug-window service. Both host and SMU readbacks stayed
`0xf0` immediately after the candidate; VCLK was `0` MHz. Restoring `0xf0`
was acknowledged and independently read back; the SMU remained responsive,
the GPU governor restarted and the BC250 stayed on boot
`23e3fb45-1b13-4c58-be20-04c3b1bdc23a`. This specific live bit-11 store
does **not** latch through either tested view. It does not prove the bit's
hardware meaning or exclude a write before boot-time locking. The raw
[comparison](../output/video-decode-20260922/results/smu-fabric-window-compare-20260928.json)
and [trial](../output/video-decode-20260922/results/smu-fabric-bit11-20260928.jsonl)
are recorded. The first comparison harness accidentally held a PCI flock
across an SMU-library call, causing a self-deadlock; it was stopped, the
governor restored and the corrected per-read locking completed the comparison.
No target write occurred in that aborted run. No BIOS EEPROM or Pico QSPI
write occurred in any run here.

The pinned SMU decompile and [Ghidra xref
script](../tools/vcn-psp-diagnostics/Bc250SmuPowerXrefs.java) show the generic
slot-clock routine calls domain power-up only when the domain's state byte is
zero. The observed domain-6 status already has the up-ack bit, while VCN's
register access and VCPU readiness still fail. A further domain-up request
or another `0x50d6c` bit write is therefore lower value than locating the
isolation/fabric operation that actually makes the VCN cache and reset
registers respond. Hardware decoding remains unverified.

**Update 2026-09-28, answer to the harvest-control question:** Treat live
`CC_UVD_HARVESTING=3` as an observed disable indication, **not an established
start control**. The pinned VCN 2.0 startup never reads it, a guarded host
write of zero read back `3`, and it was already `3` at ABL0. The ROM's VCN
2.0.3 discovery record reports `harvest=0`, so firmware inventory and live
register state differ; neither observation identifies a physical fuse. The
Linux loads VCN firmware through PSP during initialization; its VCN 2.0 start
path then requests SMU power, sets local PG/clock controls, releases VCPU
reset, and waits for `UVD_STATUS & 2`. The Cyan Skillfish
SMU callback for that power request is absent. On the current normal boot,
the [read-only root-SMN diagnostic](../tools/vcn-psp-diagnostics/read_fabric_gate.py)
returned domain-6 control `0x6d0f8=0x02`, status `0x6d190=0x01010101`,
fabric `0x50d6c=0xf0`, and core mask `0x5a870=0xff`; GPU metrics report
VCLK `0` MHz. The domain status has an up-ack bit, while the control word
holds the clock gate for slot `0x17`. An earlier guarded trial cleared that
control word, enabled all three domain-6 slots, and issued the power-up
commands; VCN register access still read all ones. This means the gate is a
real control candidate but is insufficient alone. The useful next target is
the still unidentified isolation/clock/fabric path that makes VCPU reset and
firmware-cache registers respond, followed by a ring test and decoded frame.
No target register or flash was written during this update.

**Update 2026-09-28 19:28 UTC, SMU feature-name correction:** The pinned
[Cyan Skillfish SMU 11.8 PMFW header](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_8_pmfw.h)
defines feature bit 11 as `FEATURE_G6_SSC_BIT` (memory UCLK/UCLK_DIV spread
spectrum), **not a VCN power feature**. [Van Gogh SMU
11.5](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_5_pmfw.h)
uses the *same bit number* for `FEATURE_VCN_DPM_BIT`, which explains the
mistaken transfer between chips. The previously measured enabled bit,
callback returning `1` and clock-slot state byte therefore cannot establish
that VCN was powered. The earlier descriptions of bit 11 as a VCN feature or
the associated slots 3/4 as VCN tiles were incorrect. The
[offline audit](../tools/vcn-psp-diagnostics/audit_smu_feature11.py) now
checks that exact header and reports the proper feature name. This removes
feature-11 toggling and slot 3/4 reset as justified VCN experiments. The
actual PMFW VCN activation path remains unidentified; the Linux callback
gap below is still real. No board access or flash write was needed for this
correction.

**Update 2026-09-28 19:20 UTC, reframe the harvest register:** We have not
shown that writing `CC_UVD_HARVESTING=0` can enable VCN. The VCN 2.0 register
definition names the observed `3` as `MMSCH_DISABLE | UVD_DISABLE`, but this
may be a read-only or earlier-latched availability indication. It was already
`3` at ABL0, before Linux attempts to start VCN, and the guarded writes made
so far did not change its readback. Earlier entries calling it a *direct
blocker* are hypotheses, not a demonstrated causal mechanism. The pinned
[VCN 2.0 startup](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu/vcn_v2_0.c)
does not read that register; it conditionally requests SMU VCN power, then
changes local power/clock gates, enables VCPU clock, releases reset and waits
for `UVD_STATUS & 2`. VCN 2.5 does use the harvest value to skip instances,
but the BC250 reports VCN 2.0.3. The current normal Fedora boot has no VCN
ring: the stock [IP selection](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_discovery.c)
only registers VCN 2.0.3 with our opt-in experimental switch. Earlier
diagnostic boots enabled that switch, reached VCN startup and still left
`UVD_STATUS=4` with no responding VCPU. Thus discovery/registration and
physical startup are separate steps; the harvest readback has not been shown
to control either one.

The more concrete software gap is in the SMU power call: generic
[`smu_dpm_set_vcn_enable`](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/amdgpu_smu.c)
returns success without sending anything when the board's
[`cyan_skillfish_ppt_funcs`](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/smu11/cyan_skillfish_ppt.c)
lacks `.dpm_set_vcn_enable`. The [SMU 11.8 message
header](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_8_ppsmc.h)
also has no `PowerUpVcn` message, unlike Van Gogh's power callback. This does
not prove a callback alone would fix the hardware: BC250 needs an identified
PMFW power/clock/isolation sequence. The next diagnostic should measure the
actual VCN clocks, power and VCPU readiness around a bounded, RAM-only test
of that sequence on an isolated opt-in VCN boot, then confirm a decoded
frame. Current kernel `7.2.5-200.fc44.x86_64` is running with DPM level
`auto`; no flash write or board change was made for this source audit.

**Update 2026-09-28 19:10 UTC, early fabric-policy control:** Two RAM-only
Pico boots substituted only the *first* physical read of the `SEC_GASKET`
tuple at ROM `0x983068/0x98306c`: `0x1f820 <- 0x185103` became
`0x50d6c <- 0x8c0` (the measured ABL0 value `0xc0` plus bit 11). The second
read, signed policy, key and BIOS flash remained original. The
[generator](../tools/pico2-interposer/prepare_policy_one_shot.py) pins the
working ROM and each previously successful ABL0 readback profile. Both Pico
UF2s contained only SRAM blocks. The first, with an ABL0 `0x50d6c` readback,
served 1,398/1,398 substitutions over two boot passes with fault, mismatch,
late-decision and RX-stall counts zero. ABL0 returned **`0xc0` on both
passes** (`diag0=diag1=0x03c40300`), so the requested bit did not appear.
The complementary ABL0 `0x1f820` readback returned **`0` on both passes**
(`diag0=diag1=0x03c40000`) with the same 1,398/1,398 verified substitutions
and no Pico fault. This confirms the replacement tuple displaced the
original `0x1f820` write, while the fabric bit still did not latch by ABL0.

The pinned native TOS/driver instruction model issued 1,230 SVC `0x7c`
requests and changed exactly one request to `0x50d6c <- 0x8c0`; this checks
the policy loop, not whether the early physical store was accepted. The two
ignored Pi logs are under `output/pico2/early-policy-fabric-bit11-20260928-v1/`
and `output/pico2/early-policy-fabric-bit11-policy-20260928-v1/`, with SHA256
`832c5d330130a252ce5a148caa910b921559db816b8f540cc88ba2adfa8b7087`
and `9109b4a306fae2a2390d9e58bdef23c3ade0371523d314f68428807a358fd0d3`.
The RAM-only UF2 hashes were
`a2aaa567e3dafd70249b42910553b7aa3485ed1a576d0006b81686422b6e8841`
and `93cd1b8a724e2f96341fdaab66e039682fbbb69947c340ac392b51b14d2d63d2`.
Fedora booted after both trials; final boot
`23e3fb45-1b13-4c58-be20-04c3b1bdc23a` is running with `amdgpu` bound,
the GPU governor active and `/boot` read-only. `vainfo` still fails VA-API
initialization. The Pico was restored to armed CS-PASS v2 in RAM; neither
SPI flash was written. The experiment excludes this particular early policy
retarget as a fabric-bit fix. It does **not** distinguish a hardware write
block from an address-space or earlier-latch issue, and there is still no
VCN-decoded frame.

**Update 2026-09-28 18:47 UTC, Pi 5 restarted:** At the user's request, the
Pi 5 was rebooted over SSH. Its boot ID changed from
`72d6ec53-5bbf-4718-ad2a-76b6268934ef` to
`d68f76d0-1ac3-4f59-b842-bcc1dc3ebf23`. The Pico returned on
`/dev/ttyACM0`; the verified CS-PASS v2 UF2 (SHA256
`70b5af760d37bd4a30b4c0efc35d758cbfb5c415563a63b3f093844660e3829d`)
was loaded into Pico RAM and armed (`armed=1 gate=1 host_cs=1 miso=INPUT
bios_write=UNAVAILABLE`). The BC250 remained healthy on Fedora boot
`433d0c0b-5d62-4915-be73-722fb2497fe9`, with systemd running and the GPU
governor active. Neither SPI flash was written. Hardware decoding remains
unverified.

**Update 2026-09-28, pinned early-input audit:** The new
[read-only audit](../tools/pico2-interposer/audit_early_boot_inputs.py)
checks the known-working ROM, captured SPI profile and parsed signed policies
against their pinned SHA256 values. The resulting ignored
`output/video-decode-20260922/psp-analysis/early-boot-input-audit-20260928.json`
has SHA256
`711c2c6ebbfd72cc72e775d1831b66787ec4475e7e4a6e8e14342340397b1771`.
In captured read order, `SEC_GASKET` starts at row 1,648, SMU firmware at
7,456, ABL0 at 138,656, APCB at 139,072, TOS security policy at 253,720,
and signed `HARDWARE_IP_CONFIG` only at 776,712. Read order does not prove
when code ran or a register was set. The two parsed valid directories have
no type-`0x0b` soft-fuse-chain entry. The current APCB has a valid checksum
and contains `PSPG`, `DFG`, `MEMG`, `FCHG` and `CBSG`, but lacks `CCXG` and
`GNBG`; the retail P3.00 APCB has the same group set. This does not identify
why the VCN disable bits are asserted.
The signed `HARDWARE_IP_CONFIG` and `SEC_GASKET` objects are byte-identical
between the retail P3.00 ROM and the current known-working backup; APCB
differs. Thus the user's BIOS setting changes did not alter those two signed
objects.
The pinned decrypted PSP IPL's embedded 88-row SMN table also has no direct
write to `0x1f81c`, `0x1f820`, `0x1f8a4`, `0x50d6c` or `0x511b4`.

The signed IP-discovery `harvest=0` object is read much later than the ABL0
image and APCB in this trace; a separate ABL0-entry hook measured live
`CC_UVD_HARVESTING=3`. The inventory value cannot, by itself, prove this
specific chip's fuse state. [AMD's public response to a BC250 VCN
inquiry](https://www.mail-archive.com/amd-gfx@lists.freedesktop.org/msg148015.html)
says VCN was outside the product definition and individual dies may differ.
That response does not establish that this board's VCN is defective. The
next discriminating work is identifying an early hardware/bootloader source
or a demonstrably effective clock/isolation path; editing inventory metadata
alone is not supported by these measurements. No flash or board change was
made for this audit, and no VCN-decoded frame exists yet.

**Update 2026-09-28 18:26 UTC, Pi 5 restarted:** The Pi 5 was restarted over
SSH as requested; boot ID changed from
`07bcc707-ca2d-49f0-9a32-c1e9abe95a32` to
`72d6ec53-5bbf-4718-ad2a-76b6268934ef`. The Pico returned on
`/dev/ttyACM0`; its hash-verified CS-PASS v2 relay was loaded into RAM and
armed (`armed=1 gate=1 host_cs=1 miso=INPUT bios_write=UNAVAILABLE`). The
BC250 remained healthy on Fedora boot
`433d0c0b-5d62-4915-be73-722fb2497fe9`, with systemd running and the GPU
governor active. Neither SPI flash was written.

An offline audit of the parsed signed BC250 `SEC_GASKET` and
`TOS_SECURITY_POLICY` tables found no direct `0x1f81c` write. The 88-entry
SMN write table at offset `0x8928` of the pinned decrypted PSP IPL likewise
contains none of `0x1f81c`, `0x1f820`, `0x1f8a4`, `0x50d6c`, or `0x511b4`.
The two neighboring `SEC_GASKET` writes, `0x1f820` and `0x1f8a4`, were
already individually and jointly changed in first-read-only trials; ABL0
still read `CC_UVD_HARVESTING=3`. This narrows direct table-write candidates,
but a computed address, other firmware code, or a hardware latch remains
possible. Hardware decoding is still unverified.

**Update 2026-09-28 18:07 UTC, Pi restart and direct SMU write:** At the user's
request the Pi 5 was restarted over SSH. Its boot ID changed from
`086fe946-1318-48bc-a5e5-b7b46037a87a` to
`07bcc707-ca2d-49f0-9a32-c1e9abe95a32`. The verified CS-PASS v2 image was
reloaded into Pico RAM and armed (`armed=1 gate=1 host_cs=1 miso=INPUT
bios_write=UNAVAILABLE`). The BC250 stayed on Fedora boot
`433d0c0b-5d62-4915-be73-722fb2497fe9`; systemd and the GPU governor are
running. Neither SPI flash was written.

The previous direct SMU-core **read** of Van Gogh's `0x0116f200` clock-enable
address stalled its callback, while a known live `0x01210718` direct-read
control returned normally. A separate 90-byte write-only helper, assembled
from [source](../tools/vcn-psp-diagnostics/smu-direct-clock-write.asm) and
tested in Ghidra against the pinned BC250 SMU SRAM, then performed a guarded
volatile `0`, `1`, `0` sequence at `0x0116f200`. Each store returned the
expected SMU status. The target was deliberately never read. The V2.2 GPU
metrics reported VCLK/DCLK `0/1111` MHz before, after the `1`, and after
restoring `0`; the helper SRAM and dispatch slot were restored and verified.
The [runner](../tools/vcn-psp-diagnostics/smu-direct-clock-write.py) and
ignored [trial evidence](../output/video-decode-20260922/smu-direct-clock-20260928/live-toggle-01.jsonl)
(SHA256 `fdf8891aeb5562672cc1c1681aacd7ee9227f29a8d5c5dfc2c4425fbccc6d5d9`)
record the exact transactions. This proves the direct store path returns on
the BC250; it does not prove the register latched or that VCN clocks or the
fabric gate were enabled. No hardware-decoded frame exists yet.

A pinned [byte-window comparison](../tools/vcn-psp-diagnostics/compare_smu_vcn_windows.py)
found no nontrivial, exact 16-byte window shared between the Van Gogh SMU VCN
entry (`0x2bf30..0x2c007`) or its inner routine (`0x26984..0x26caf`) and
the BC250 SMU SRAM. Two Van Gogh SMN access routines supplied positive
controls, each with 54 matching windows. This suggests that simply invoking
an existing BC250 equivalent of the Van Gogh VCN routine is unlikely; it
does not rule out a rewritten equivalent or prove physical VCN absence.

**Update 2026-09-28, Pi restart and Van Gogh SMU cross-check:** At the user's
request the Pi 5 was restarted over SSH. Its boot ID changed from
`9539591b-cc47-421f-b63f-6f08fd3ecbe4` to
`086fe946-1318-48bc-a5e5-b7b46037a87a`. The Pico returned on
`/dev/ttyACM0` in its persistent passive image, so the hash-verified
CS-PASS v2 UF2 (`70b5af760d37bd4a30b4c0efc35d758cbfb5c415563a63b3f093844660e3829d`)
was loaded into Pico RAM and armed. Its final status was `armed=1 gate=1
host_cs=1 miso=INPUT bios_write=UNAVAILABLE`. The BC250 stayed on boot
`2c11882a-1254-4608-b325-a4d2092a71fd`, with systemd running, `amdgpu`
bound and `/boot` read-only. No BIOS EEPROM or Pico QSPI write occurred.

The pinned, decompressed ABL3 body (SHA256
`4b9f013864e9c96d5fed681a43af5e91d8322aaf6c51679e728b0ca099df94ba`)
was imported at `0x54000` with the
[Ghidra seed](../tools/pico2-interposer/GhidraAbl3Seed.java). It has no
direct little-endian literal for `0x50d6c`, `0x511b4`, `0x1f81c` or
`0x1f820`. A visible SVC `0x1b` call is in an error-reporting path, so it
cannot be identified as the operation that changed fabric state. Computed
addresses and PSP services remain possible. Separately, the pinned Van Gogh
SMU image (SHA256
`c4de5edc9eb2a9676b7c9a6811e71fee793192ba7bb340d7f6689c7b7eb89b25`)
was imported using the
[VCN seed](../tools/pico2-interposer/GhidraVgVcnSeed.java). Its function
`0x2bf30` writes `1` to the pointer stored at image offset `0x16c28`
(`0x0116f200`), then reads the pointer at `0x16c34` (`0x50d6c`). Only if
bits 11:12 are nonzero does it access the pointer at `0x16c38`
(`0x511b4`) and call the larger VCN path at `0x26984`. The pinned BC250 SMU
SRAM has its feature-11 callback, but no direct literal for these three
registers. That is a concrete difference in the observed power paths, not
proof that VCN is physically absent or that copying one write will enable it.
The operational harvest value remains `3`; no VCN-decoded frame exists.

**Update 2026-09-28, early policy retarget cross-check:** The Pi 5 and Pico
were responsive during this trial. A new RAM-only
Pico image used the same first-read-only `SEC_GASKET` substitution as the
earlier `0x1f81c <- 0` retarget trial, but changed its signed ABL0 diagnostic
hook to read `0x1f820`. ABL0 read `0` on **both** boot passes (`diag0=diag1=
0x03c40000`, where the diagnostic address encodes the low 16 bits). The Pico
verified 1,398/1,398 substitutions, completed both passes, and reported no
fault, mismatch or RX stall. Fedora boot
`2c11882a-1254-4608-b325-a4d2092a71fd` is running normally with `amdgpu`
bound and `/boot` read-only. VA-API still fails initialization. The matching
earlier trial read `CC_UVD_HARVESTING=3` at ABL0 on both passes. Together,
these observations support that the substituted tuple avoided the normal
`0x1f820 <- 0x185103` effect, while the live harvest state stayed `3`; they
do not prove that a write to `0x1f81c` reached the VCN block or identify its
disable source. The ignored Pi log is
`output/pico2/early-policy-live/policy-first-read-1f81c-zero-policy-20260928-v1.log`
(SHA256 `935f33ff1546e960b80d26e54811a18c18e60d6af80808cd9b809e2ad0a4491c`).
The UF2 SHA256 is
`7fed0d4f5be392056f277464d96cbc76b59ba96fd3c827ed4cc7fc59ae85062e`;
all 195 UF2 blocks target RP2350 SRAM. After the measurement, the Pi 5 was
restarted at the user's request (new boot ID
`9539591b-cc47-421f-b63f-6f08fd3ecbe4`); the Pico returned to its passive
image, then the known CS-PASS v2 relay was loaded into RAM and armed with
`host_cs=1`, `miso=INPUT`. The BC250 stayed running on the same boot.
Neither BIOS EEPROM nor Pico QSPI was written. No VCN-decoded frame has been
produced.

**Update 2026-09-28, guarded LMI control trial:** A pinned Fedora 7.2.5
diagnostic tested the LMI-control word suggested by the archived PS5
manufacturing-driver decompile. That source is a decompile without the
corresponding ELF, so the register setting was treated as a hypothesis. The
module required `UVD_POWER_STATUS=0x800`, `PGFSM_STATUS=0`,
`UVD_VERSION=0x2001b`, `CC_UVD_HARVESTING=3`, and the previously measured
VCPU/LMI state before writing one volatile register. It changed
`UVD_LMI_CTRL` from `0x00307340` to `0x00307108`, and immediate readback
matched. The pinned post-power PSP VCN firmware load succeeded
(`ret=0, status=0`), but the VCPU program counter remained zero,
`UVD_STATUS` remained the driver's BUSY value `4` through ten waits, and
the GPU did not bind. Thus this LMI setting alone does not start VCN or
produce a decoded frame while the operational harvest register remains `3`.

The [generator](../tools/vcn-psp-diagnostics/prepare_vcn_lmi_oracle_trial.py),
[build script](../tools/vcn-psp-diagnostics/build_vcn_lmi_oracle_trial.sh), and
[one-shot runner](../tools/vcn-psp-diagnostics/run_late_vcn_lmi_oracle_trial.py)
pin module SHA256 `56343ccf27087c59e3f86fb22536decc365519b4d4e8c25bac0e027cfd8a89e1`.
The ignored journal and dmesg are in
`output/video-decode-20260922/results/late-vcn-lmi-oracle-v01-20260928.*`.
The Pi remained on boot `daa8aff3-d9f1-425e-812f-51ed2c37d13a` after
its earlier restart; Pico verified 1,402/1,402 RAM-only substitutions in two
firmware passes with fault, mismatch, late-decision and RX-stall counts zero.
BC250 diagnostic boot `c7434188-0574-474c-b640-8cbd68f458bc` is running,
GPU unbound, `/boot` read-only and the unused one-time recovery entry removed.
Neither BIOS EEPROM nor Pico QSPI was written.

**Update 2026-09-28, Pi restart and cold-reset proposal audit:** The Pi 5 was
restarted over SSH while the BC250 remained on Fedora boot
`f9a9e050-19a0-407f-989c-afa13fd33cfa`. Its boot ID changed from
`6e1aa77a-fbfd-4fad-8dad-31e5f0eb88e1` to
`daa8aff3-d9f1-425e-812f-51ed2c37d13a`. The Pico re-enumerated on
`/dev/ttyACM0`; the known CS-PASS v2 image was loaded into Pico RAM and
armed with `host_cs=1`, `miso=INPUT`, and `bios_write=UNAVAILABLE`. The
BC250 remained healthy. Neither BIOS EEPROM nor Pico QSPI was written.

The public [direct cold-reset proposal](https://github.com/daveconde/bc250-vcn-enable/issues/2)
asks whether host SMN `0x0900c004 <- 1` has been tried. In the pinned BC250
PSP driver, native execution of the original success path requests exactly
that write through SVC `0x7c` for physical-function context `0xffff`, then
requests `0x1f8a4 <- 1`. The 27-case native status-guard test also passes.
On an earlier powered trial after the authenticated type-13 firmware load,
PSP-side SVC `0x7b` read `0x0900c004=1`, while the host root-SMN read of
that numeric address returned `0xffffffff`. This does not establish that a
host-origin write would have the same effect as a PSP-origin write, but it
removes a *missing reset value* as a supported explanation for our failed
VCN start. A previous host root-SMN read of a VCN register stalled the board,
so no new host VCN access was attempted during this audit. The remaining
lead is the `CC_UVD_HARVESTING=3` value already present before TOS and ABL0.

**Update 2026-09-28, early signed-policy check/use trials:** A read-only
ABL0-entry hook measured `0x1f820` low 16 bits as `0x5103` on both stock-policy
boot passes. The `SEC_GASKET` image at ROM `0x982000` carries the earlier
`0x1f820 <- 0x185103` tuple at `0x983068`; the captured SPI trace reads this
value twice before ABL0 (rows 2699 and 5539). Its original RSA-PSS signature
verifies under KEYDB_BL usage 31. The later signed driver is read only after
ABL0, so skipping its same-value write did not test this earlier setting.

Re-signing the early policy with the researcher key, even with its value
unchanged, stalled before the large UEFI read. All 536 requested Pico
substitutions were verified without a Pico fault, but Fedora did not boot.
Instead, [the one-read profile generator](../tools/pico2-interposer/prepare_policy_one_shot.py)
changed **only the first** physical read of the policy tuple, leaving its
second read, original signature, and usage-31 key untouched. With the first
`0x1f820` value set to zero, ABL0 measured `0`, both SPI passes completed
(1,396/1,396 substitutions, fault 0), and Fedora booted as
`f55b5eb1-97ef-47a6-b5f3-643adec7aae8`. This demonstrates that divergent
policy reads can change the executed early setting while this boot accepts
the stock signature. Which internal check uses each read is inferred from
these effects, not directly traced.

The same first-read method changed `0x1f8a4 <- 0xb` to zero; a separate ABL0
hook read back `0` on both passes and Fedora booted. However ABL0 still read
`CC_UVD_HARVESTING=3` when either policy value alone was zero, when both were
zero together, and when the first policy tuple instead requested an earlier
`0x1f81c <- 0` write. The last two trials each completed two passes with all
1,398 substitutions verified, fault 0, and Fedora running (latest boot
`f9a9e050-19a0-407f-989c-afa13fd33cfa`). VA-API still fails to initialize;
no VCN-decoded frame exists. These trials exclude those specific early policy
writes as effective harvest overrides, but do not establish fuse provenance.
The Pi 5 was restarted after one Pico USB disappearance; its known CS relay
was restored from RAM before BC250 power-on. The Pico loader now follows USB
serial re-enumeration. Neither BIOS EEPROM nor Pico QSPI was written. Private
traces are in `output/pico2/early-policy-live/`.

**Update 2026-09-28, ABL stage boundary and reversible fabric writes:**
Read-only, signed RAM-only hooks measured the low 16 bits of PSP-aperture
`0x50d6c` as `0x00c0` at ABL0, ABL1, ABL2 and ABL3 entry. An ABL3 ARM-exit
hook measured `0x00f0` after its Thumb worker returned; both boot passes
completed without Pico faults and Fedora booted. This brackets the change
within ABL3 execution. An ABL4-entry hook also measured `0x00f0`, but its
boot did not reach Fedora, so the healthy ABL3-exit run is the stronger
boundary observation. The ABL hooks return with PC-relative control flow
because later ABL images can be relocated in PSP memory.

Two separate guarded hooks checked the **full** word, requested only volatile
bit 11 (`0x00c0 → 0x08c0` at ABL3 entry, `0x00f0 → 0x08f0` at ABL3 exit),
sampled immediate readback, then restored the original word. In each of two
boot passes, the entry hook emitted SPI address `03c40300` (readback `0xc0`)
and the exit hook emitted `03c403c0` (readback `0xf0`). Those addresses also
show that both exact-value guards passed. The Pico verified all 41,552
entry and 41,176 exit substitutions with zero faults/mismatches; Fedora
returned on boots `22bd9369-773d-4cea-88a5-ce505db06086` and
`26864ce5-088d-4df5-9f43-53332b08cba2`, with `/boot` read-only. The
[entry hook](../tools/pico2-interposer/abln-entry-fabric-toggle.S),
[exit hook](../tools/pico2-interposer/abln-exit-fabric-toggle.S), and
[entry native execution check](../tools/pico2-interposer/test_abln_entry_fabric_toggle.py)
document the exact operations. Private logs are under
`output/pico2/abl3-{entry,exit}-fabric-toggle-20260928-v1/live/`.

The tested direct PSP-aperture write did not stick on either side of the ABL3
change. This does not identify the meaning or producer of `0x50d6c`, and no
causal link from it to VCN has been established. The operational
`CC_UVD_HARVESTING=3` predates ABL0 and remains the more direct blocker to
investigate. VA-API still fails; no VCN-decoded frame exists. The Pi 5 was
restarted once to recover a serial problem, and the Pi logger now reconnects
after Pico USB re-enumeration. No BIOS EEPROM or Pico QSPI payload was written.

**Update 2026-09-28, fabric changes after ABL0:** A read-only, signed
[ABL0-entry fabric hook](../tools/pico2-interposer/abl0-entry-fabric.S)
sampled the low 16 bits of `0x50d6c` through the same PSP aperture. Both
boot passes emitted `0x03c40300`, decoding to **`0x00c0`**. The Pico verified
1,394/1,394 substitutions with zero faults/mismatches; Fedora booted as
`be7f8590-798f-47a1-a1df-a5912b71ab2b` and reported `running`, with
`/boot` read-only. The [native ARM check](../tools/pico2-interposer/test_abl0_entry_harvest.py)
passed six synthetic MMIO values and five signed ABL views. Ignored trace:
`output/pico2/abl0-entry-fabric-20260928-v1/live/`.
By the first TOS instruction the same word was **`0x00f0`** in an earlier
trial. This establishes a change after ABL0 entry and before TOS entry, not
which ABL stage caused it. The VCN harvest word was already `3` at ABL0 and
did not respond to a guarded write there, so these are distinct timing
observations. The next useful measurement is at later ABL entry points.
No BIOS EEPROM or Pico QSPI payload was written; no decoded frame exists.

**Update 2026-09-28, guarded ABL0 write test:** With the ABL0-entry
measurement already reading `CC_UVD_HARVESTING=3`, a signed, RAM-only
[hook](../tools/pico2-interposer/abl0-entry-harvest-clear.S) checked the full
initial 32-bit value for exactly `3`, wrote volatile zero through the PSP
SMN aperture only on that condition, and encoded the immediate readback in
one SPI address. Both boot passes emitted **`0x03c4000c`**, meaning the
readback stayed **`3`**. The Pico reported 1,396/1,396 verified substitutions,
zero routing mismatches, zero faults, and two completed passes. Fedora booted
as `3e02c592-beaa-437d-93ef-ac8b06ee3fe4` and reported `running`, with
`/boot` read-only. The [native ARM check](../tools/pico2-interposer/test_abl0_entry_harvest_clear.py)
passed accepted and ignored write cases, nonmatching guard cases, and all
five RSA-PSS signed views. Private trace:
`output/pico2/abl0-entry-harvest-clear-20260928-v1/live/` (Pico status SHA256
`eb32a2f47842cdc5672ebef87b1e01d878c39b743cd02e5fd40f61ef156fae8b`).
The earliest controllable ABL0 instruction did not clear this value through
the tested aperture. It does **not** prove a fuse: the register could be
read-only, or a producer/lock could act before ABL0. The Pi/Pico remained
online, the PDU outlet stayed on, and no BIOS EEPROM or Pico QSPI payload
was written. No VCN-decoded frame exists yet.

**Update 2026-09-28, ABL0-entry measurement:** A RAM-only SPI interposer
replaced the usage-42 KEYDB_BL modulus and re-signed **all five** ABL images
with the existing researcher key. A re-sign-only control booted Fedora, so
the modified signing path was accepted without changing any ABL payload.
A second signed ABL0 header hook emitted an SPI marker at ABL0's first
instruction; its retry completed two boot passes and reached Fedora. This
establishes that the earlier ABL0 execution boundary can be measured, rather
than inferring execution from SPI read order. See the
[control generator](../tools/pico2-interposer/prepare_abl_resign_control.py),
[entry marker](../tools/pico2-interposer/abl0-entry-marker.S), and
[execution check](../tools/pico2-interposer/test_abl0_entry_marker.py).

The final read-only [ABL0 hook](../tools/pico2-interposer/abl0-entry-harvest.S)
used the PSP's direct SMN aperture to read the low 16 bits of
`CC_UVD_HARVESTING (0x1f81c)` and encoded the value in one SPI read address.
Both boot passes reported `0x03c4000c`, which decodes to **`0x0003`**.
The Pico verified 1,394/1,394 substitutions, with zero mismatches or faults;
Fedora booted as `11d83c4b-c21c-4372-82da-c3f3243bfe57` and reported
`running`. The [native check](../tools/pico2-interposer/test_abl0_entry_harvest.py)
covers six ARM MMIO/SPI cases and all five RSA-PSS signed views. Ignored
evidence is under `output/pico2/abl0-entry-harvest-20260928-v2/live/`.
This rules out an all-ones bus reply and places the VCN disable value
**before ABL0 executes**. It does not prove physical fusing or identify the
producer: an earlier PSP boot stage or SoC latch remains possible. The Pi
was restarted after one USB failure, the Pico was rearmed from RAM, and the
BC250 was recovered using the PDU. The final Pico remains on a RAM-only
interposer with MISO input-only between reads; BC250 is healthy. No BIOS
EEPROM or Pico QSPI payload was written, and no VCN-decoded frame exists.

**Update 2026-09-28, live SMU feature-11 audit after Pi recovery:** On the
unchanged BC250 boot `f1ba9964-3c6d-4e7b-bfd1-110633c2f5e2`, read-only SMU
access found feature-table base `0xcc98`, desired and enabled low masks both
`0xdd602c7d`, and Q0's reported enabled mask also `0xdd602c7d`. Bit 11 is
therefore enabled in all three views. The SMU 11.8 header names bit 11
`G6_SSC` (memory-clock spread spectrum), not VCN power. Its enable and disable callback
pointers are `0x1d938`; the live callback bytes
`36 41 00 0c 12 1d f0 00` match the pinned SRAM image. The Xtensa listing
shows this callback simply returns `1`. The live clock-slot state byte at
`0xCEC8+0x19` is `1`, and the slot down/up code bytes also match the pinned
image. The [offline audit](../tools/vcn-psp-diagnostics/audit_smu_feature11.py)
reproduces the pointer, code and disassembly checks.

The Q2 enable/disable feature handler reconciles the mask through those
callbacks. A bit-11 mask toggle alone does not directly call the separate
slot-down `0x1edb0` or slot-up `0x1edd4` routines. Those routines themselves
require bit 11 to be enabled before acting. Thus a Q2 off/on cycle is not a
justified VCN reset test; it could still have indirect interactions
with other SMU tasks, which this audit has not ruled out. No feature toggle,
board reset or flash write was made for this check. The operational problem
remains the observed pre-TOS `CC_UVD_HARVESTING=3`; locating its boot-stage
source is the next useful discriminator. No frame has decoded on VCN.

**Update 2026-09-28, Pi recovery and pre-TOS ABL audit:** On request, the Pi 5
was restarted over SSH. Its boot ID changed to
`b5f196fd-46bd-4dff-baa7-5a476e957a4f`; the Pico returned on
`/dev/ttyACM0` in QSPI `PASSIVE v1`. The known CS-PASS v2 image was reloaded
into Pico RAM and armed (`armed=1 gate=1 host_cs=1 miso=INPUT
bios_write=UNAVAILABLE`). The BC250 stayed on boot
`f1ba9964-3c6d-4e7b-bfd1-110633c2f5e2` throughout. No board or Pico flash
write occurred.

The [pinned pre-TOS audit](../tools/pico2-interposer/audit_pre_tos_abl.py)
verified the vendor RSA-PSS signatures and decompressed SHA256 digests of
ABL0–ABL4 in the known-working ROM. The captured SPI read profile covers each
ABL image before the driver and TOS images. This is read order, not a direct
execution trace; it means the first-TOS `0x50d6c=f0` sample cannot exclude
ABL initialization. A direct little-endian 32-bit scan of the decrypted IPL
and five decompressed ABL bodies found no literal for `0x50d6c`, `0x511b4`,
or `0x1f81c`. The IPL did contain the expected `0x5a870` control and SMN
selector literals. The absent literals do not rule out a constructed address,
a lookup table, or a hardware-derived value. An earlier ABL stage, PSP
bootloader, and SoC latch all remain candidates; a read-only stage-boundary
measurement is the next useful discriminator.

**Update 2026-09-28, fabric state predates TOS and resists its early bit-11
write:** A signed, read-only first-TOS hook measured PSP-aperture
`0x50d6c=0x000000f0`, core-mask control `0x5a870=0x77`, and VCN harvest
`0x1f81c=3`. On the same Fedora boot (`6fbc2b1d-5c27-4901-8055-ddbfb2d9af3a`),
the guarded host root-SMN reader returned `0x50d6c=f0`, `0x511b4=ffffffff`,
and `0x5a870=ff`. The changed core-mask control confirms the early sample
precedes a later initialization step; the fabric word is already at its
post-boot value before TOS runs.

A second RAM-only hook required that exact early triple, wrote only volatile
`0x50d6c <- 0x8f0`, read fabric and harvest, wrote the original `0xf0`,
read both again, and required the fabric restore before stock continuation.
Its Pico trace decoded **`f0, 3, f0, 3`**: bit 11 did not stick even
momentarily through the privileged IPL aperture. The safe-end marker was
present; Pico had `fault=0`, `788/788` verified substitutions over two boot
passes, and Fedora booted as `f1ba9964-3c6d-4e7b-bfd1-110633c2f5e2`.
The [read hook](../tools/pico2-interposer/tos-entry-vcn-policy-read.S) and
[reversible write hook](../tools/pico2-interposer/tos-entry-fabric-bit-toggle.S)
passed native ARM and signed-view checks; the ignored and restore-failure
paths were executed locally. Private trace SHA256 values are
`05e834d2c0daa9f2c65ca0dbafe85acdc49b77b60b2fd6d0cc02b3f86f2ce03b`
and `6765236c23a6f00451f164d48900279c6da109a9a8760dfc172b8ce1d638c8b6`.
This rejects an early single-bit write as an unlock; it does not identify
whether the word is read-only, locked by an earlier firmware stage, or derived
from another latch. No BIOS EEPROM or Pico QSPI payload was written. The
BC250 is healthy, and the Pico is back in armed RAM-only CS-PASS v2 with MISO
input-only. Hardware decoding remains unavailable.

**Update 2026-09-28, Pi restart, early policy readback, and bounded PSP
memory capture:** The Pi 5 was restarted on request while the BC250 remained
running. As expected, the Pico reverted to its passive QSPI image; a RAM-only
interposer was armed before the next PDU cold boot. At the first TOS
instruction, a signed read-only hook measured `0x1f820=0x00185103`,
`0x1f8a4=0x0000000b`, and `CC_UVD_HARVESTING (0x1f81c)=3`. A guarded volatile
trial cleared and read back both policy words, but a zero write to the
harvest word still read back `3`. The hook restored and verified the original
policy words before continuing; Fedora booted, with Pico `fault=0` and
`908/908` substitutions verified. This narrows the tested early policy
relationship but does not prove a physical fuse or identify the earlier
producer of `3`. See the [policy hook](../tools/pico2-interposer/tos-entry-vcn-policy-pair-clear.S)
and [native execution checks](../tools/pico2-interposer/test_tos_entry_vcn_policy_pair_clear.py).

A 64 KiB first-TOS memory read at `0x54000` ran too long: its trace mixed
ordinary BIOS reads with two incomplete hook attempts, and Fedora did not
boot. The captured first 4 KiB matched the prior SHA256 exactly. Loading the
proven CS-PASS v2 RAM relay and cold-cycling through the PDU restored Fedora.
The [slice hook](../tools/pico2-interposer/tos-entry-ipl-slice.S) now emits
three start and three end markers; the [decoder](../tools/pico2-interposer/decode_ipl_spi.py)
accepts one complete marked window and removes only the observed exact
16-word stock BIOS bursts. Native ARM execution, signed-view and decoder
checks passed. Two bounded 8 KiB captures, `0x55000..0x56fff` (SHA256
`45c6a7f5799ad7a37744c5f3ce2b4926dd607b47d5809f357a8e4473d03d8c84`)
and `0x57000..0x58fff` (SHA256
`19fdfedbecec483358d8eeef28bf67b2bcffa273355fd216a8e3c9cb0ecc8a43`),
each reached Fedora and contain AGESA ABL memory-init code and log strings.
Together with the `$PS1` header and ABL strings at `0x54000`, these identify
this region as ABL material, not the PSP bootloader whose earlier code may
set the VCN disable bits. Neither new slice contains the direct little-endian
`0x1f81c`, `0x1f820` or `0x1f8a4` address. Private traces and binaries are
under `output/pico2/tos-entry-psp-bl-{dump,55000,57000}-20260928/`.
The BC250 is healthy on boot `6dfb1084-0547-487a-868c-02dbc26a0fea`;
the Pico is armed in RAM-only CS-PASS v2, MISO input-only. No BIOS EEPROM
or Pico QSPI payload was written, and no hardware-decoded frame exists yet.
The next analysis target is the producer before TOS: an ABL stage, the PSP
bootloader, or a SoC latch. More adjacent ABL string/data slices would not
separate those possibilities.

**Update 2026-09-28, Pi recovery and PSP policy-memory check:** The Pi 5 was
rebooted after a Pico USB issue. The BC250 stayed up, but the Pico reset to
its QSPI `PASSIVE v1` image with all outputs off; the RAM-only `CS-PASS v2`
relay had to be loaded and armed again before any BC250 cold boot. Two later
RAM-only, read-only TOS-entry captures each verified all substitutions and
reached Fedora. The first dumped PSP memory `0x54000..0x54fff`; later adjacent
captures identify this as an AGESA ABL image, so the static value at IPL
offset `0x93f0` was not the sought
register table. Fedora booted as `490bfa30-71f7-4bf7-bb27-a9cf66219bc3`.

The second dumped `0x0779e000..0x0779efff`, the IPL pointer used for the
policy lookup. Its `$PS1` image has four sections and 144 register records,
all matching the already parsed **BC250 TOS_SECURITY_POLICY** in the clean
ROM at `0x9ca400`; see the [capture validator](../tools/pico2-interposer/check_runtime_tos_policy.py).
There is no direct `0x0900cxxx` VCN record in that policy. This confirms the
live policy object and its address, but identifies no new producer for
`CC_UVD_HARVESTING=3`. The second boot is
`c44a3872-e568-42b1-bf22-2a71192aa600`, with Pico `fault=0`,
`492/492` verified substitutions and Fedora running. Captures are private,
ignored files under `output/pico2/tos-entry-ipl-{config,register}-table-20260928/`;
their SHA256 values are respectively
`d490313ad83c037eb19c072638cdb048a84de7a0c493d1fc0f540db6ae671a16`
and `51ce3d1165d07ec2c999fc5d51717408e5e34163fbdebb55c2ad3f4be193f121`.
The Pico is now armed in CS-PASS v2 with MISO input-only, the second Fedora
boot remains healthy, and no BIOS EEPROM or Pico QSPI payload was written.
Hardware video decoding is still unavailable.

**Update 2026-09-28, VCN disable bits predate the Trusted OS and resist an
early volatile write:** The decrypted PSP IPL's `FUN_00007db8` selects its
SMN aperture with `0x0322003c <- address >> 4`, then reads
`0x02f00000 | (address & 0xfffff)`. A RAM-only TOS-entry hook applied that
same sequence at its first instruction and encoded the result in original
SPI-flash *read addresses*. Its `0x5a870` control returned **`0x77`** before
the Trusted OS ran; Fedora booted and the same boot's root-SMN control later
read **`0xff`**. This changing, known core-mask value validates the early
aperture path rather than a constant or replayed reply. The first control
attempt lost Pi USB and was recovered by restarting the Pi, loading the
CS-pass RAM image and cold-cycling via the PDU; a logged retry completed
with Pico `fault=0`, 564/564 verified substitutions and a healthy Fedora boot.

The identical early read of `0x1f81c` returned **`0x00000003`**. The Pico
captured both fixed start/end markers and encoded `03c4000c 03c80000`,
with `fault=0` and 564/564 verified substitutions; Fedora booted as
`d54b0f6f-0f6f-4f53-9bff-18d888c01fb8`. A separate, guarded TOS-entry
trial required that exact `3`, issued one volatile write of zero through the
same aperture, and read back **`3`** immediately. Its six marker/address
reads were `03c3fffc 03c4000c 03c80000 03c4000c 03c80000 03cffffc`:
before and after both equal `3`. The Pico verified 620/620 substitutions
without fault, and Fedora booted as
`4ef706ed-c32d-417b-82d9-68cd55626a1f`.
Five native ARM cases per hook verified register access, guard behavior,
continuation and signed ROM views before either physical run. See the
[read hook](../tools/pico2-interposer/tos-entry-ipl-aperture-read.S),
[write hook](../tools/pico2-interposer/tos-entry-ipl-harvest-clear.S), and
[their execution checks](../tools/pico2-interposer/test_tos_entry_ipl_harvest_clear.py).
Ignored Pi telemetry logs are under `output/pico2/tos-entry-ipl-aperture-harvest-20260928/live/`
and `output/pico2/tos-entry-ipl-harvest-clear-20260928/live/`, with SHA256
`73a950bdfb6a840ba992e70f10dcf654f983d189a526f0abd2ae8fc6d2f0e8c4` and
`04b00507ad4b7a86a0e8600d5b0a0e89d1ae090fb6ac997f8e3b83294bd3481f`.

The operational disable value is therefore present **before TOS, UEFI and
Linux**; the tested early and late volatile writes all leave it at `3`.
This does not distinguish an earlier PSP/SoC latch from a physical fuse or
establish a supported override. The hardware IP-discovery record still says
VCN `harvest=0`, so it cannot settle the live register's provenance.
No BIOS EEPROM or Pico QSPI payload was written in these trials, and no
hardware-decoded frame has been produced. The next useful boundary is the
IPL's own initialization or its underlying source for those two bits.
The BC250 is healthy on boot `4ef706ed-c32d-417b-82d9-68cd55626a1f`;
the Pico was returned to its armed CS-PASS v2 RAM image with MISO input-only.

**Update 2026-09-28, DF-lock omission did not make the suspected fabric word
writable:** A second RAM-only boot of the same SHA256-verified UEFI overlay
completed both 20,727-read passes (`41,454/41,454`, Pico `fault=0`, maximum
rearm 166 cycles). The Pico's input-only sample matched all 32 words of a
second-pass reply, and Fedora booted as
`3489ac2a-0b0d-4caa-a726-a4eb27071404`. A [single guarded host-SMN
probe](../tools/vcn-psp-diagnostics/probe_df_gate_after_lock_omission.py)
required that boot ID, the expected PCI IDs, `0x50d6c=0xf0`, and core-mask
control `0x5a870=0xff`. It attempted only a volatile bit-11 write
`0x50d6c <- 0x8f0`, read back **`0xf0`**, restored `0xf0`, and verified the
final `0xf0`. Thus skipping the identified UEFI `LockDFReg` call does not make
this particular word writable from the root PCI SMN path after boot. It does
not prove whether the callback ran, whether another lock exists, or whether
bit 11 is a VCN-present control. No BIOS EEPROM write or decoded frame.
That candidate boot remained healthy; the later TOS-entry trials superseded
this temporary Pico state.

**Update 2026-09-28, SMU message scan corrected offline:** A scan of the
pinned 88.6.0 SMU SRAM image initially attributed domain-power calls to
several sendable Q3 messages. Ghidra caller ownership disproved that broad
range match: the direct domain-6 function at `0x24764` is a *power-down*
routine with no references in this capture, while Q3 `0x5c/0x5d` call the
generic slot-clock routine for other slot numbers. The direct callers of
`0x23b14` include domain-7 up/down and domain-5/6 down, plus the generic
clock routine; they reveal no newly discovered native VCN power-up message.
The [reproducible xref script](../tools/vcn-psp-diagnostics/Bc250SmuPowerXrefs.java)
operates on the pinned SRAM snapshot. Sending Q3 `0x1a/0x42/0x60/0x9a`
as VCN power commands would be unjustified. The prior measured domain-6
clock and power trials remain the relevant negative hardware controls.

**Update 2026-09-28, full-stream candidate booted but VCN stayed disabled:**
The corrected early-CS-release Pico selector served both 20,727-read UEFI
passes from an exact-original QSPI control and Fedora booted. Its final
candidate trial served both passes from the SHA256-verified, equal-length
DF-lock omission payload (41,454/41,454 reads, `fault=0`, maximum rearm 162
Pico cycles); an input-only 64-byte second-pass MISO sample matched every
expected word. Fedora booted as `d8bd138b-2c0b-4228-b756-bcdb8e74cd27`,
but AMDGPU detected no VCN IP block and `vainfo` failed initialization.
Post-boot root-SMN `0x50d6c` stayed `0xf0`. The candidate does not enable
hardware decode and is not fit for a BIOS EEPROM flash. The Pi 5 was
restarted to recover Pico USB during passive-image restoration; original-
BIOS Fedora is now healthy on boot
`f695bd15-ce10-4b19-98b8-4fd3b37ca543` with Pico MISO input-only. The
BIOS EEPROM was never written. A direct GPU BAR5 MMIO `mmap` read had hung
an earlier candidate boot; do not repeat that probe. The next investigation
should identify the producer of the operational VCN harvest bits rather than
repeat the DF-lock omission. See [the detailed evidence](df-lock-control-20260928.md).

**Earlier late-selector result, superseded:** The first full-stream
candidate and exact-original control each stopped after one pass with an
older selector. The corrected early selector above cleared that timing
failure. The earlier one-pass result did not establish candidate boot
behavior.

**Correction to earlier local benches:** Pico `no_flash` RAM images had
uninitialized QMI/XIP, so the reported 34/42.5 MHz and 1,024-burst tests
initially compared zeros with zeros. The corrected image passed 1,000/1,000
nonzero 64-byte replies at 34 MHz; 42.5 MHz failed. A SHA256-pinned 64 KiB
actual-payload source then passed 1,024 consecutive reads at ~1,064 ns gaps.
These local tests do not prove BC250 on-wire integrity.

**Update 2026-09-28, 16 consecutive real-board SPI handoffs passed:** A
Pico-only 34 MHz test served 1,024 consecutive, increasing-address 64-byte
replies from sequential uncached Pico flash, at a measured steady CS# high
gap of 1,070 ns; every word matched. Its slowest core1 rearm was 52 Pico
cycles. A RAM-only BC250 control then supplied 16 consecutive **unchanged**
64-byte BIOS replies on **two separately armed boots**, with 16/16
completions per boot, zero fault, empty DMA/FIFO and slowest 133/137-cycle
(~391/403 ns) rearms; Fedora returned over SSH both times. An intervening
boot verified the image's pass-through fallback after its one-shot control.
No BIOS or Pico flash write occurred in that trial. At that stage, the first,
longer DF-lock candidate still needed a mixed four-byte/64-byte overlay:
an earlier four-byte scan reads three changed words at `0xae0088..0xae0090`,
and the early long-read order varies. The later equal-length candidate was
tested as reported above. See [the detailed timing and control
note](df-lock-control-20260928.md).

**Update 2026-09-28, Pico XIP path and full UEFI burst-gap timing:** A RAM-only,
on-chip test served 1,000/1,000 exact 64-byte SPI replies from the Pico's
uncached onboard flash at an actual 34 MHz. The apparent 42.5 MHz pass used
uninitialized XIP and compared zeros; the corrected 42.5 MHz run failed on
its first word. The BC250 stayed booted through both tests. A passive PDU
boot then measured all 21,610 internal CS# high gaps in
the first contiguous 64-byte UEFI read pass: minimum ~1,071 ns, median
~1,076 ns, maximum ~1,106 ns, with no command RX stall or truncated region.
Fedora returned. No BIOS EEPROM or Pico flash write occurred in those tests.
This cleared the 34 MHz single-burst XIP bandwidth concern and bounded the
software rearm deadline; the later full-stream overlay result appears above.
See [the control and timing note](df-lock-control-20260928.md).

**Update 2026-09-28, reversible 64-byte SPI handoff proven:** A new Pico
address-matching selector substituted exactly the original 64-byte response
at `READ03 0xae0140`, then Fedora booted. The Pico's own completion IRQ
reported `verified=1`, `fault=0`, no DMA or FIFO words left; its first-target
snapshot had original-flash CS# released and Pico MISO enabled. Passive mode
also booted with MISO disabled. A fresh complete read-only command trace shows
that `0xae00c0` between `0xae0100` and `0xae0140` occurs in one firmware pass
but is absent in another, explaining why a fixed-skip selector failed closed.
The DF-lock candidate has **not** been tested: the boot reads 1,386,944 bytes
of changed 64-byte replies, more than Pico SRAM. A multi-burst XIP/DMA
source or a narrower boot-stage patch remains necessary. Neither BIOS EEPROM
nor Pico flash was written, and there is still no decoded video frame. See
[the detailed control note](df-lock-control-20260928.md).

**Update 2026-09-28, UEFI DF-lock call identified but not yet tested:** The
known-working BC250 ROM's `AmdPspDxeV2` registers a PCI-enumeration callback
that sends PSP mailbox command `0x1b` at PE offset `0x229f`, with adjacent
`Psp.C2PMbox.LockDFReg` diagnostic text. A pinned five-byte omission and a
full-ROM recompression pass local execution checks, checksum validation and
independent UEFI re-extraction. The resulting ROM is **unflashed**. A
[published EPYC experiment](https://benschlueter.com/assets/paper/fabricked.pdf)
found that omitting this lock command alone restarted its different machine
before GRUB; it needed a second mailbox omission to boot. There is still no
evidence that BC250 `0x50d6c` is governed by this lock or that omitting it
would enable VCN. The existing Pico selector cannot inject the dense
recompressed, 64-byte-burst SPI region. A RAM-only, input-only Pico capture
verified one 64-byte read of the original ROM at ~33.34 MHz; Fedora returned
and neither flash chip was written. Exact offsets, hashes, checks and
constraints are in [the DF-lock control note](df-lock-control-20260928.md).

**Update 2026-09-28, PSP/host SMN alias control:** A second RAM-only
first-VCN read targeted the previously measured core-mask word `0x5a870`.
The root-SMN bridge read **`0xff`** both before and after the trial, while
`0x50d6c` remained `0xf0`. Actual Trusted OS instructions mapped service
argument `0x5a870` to PSP aperture `0x0105a870`; eight native diagnostic
cases passed. Cold diagnostic boot `7ec81d27-a824-42fd-b121-f6e0655eeed9`
returned **`ret=0, status=0x700000ff`** on the first VCN request, encoding
the PSP read of `0xff`. Pico verified **770/770** substitutions over two
passes, with zero faults, mismatches, late decisions and RX stalls. These two
distinct matching PSP/host values materially strengthen the SMN-alias
interpretation of the guarded `0x50d6c` write result below; they still do
not prove that bit 11 is a fuse or even that it denotes VCN on this SKU.
The diagnostic response intentionally failed firmware loading, and the
existing runner exited nonzero because it expected an ordinary successful
load; its journal shows the clock controls restored. The GPU is bound,
`/boot` is read-only, and the consumed GRUB entry is gone. There was no BIOS
EEPROM or Pico flash write and no decoded frame. The restricted generator
[`prepare_early_fabric_read.py`](../tools/pico2-interposer/prepare_early_fabric_read.py)
now accepts only these two read targets; the guarded host read is
[`read_fabric_gate.py`](../tools/vcn-psp-diagnostics/read_fabric_gate.py)
with `--core-mask-control`. Private trial ROM SHA256
`181976666f7b2eb19b69af32270496d6acbf4c4ad559fceb4abb010647053423`
and RAM-only Pico UF2 SHA256
`859d5da978b4ce307f555a83e22fc5c8c8c95ceb06a7c7df7146d331171f1755`
are ignored under `output/pico2/psp-5a870-alias-control-20260928/` and
`output/pico2/build-psp-5a870-alias-control/`. Ignored journal/dmesg
SHA256 pair under `output/video-decode-20260922/results/early-psp-5a870-alias-control-v01-20260928.*`:
`a469fe4e895ed3d7697fb8e686bf17827be8f9590c66f8b2c8c9b76f7c9ee887` /
`b2bc9e8910fcd97d1cc82ac2456a7fa889d29116b4165bb63bc9631414c706de`.

**Update 2026-09-28, the early PSP fabric gate was readable but resisted a
volatile write:** A RAM-only profile changed one already proven first-VCN
request diagnostic from PSP service argument `0x1f81c` to `0x50d6c`.
Actual-instruction execution showed that the Trusted OS maps this argument
to its `0x01050d6c` aperture; that numerical address is distinct from the
host's root-SMN `0x00050d6c`. On cold diagnostic boot
`5b1cc634-a790-46e8-b7c4-4a7a84a8cd00`, the PSP returned diagnostic
`0x700000f0`, encoding a successful read of **`0xf0`** at the first VCN
firmware request, before host VCN initialization. The earlier host root-SMN
read also returned `0xf0`, supporting an alias for this register on this
board. Pico verified all **770/770** substitutions across two boot passes,
with zero faults, mismatches, late decisions and RX stalls.

A second RAM-only profile guarded on that exact `0xf0`, requested a PSP
service write of `0x8f0` (bit 11 only), read it back, wrote the original
`0xf0`, and verified the final read. Nine native-instruction cases covered
successful, ignored and error paths before live use. On cold boot
`a8084cf3-e941-4f5d-b30b-f9d50e4c07cd`, it returned **`0x700000f0`**:
both write services and both follow-up reads completed without service
error, but the immediate post-write value remained `0xf0`; the restore read
also returned `0xf0`. A separate later host root-SMN probe again returned
`0x50d6c=0xf0` and `0x511b4=0xffffffff`. The Pico verified **834/834**
substitutions without fault or mismatch. This excludes a *late PSP service
write of bit 11* as a way to change that value. It does not prove which
earlier firmware stage or physical mechanism supplies the bits, nor that
the Van Gogh interpretation of bit 11 applies to the BC250. The diagnostic
PSP responses intentionally fail the firmware-load request, so neither run
tests decoding. The board remains reachable with GPU bound in isolated
diagnostic mode, `/boot` read-only, no pending one-time GRUB entry, and no
BIOS EEPROM or Pico flash writes.

The pinned generators are
[`prepare_early_fabric_read.py`](../tools/pico2-interposer/prepare_early_fabric_read.py)
and [`prepare_fabric_bit_probe.py`](../tools/pico2-interposer/prepare_fabric_bit_probe.py);
the [native probe check](../tools/pico2-interposer/test_fabric_bit_probe.py)
and [address-space check](../tools/vcn-psp-diagnostics/verify_svc7b_address_space.py)
are reproducible offline. Private, never-flash ROMs and Pico UF2s are ignored
under `output/pico2/psp-{50d6c-read,fabric-bit-probe}-20260928/`.
Archived journals and dmesg are ignored under
`output/video-decode-20260922/results/early-psp-{50d6c-read,fabric-bit-probe}-v01-20260928.*`.
The first journal/dmesg SHA256 pair is
`7556633ed46f63e2bd776b1f839b7233bd2ab953118f4225a33cb46b30fc84e2` /
`a1d094f336f0c32a4f66d4d7143c4b9ef23db100bd15276f03aeae1b42510be1`;
the second is
`485f6fc6d72dd883bb4c94cd7102edd99f7db73b2d6098cb88629858b761285c` /
`b8815b17ae549629d022511474d7526553a585b4201876a02d57a8abdc528fb4`.

**Update 2026-09-28, both observed `0x1f820` writes omitted:** A new RAM-only
profile retained the native type-13 omission below and guarded the earlier
signed `SEC_GASKET` section `0x201` service loop. It skips only
`(address=0x1f820, value=0x185103)`; the authenticated policy object remains
byte-identical. Offline execution of the original and guarded Thumb loops
produced respectively 1,230 and 1,229 service calls, with exactly that one
pair removed. Three predicate controls passed. The re-signed driver profile
had 491 changed SPI words and 729 expected substitutions per boot pass; the
Pico verified **1,458/1,458** across two passes, with fault, route mismatch,
late decision and RX-stall counts all zero. The resulting BC250 boot
`5eeba018-0e66-43c9-81a9-dbcdd927b49d` reached diagnostic Fedora. Powered
host MMIO still read `power=0x800, pgfsm=0, harvest=3`. The post-release PSP
VCN firmware request returned `ret=0, status=0`, but `UVD_STATUS` stayed at
the driver's own BUSY value `4` through ten waits, and the decode ring timed
out `-110`. The GPU did not bind and no frame decoded. This shows that the
combined omission was not sufficient. The early policy loop was verified
offline; its execution in this particular boot was **not** independently
marked, so the result does not prove it was reached or locate the disable
source. The [generator](../tools/pico2-interposer/prepare_policy_control_trial.py),
[policy-loop execution check](../tools/pico2-interposer/test_policy_control_trial.py)
and [trial notes](../tools/pico2-interposer/VIDEO_DRIVER_TRIAL.md) are tracked.
Ignored trial ROM SHA256 `08dbb3482270fad1d126999d835783171132d18a13cd44a019ac6e16926af2b4`
must never be flashed to BIOS EEPROM; ignored UF2 SHA256
`7db5b1e26415351abd7c390788aa3968ed63e64582140df1da1aefdd0b4184bf`
was loaded into Pico RAM only. Journal SHA256
`f2d9b1335abec46ccf12680dc16350f35df19950b3a8c65b0ede6a78e33f363b`
and dmesg SHA256
`8e01cbc8c9d7e62fc38704eec64b40a2af7841c42ac13d51d1f4b163e8ccfb0c`
are under ignored `output/video-decode-20260922/results/late-vcn-skip-both-control-v01-20260928.*`.
The board is reachable in diagnostic mode, GPU unbound, `/boot` read-only;
the unused one-time GRUB entry was removed. Neither BIOS EEPROM nor Pico
flash was written.

**Correction 2026-09-28, SMU feature 11 is not VCN power:**
The earlier claim that SRAM byte `0xCEE1=1` means the VCN gate is stuck
closed misreads the firmware. In the pinned 262,144-byte SMU SRAM snapshot
(`output/video-decode-20260922/results/smu-sram.bin`, SHA256
`b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0`),
pointer `0x171d4` resolves to `0xCEC8`; its byte `+0x19` is indeed `1`.
Pointer `0x17374` resolves to `0xCC98`; the feature word at `+8` is
`0xdd602c7d`, with feature bit 11 set. The SMU 11.8 header names this
`G6_SSC` for memory-clock spread spectrum. The pinned Xtensa instruction
listing (`output/video-decode-20260922/decompiled-postincrement/listing.txt`,
SHA256 `ed542af5f4e041d6b498a530584e16676c114881e00af736d615d03f36232ad9`)
shows a clock-slot down routine checking that byte for `1`, calling slot-down
for slots 3/4, then clearing it (`0x1edb0..0x1edcf`). The up routine requires
byte `0`, calls slot-up for slots 3/4, then sets it to `1`
(`0x1edd4..0x1eeb1`). Thus `1` is consistent with an already-run up path,
but does not establish any VCN power state. The calls do not validate all
physical effects, and the snapshot does not prove VCN's VCPU can execute.
The direct live `CC_UVD_HARVESTING=3` and failed ring remain the stronger
operational evidence. A fresh read-only gate/fabric measurement should
precede any speculative power or BIOS patch.

**Same-boot fabric readout 2026-09-28:** On diagnostic boot
`5eeba018-0e66-43c9-81a9-dbcdd927b49d`, after the failed VCN probe,
the [guarded read-only probe](../tools/vcn-psp-diagnostics/read_fabric_gate.py)
read root-SMN `0x50d6c=0x000000f0` and `0x511b4=0xffffffff`. The probe
wrote the PCI SMN index selector only; it did not write either target. These
values agree with older fabric observations. The captured enabled SMU
feature 11 is `G6_SSC`, not VCN power. They support investigating an upstream fabric
enable or routing decision. They do not show when either value was latched,
prove that `0x50d6c` is the physical fuse source, establish that the BC250
SMU uses the same `0x50d6c` interpretation reported for Van Gogh, or by
themselves explain every VCN register. The earlier `SEC_GASKET` omission did
not change the operational harvest bits. The next discriminating work is to
identify the specific boot-stage producer of the fabric/harvest state before
modifying another signed component.
A byte scan of the 299 extracted UEFI PE/TE sections found no direct
little-endian 32-bit literal for `0x50d6c` or `0x511b4`. This excludes only
those exact encodings in the extracted sections; a computed address, another
firmware component, or hardware-derived state remains possible.

**Update 2026-09-28, original PSP video-control write omitted:** The signed
BC250 driver requests `0x1f820 <- 0x185103` during type-13 TMR setup. A
RAM-only interposer replaced only its `SVC #0x7c` instruction with
`movs r0, #0`, preserving the existing success check and all other startup
instructions. Eight offline startup cases confirmed that the request was
absent while TMR allocation still returned normally; 25 post-load cases
passed. A byte comparison with the previous profile found only that
instruction, its body hash and new RSA-PSS signatures changed. The Pico
verified all **1,406/1,406** substitutions over two boot passes with no
fault or routing mismatch. On the fresh diagnostic boot, the actual powered
host-MMIO `CC_UVD_HARVESTING` still read **`3`**, the PSP VCN firmware load
returned `ret=0, status=0`, and VCPU status stayed at the driver's `4`
through ten waits. The decode ring again timed out `-110`; no frame decoded.
This excludes that one native service write as a sufficient explanation for
the operational disable value in this profile. It does not locate the earlier
source, prove a physical fuse, or establish whether `0x1f820` is itself a
VCN register. The BIOS's separate signed `SEC_GASKET` section `0x201`
contains the **same** tuple at ROM `0x983068`; the trial did not change that
policy record or prove whether it was applied on this boot. The pinned
Cezanne and Renoir policies contain the same tuple, so it is not unique to
BC250. The [RAM-only generator](../tools/pico2-interposer/prepare_video_driver_trial.py)
and [startup model](../tools/pico2-interposer/test_video_tmr_trial.py) define
the trial. Private artifacts are ignored under
`output/pico2/driver-video-skip-native-control-20260928/`; archived journal
and dmesg are `output/video-decode-20260922/results/late-vcn-skip-native-control-v01-20260928.*`.
Boot `960c4549-0a87-475f-8952-297b3eedff7f` remains reachable in
diagnostic mode, GPU unbound, `/boot` read-only and the unused one-time GRUB
entry removed. Neither BIOS EEPROM nor Pico flash was written.

**Update 2026-09-28, powered VCN free counter stayed zero:** A second guarded
module sampled `UVD_FREE_COUNTER_REG` twice 100 µs apart with the VCPU
clock-enable bit set, once after clearing that bit, and once after restoring
it. All four reads were `0`. The adjacent `UVD_VCPU_CNTL.CLK_EN` readbacks
again followed the requested clear/restore, PSP firmware load returned
`ret=0, status=0`, and the GPU did not bind. A zero counter is consistent
with a clock or reset gate remaining active, but the available register
definition does not say what enables this counter, so it is not a direct
clock-frequency measurement. The pinned
[generator](../tools/vcn-psp-diagnostics/prepare_vcn_free_counter.py),
[build](../tools/vcn-psp-diagnostics/build_vcn_free_counter.sh) and
[runner](../tools/vcn-psp-diagnostics/run_late_vcn_free_counter.py)
produced module SHA256 `e30611052a25aacab1007751008dea3f58d68d1f2a6a042a5fc88d0919e140ce`.
The ignored journal and dmesg are
`output/video-decode-20260922/results/late-vcn-free-counter-v01-20260928.*`.
The Pico verified 8,412/8,412 substitutions across twelve boot passes with
zero faults, routing mismatches, late decisions and RX stalls. BC250 boot
`aebc9067-eec3-4503-8bb2-c0a8cdaa9f73` remains reachable in diagnostic
mode, GPU unbound, `/boot` read-only and one-time recovery armed. Neither
flash device was written; no decoded frame exists.

**Update 2026-09-28, VCPU clock control is writable but VCN still does not
start:** A one-shot module briefly cleared only `UVD_VCPU_CNTL.CLK_EN` before
Linux's VCPU reset-release step, then restored the original word before
normal startup. Its guard required the previously measured power state, version,
harvest value and VCPU control word. Host-MMIO readback followed the writes
exactly: `0x0ff20200 → 0x0ff20000 → 0x0ff20200`. The PSP's postpower VCN
firmware load again returned `ret=0, status=0`; cache and reset readbacks
remained all ones, `CC_UVD_HARVESTING` remained `3`, `UVD_STATUS` remained the
driver's own `4` through ten waits, and the GPU did not bind. This rules out
a blanket inability to write the powered VCN register aperture, but it does
not show that the VCPU clock actually oscillated or that the reset/cache
registers are writable. The pinned
[generator](../tools/vcn-psp-diagnostics/prepare_vcn_vcpu_clock_readback.py),
[build](../tools/vcn-psp-diagnostics/build_vcn_vcpu_clock_readback.sh) and
[runner](../tools/vcn-psp-diagnostics/run_late_vcn_vcpu_clock_readback.py)
produced module SHA256 `b6c8537678811f744711f3b2a12e374a91dd9d56f9f1d8cd4ca01b94a35b809a`.
The ignored journal and dmesg are
`output/video-decode-20260922/results/late-vcn-vcpu-clock-readback-v01-20260928.*`.
The Pico verified 7,010/7,010 substitutions across ten boot passes, with
zero faults, routing mismatches, late decisions and RX stalls. BC250 boot
`dcd5b84c-c9b2-4cf6-8829-14a0551275b1` is reachable in diagnostic mode,
GPU unbound, `/boot` read-only and one-time recovery armed. Neither BIOS
EEPROM nor Pico flash was written; no decoded frame exists.

The public claim that BC250 users tried `SetSoftMaxVcn 0x4c` and
`SetSoftMinVcn 0x4d` does not identify the command queue or PMFW version.
On this board's [BC250 Q3 API](../output/video-decode-20260922/sources/bc250-smu-unlock/bc250_smu/api_q3.py),
Q3 `0x4c` is GFX droop calibration and Q3 `0x4d` is a CPU VID offset. The
[SMU 11.8 Q0 header](../output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_8_ppsmc.h)
has no VCN clock messages and ends at message count `0x3e`. The reported
partial decode lacks an independently reproducible command trace in the
material reviewed here, so those numbers are not a safe BC250 trial as
written. The next work should establish an exact queue, handler and argument
layout, or identify an earlier control for the live harvest bits.

**Update 2026-09-28, powered direct-buffer load also fails to start VCPU:**
A third one-shot module copied the pinned `navi10_vcn.bin` payload into the
ordinary VCN GPU buffer and selected Linux's direct firmware path instead of
the PSP TMR VCN mapping. This differs from the older direct-load trial: the
current host power sequence reached `UVD_VERSION=0x0002001b` and
`PGFSM_STATUS=0`, and guarded direct VCPU/LMI reset writes were used.
The firmware buffer was at `0x000000f41fc00000`; the firmware file was
405,952 bytes, including its header and payload.
`CC_UVD_HARVESTING` still read `3`, `UVD_STATUS` stayed `4` through ten waits,
and the GPU did not bind. Thus neither the protected TMR mapping alone nor
the read-modify-write reset alone explains the failure. The
value `4` is the driver's own `UVD_STATUS__UVD_BUSY` write before VCPU
release; the driver waits for bit 1 (`UVD_STATUS__IDLE`) and never sees it.
It is not an observed VCPU progress code. The
[generator](../tools/vcn-psp-diagnostics/prepare_vcn_direct_bo_powered.py),
[build script](../tools/vcn-psp-diagnostics/build_vcn_direct_bo_powered.sh)
and [runner](../tools/vcn-psp-diagnostics/run_late_vcn_direct_bo_powered.py)
pin module SHA256 `70aacb396d26ef0651f7d42468a4a413da82cd0cdd400c7d970d02b5dabba580`.
Journal and dmesg are in ignored
`output/video-decode-20260922/results/late-vcn-direct-bo-powered-v01-20260928.*`.
Pico verified 5,608/5,608 substitutions in eight boot passes with fault,
routing mismatch, late-decision and RX-stall counts zero. BC250 boot
`03c443f2-4ea5-4d25-8f13-24fb1a9b87fc` is reachable in diagnostic mode,
GPU unbound, `/boot` read-only and one-time recovery armed. No BIOS EEPROM
or Pico flash write occurred, and there is still no decoded frame.

**Update 2026-09-28, powered register file opens but direct reset does not
start the VCPU:** A read-only, hash-pinned Fedora module sampled `UVD_VERSION`
around the successful PSP VCN firmware load. Before the Linux VCN power
sequence, `power=0x801`, `pgfsm=0x00200000`, and `version=0xdeadbeef`.
With `power=0x800` and `pgfsm=0`, the same host-MMIO register read
**`0x0002001b`** before VCPU release, and kept that value afterward.
`CC_UVD_HARVESTING` read `3` in both powered samples; the second PSP
`LOAD_IP_FW` returned `ret=0, status=0`, while `UVD_STATUS` stayed `4`.
This confirms that at least the VCN version register becomes accessible; it
does not establish that the VCPU, firmware cache, or decoder engines are
operational. The archived read-only [generator](../tools/vcn-psp-diagnostics/prepare_vcn_version_probe.py)
and [runner](../tools/vcn-psp-diagnostics/run_late_vcn_version_probe.py)
produced module SHA256 `20558568255b9905b642afc798339ad49f4a4913b7886619cf2182f89b115aea`.
The journal and dmesg are under ignored
`output/video-decode-20260922/results/late-vcn-version-probe-v01-20260928.*`.

Because `UVD_SOFT_RESET` reads `0xffffffff`, Linux's ordinary
read-modify-write release could propagate all those read bits into the
reset write. A second guarded, one-shot module therefore asserted only
`VCPU_SOFT_RESET`, then wrote zero directly, after the successful PSP load;
it also used direct zero for the later LMI reset release and VCPU retries.
The direct writes did **not** start the VCPU: reset readback remained
`0xffffffff`, status remained `4` through the waits, and the GPU did not
bind. The readback alone cannot distinguish a write-only register from an
ignored write, but a changed ring outcome did not occur. The
[generator](../tools/vcn-psp-diagnostics/prepare_vcn_direct_reset_after_psp.py)
and [runner](../tools/vcn-psp-diagnostics/run_late_vcn_direct_reset_after_psp.py)
produced module SHA256 `c3f6885a54912a26bc7a7eccf747dea83d07a5c118cbf06f8937ffb0ea52e9a2`;
evidence is in ignored
`output/video-decode-20260922/results/late-vcn-direct-reset-after-psp-v01-20260928.*`.
Pico verified 4,206/4,206 guarded substitutions across six boot passes,
with zero faults and routing mismatches. BC250 boot
`e6b63b22-cde6-4aef-b913-1a58215ea19b` remains reachable in diagnostic
mode, GPU unbound, `/boot` read-only and one-time recovery armed. Neither
the BIOS EEPROM nor the Pico flash was written. No decoded frame exists.
The next question is how the live `CC_UVD_HARVESTING=3` state is established
or locked before the first VCN firmware request. The version read rules out
a wholly inaccessible register aperture; it does not identify an override
or prove physical fuse provenance.

**Update 2026-09-28, powered host write did not clear harvest:** The
hash-pinned, one-shot amdgpu diagnostic checked the exact prior VCN/TMR
allocations, then required `UVD_POWER_STATUS=0x800`, `UVD_PGFSM_STATUS=0`,
and `CC_UVD_HARVESTING=3` before issuing a single host PCI-MMIO write of
zero to that register. Its immediate readback remained **`3`**:
`power=00000800 pgfsm=00000000 before=00000003 after=00000003`.
The VCN decode ring still timed out (`-110`), the GPU did not bind and no
frame was decoded. In this particular run, a later diagnostic PSP reload
returned `0x70000001`, so its ring timeout alone does not isolate the
harvest write; an older clean run with successful postpower and postrelease
PSP loads independently left `UVD_STATUS=4`. The unchanged harvest readback
closes the ordinary powered host-MMIO write path
as an effective runtime override, complementing the earlier PSP-side
write/readback. It does **not** prove a physical eFuse: a read-only register,
an earlier locked shadow or immediate hardware restoration would look the
same. The first VCN firmware request already read `3`, so any supported
override would need evidence for an earlier control or a different register.
The [source generator](../tools/vcn-psp-diagnostics/prepare_vcn_harvest_write.py)
and [pinned runner](../tools/vcn-psp-diagnostics/run_late_vcn_harvest_write.py)
produced module SHA256 `8ff186ee1f75c41850f7bb657ba2cd8cf0561e9b83a6fdf00c24254f22869c9a`.
Raw mode-0600 dmesg and journal are in ignored
`output/video-decode-20260922/results/late-vcn-harvest-write-v01-20260928.*`.
Pico verified 3,690/3,690 substitutions, fault and routing mismatch zero.
BC250 remains reachable on diagnostic boot
`402e7717-62b4-4a4b-8786-e4a7408e3754`, GPU unbound, `/boot` read-only,
unused recovery entry removed. No BIOS EEPROM or Pico flash write occurred.

**Update 2026-09-28, direct host-MMIO harvest confirmed:** A one-shot,
default-off amdgpu diagnostic read the actual `mmCC_UVD_HARVESTING` register
through `RREG32_SOC15(VCN, 0, ...)` after the adjacent power and PGFSM
registers responded. In the same boot it logged
`power=0x00000800 pgfsm=0x00000000 harvest=0x00000003`. Thus the VCN 2.0
hardware register itself asserts both `MMSCH_DISABLE` and `UVD_DISABLE`, and
the earlier PSP-side `3` was not merely an unrelated same-numbered SMN word.
The pinned module was built from
[the guarded source generator](../tools/vcn-psp-diagnostics/prepare_vcn_harvest_mmio.py)
(module SHA256 `c835b22df299c94c0357a564dc79b54e68ccd50e483c832da83c267acf3e7b18`).
The Pico verified 2,460/2,460 substitutions across two boots with zero faults
and mismatches; the BC250 remained reachable on diagnostic boot
`5702bead-bfb3-467f-b85c-c958e5942912`. The exact host line and neighboring
registers are archived in ignored
`output/video-decode-20260922/results/late-vcn-harvest-mmio-v01-20260928.dmesg`;
the runner journal is beside it. The probe still ended at `UVD_STATUS=4`,
the GPU did not bind, and no frame was decoded. `/boot` is read-only and the
unused one-time recovery entry was removed. Neither the BIOS EEPROM nor Pico
flash was written. The read proves the **operational disable state**, not
whether its source is a physical fuse or an earlier latched/locked setting.
Any further VCN work must identify that source or a supported override;
repeating firmware cache and reset sequences while `UVD_DISABLE` is asserted
has no clear path to decoding.

The pinned Fedora 7.2.5 source only **reads** `CC_UVD_HARVESTING`: its VCN
2.5 and JPEG 2.5/3.0 paths treat `UVD_DISABLE` as a harvested block. No
driver write to this register was found. The VCN 2.0 path used by the opt-in
BC250 trial does not check this live register before trying to start the
ring, which explains why discovery `harvest=0` let the trial proceed despite
the hardware value. This is a source-derived explanation of the software
behavior, not proof of a physical fuse or a complete causal proof for the
ring timeout. PSP and now powered host writes both left immediate readback at
`3`, so neither measured path is an effective runtime override. See the
upstream [VCN 2.5 harvest check](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/vcn_v2_5.c)
and [VCN 2.0 register bits](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/asic_reg/vcn/vcn_2_0_0_sh_mask.h).
An offline scan of all 299 previously extracted UEFI PE/TE sections found
no little-endian 32-bit literal `0x0001f81c` or `0x0101f81c`. That narrow
negative result cannot exclude a computed address, a compressed or
unextracted module, or a different early firmware component.

**Address-space qualification 2026-09-28:** The signed Trusted OS sends PSP
service `0x7b` through a page-selected SMN aperture. Offline execution of its
pinned instructions maps argument `0x1f81c` to PSP address `0x0101f81c`.
The [Linux VCN 2.0 register table](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/asic_reg/vcn/vcn_2_0_0_offset.h)
defines `CC_UVD_HARVESTING` at PCI GPU MMIO byte offset
`(0x7e00 + 7) * 4 = 0x1f81c`. These are different access paths, so the
matching number alone cannot identify the target. Crucially, archived
same-boot data *does* support an alias for several VCN registers: PSP reads
of `UVD_VCPU_CNTL` at `0x20160`, `UVD_LMI_CTRL2` at `0x1fff4`, and
`UVD_LMI_STATUS` at its numeric offset matched host MMIO values
`0x0ff20200`, `0x003e0010`, and `0x007c337f` respectively. The evidence is in
`output/video-decode-20260922/results/late-vcn-postrelease-{vcpu-cntl,lmi-ctrl2,lmi-status}-v01-20260927.jsonl`.
The `0x1f81c → 3` PSP result is now independently corroborated by the direct
host-MMIO read above. The signed PSP driver also writes SMN `0x1f820` and
`0x1f8a4`; those offsets are unnamed gaps in the public VCN header, which
does not settle their hardware identity. The ignored write-zero result does
not establish physical fuse provenance. The separate host-MMIO all-ones
readings for inaccessible VCN windows and the failed decode-ring test stand.
The [read-only, pinned SVC execution](../tools/vcn-psp-diagnostics/verify_svc7b_address_space.py)
reproduces the PSP mapping without touching the board. The remaining decisive
question is the origin of the live disable bits, rather than whether they
are present in VCN MMIO.

**Update 2026-09-28, PSP-driver startup probe stopped at the service boundary:**
A signed, RAM-only Thumb hook ran the original PSP-driver initializer, called
service `0x7b` for `CC_UVD_HARVESTING`, and attempted to encode the result in
flash-read addresses. The Pico verified all 658 substitutions across two
passes with fault `0` and routing mismatches `0`, but the BC250 did not reach
Fedora SSH. The first four retained flash reads were normal sequential
firmware traffic, so they did not contain a valid service result. A locally
tested marker-and-filter variant would distinguish the hook's reads, but it
was **not** run: the unmarked hook disrupted startup and repeating the same
service call would not be a useful fix. The board recovered with the known-good
Pico CS pass-through and one authorized cold cycle. Current diagnostic boot is
`a09bb1ff-8e95-4733-a26e-6ec61d1a0ffd`, `/boot` read-only, PDU outlet on,
Pico in CS-PASS v2. No BIOS EEPROM or Pico flash write occurred. The earliest
valid SMN measurement at numeric address `0x1f81c` remains `0x3` at the
first VCN firmware request; no decoded frame has been produced.

**Update 2026-09-27, PSP bootloader readout and early SVC limit:** A signed,
RAM-only Pico interposer first ran a no-op Trusted OS detour at payload offset
zero and booted Fedora with fault `0`, mismatches `0`, and every substituted
SPI word verified. A second detour called PSP service `0x7b` to read
`CC_UVD_HARVESTING` before the Trusted OS overwrites the prior bootloader.
Four flash-read addresses encoded the service result: status **`9`**, sample
`0`. The service returned but did not complete a valid read at this early
point. The sample cannot be interpreted as a zero register value, and this
does not contradict the later, successful SMN read of `0x3` at the first VCN
firmware request. At the time, neither result had a verified VCN MMIO identity;
the direct host-MMIO read above later confirmed `CC_UVD_HARVESTING=3`. Both early
guarded trials that required status `0` failed for this reason. The Pico had
no routing fault; the unguarded trace booted Fedora normally.

Using the [Positive Technologies BC250 method](https://habr.com/ru/companies/pt/articles/979470/),
six further RAM-only cold boots emitted 16-bit words of the decrypted PSP IPL
as read addresses in the original BIOS flash's `0xC00000` region. The Pico
captured and reconstructed the complete `0xA800`-byte range at
`output/pico2/tos-entry-ipl-slice-20260927/decrypted-ipl-0000-a7ff.bin`
(SHA256 `2fe1046cb0ac338d86176bf59e8fdabd574954d1df5892fd8c674e40a2309141`).
All six reads had Pico fault `0`, mismatches `0`, complete substitutions,
and a subsequent Fedora boot. The first bytes form a plausible ARM exception
vector table. The dump does **not** contain a direct little-endian
`0x0001f81c` or 16-bit `0xf81c` constant. This absence does not identify the
source of the now host-confirmed VCN harvest bits.
A read-only Ghidra ARMv7 import identified 363 functions; its private
decompile is at `output/pico2/tos-entry-ipl-slice-20260927/ipl-decompile.txt`.
A text search of those functions found no direct VCN harvest address. The
PSP driver has separately been observed reading cold-reset word
`0x0900c004` as `1` after power-up, so merely writing that expected value
is not yet a demonstrated fix for this board.
The binary and address traces are Git-ignored and mode `0600` locally.
No BIOS EEPROM or Pico flash was written. The BC250 is currently on diagnostic
boot `1b672920-7490-4d23-8064-65188bdb1f57`, `/boot` read-only, GPU unbound;
the Pico retains the last RAM-only slice profile with fault `0` and routing
mismatches `0`. Hardware decoding remains unverified. The next useful step
is to identify the source or lock mechanism for the live `0x3` harvest value
before another VCN power or cache-map write. The firmware discovery table's
`harvest=0` still conflicts with that live register value.

**Update 2026-09-27, disable state predates host VCN initialization:** Three
more RAM-only Pico trials moved the `CC_UVD_HARVESTING` read to the *first*
VCN `LOAD_IP_FW` request. It was already **`0x3`**, before Linux's VCN power,
cache-map and reset sequence. A guarded PSP write of zero at that same early
point returned success, but immediate readback was still **`0x3`**. A final
control removed the experimental client-12 RSMU and gasket-policy writes and
read the register directly on the first request; it also returned **`0x3`**.
All three Pico profiles reported fault `0` and routing mismatches `0`.
The diagnostic `0x70000003` PSP status intentionally failed that VCN
firmware load, so these runs are register measurements, not successful decode
attempts. Their kernel logs and journals are archived as
`output/video-decode-20260922/results/early-vcn-harvest-{read,clear,no-policy}-v01-20260927.*`.
This excludes the tested host VCN startup sequence and experimental client-12
policy as sources of the disable value. The value behaves like a fixed or
earlier latched hardware harvest state, although the actual fuse source has
not been independently read. Hardware decode remains unverified. The BC250
is on diagnostic boot `5a532ddc-2ea9-4065-b6a9-69016e5f6d92`, GPU unbound,
with one-time recovery armed. No BIOS EEPROM or Pico flash write occurred.
Further VCN work needs evidence for a supported pre-boot harvest override;
additional firmware-cache or VCPU reset writes cannot overcome the measured
`UVD_DISABLE` bit.

An offline source check found no VCN-harvest override in the Linux
`cyan_skillfish` SMU11 driver or the VCN 2.0 startup path. The older
`CC_HARVEST_FUSES` register definition belongs to SMU 7.1 hardware and is
not a verified BC250 register; do not probe its address on this board. A
literal little-endian `0x1f81c` address was absent from the clean 16 MiB BIOS
backup, which is inconclusive for compressed firmware or indirect accesses.
None of these checks independently identifies the physical fuse source.

**Update 2026-09-27, live VCN harvesting state:** A fault-free RAM-only Pico
profile read `CC_UVD_HARVESTING` at PSP byte address `0x1f81c` after host
initialization. It returned **`0x00000003`**. The VCN 2.0 register definition
names bit 0 `MMSCH_DISABLE` and bit 1 `UVD_DISABLE`, so both disable bits are
asserted ([Linux register definition](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/asic_reg/vcn/vcn_2_0_0_sh_mask.h)).
The hardware-IP discovery table's earlier `harvest=0` does not describe this
live state. A second, separately cold-booted profile required the initial
value to equal `3`, issued PSP service `0x7c` to write zero, then immediately
read the same register via service `0x7b`. The service accepted the write,
but readback was still **`3`**. Both runs had Pico fault and routing-mismatch
counters at zero. They ended with `UVD_STATUS=0x4`, GPU unbound, and no
decoded frame. The unchanged readback means a runtime PSP register write
cannot clear the disable bits at this point; it does not by itself prove
whether they are physical fuses or an earlier locked platform setting.
Linux treats this bit as a harvested VCN instance on other VCN generations
([VCN 2.5 driver](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/vcn_v2_5.c)).
Journals: `output/video-decode-20260922/results/late-vcn-postrelease-uvd-harvest-v01-20260927.jsonl`
and `late-vcn-postrelease-uvd-harvest-clear-v01-20260927.jsonl` in the same
directory. The BC250 is on diagnostic boot
`4569661f-9f7e-4aea-a3c0-ef5770b00ef1`, GPU unbound, with one-time recovery
armed. There was no BIOS EEPROM or Pico flash write. Further VCN startup
attempts should first establish where this harvested state originates and
whether an earlier supported override exists; repeating cache/reset writes
while `UVD_DISABLE` remains set is unlikely to produce a decoded frame.

**Update 2026-09-27, PSP-visible clock and memory controls:** Six further
RAM-only Pico trials read the powered VCN after host initialization. The PSP
reported `UVD_CGC_GATE=0x00100000` (VCPU gate clear),
`UVD_CGC_CTRL=0x0000018c` (VCPU mode and dynamic-clock bits clear), and
`UVD_LMI_VM_CTRL=0x00000000` (VCPU virtual-memory translation disabled).
After replaying the verified cache map and releasing the real UVD reset,
`UVD_LMI_STATUS=0x007c337f`, matching the earlier host reading, while
`UVD_CGC_STATUS=0xffffffff` was not a reliable clock-state indication.
A PSP-side write to set `UVD_VCPU_CNTL.TRCE_EN` returned success but the
immediate PSP readback remained `0x0ff20200`: the trace bit did not latch
or was cleared immediately. Consequently a zero VCPU PC trace cannot prove
the CPU never fetched firmware. Every trial still ended at `UVD_STATUS=0x4`
with the GPU unbound; there is no decoded frame. The journals are
`output/video-decode-20260922/results/late-vcn-postrelease-{cgc-gate,cgc-ctrl,cgc-status,lmi-status,lmi-vm-ctrl,vcpu-trace}-v01-20260927.jsonl`.
These archived journals call the low 28 diagnostic bits `soft_reset_low28`
even when measuring another register; the runner now uses
`psp_diagnostic_low28` for future results. The BC250 is on diagnostic boot
`49f4995b-914b-4e1b-aabc-05cb1132567d`, with the GPU unbound and the
one-time recovery entry armed. No BIOS EEPROM or Pico flash write occurred.

**Correction and update 2026-09-27, actual VCN reset and clock state:** The
PSP address `0x1f8a4` used by earlier signed-driver diagnostics is **not**
Linux's `UVD_SOFT_RESET`. For this VCN 2.0 instance the latter is PSP byte
address `0x20180` (segment-1 base `0x7e00`, register offset `0x260`, then
multiply by four). An early PSP read after Linux's reset-release writes
returned `0x00080008`: VCPU reset bit 3 and VCPU clock-reset status bit 19
were still set. A later guarded PSP-side write of zero to `0x20180` returned
success and read back **`0x00000000`**, but the VCPU still reported
`UVD_STATUS=0x4` through ten waits; the GPU did not bind. A separate PSP read
after the host's VCPU clock-enable write returned `UVD_VCPU_CNTL=0x0ff20200`,
matching the host value with `CLK_EN` set. Thus the clock-enable bit reached
the hardware and PSP-side reset release succeeded, but neither started the
firmware. The subsequent clock-gating reads are recorded above. Journals:
`output/video-decode-20260922/results/`
`late-vcn-postrelease-measure-uvd-v01-20260927.jsonl`,
`late-vcn-postrelease-after-uvd-write-v01-20260927.jsonl`, and
`late-vcn-postrelease-vcpu-cntl-v01-20260927.jsonl`. One more PSP read of
`UVD_LMI_CTRL2` at `0x1fff4` returned `0x003e0010`, also matching the host
value, with `STALL_ARB` and `STALL_ARB_UMC` clear. See
`late-vcn-postrelease-lmi-ctrl2-v01-20260927.jsonl` in the same directory.
All profiles used Pico SRAM, with no BIOS EEPROM or Pico flash write. There
is no decoded frame yet.
The earlier reset interpretation below is superseded by this address
correction.

**Update 2026-09-27, postrelease VCPU and reset trials:** With the 16
cache-window words programmed and verified through the PSP, a pinned kernel
module sampled `UVD_VCPU_TRCE`, `UVD_PF_STATUS` and `UVD_LMI_LAT_CNTR` at
release and one second later. Both samples were `pc=0`, `pf=0`,
`latency=0x0000ff00`; status remained `0x4` and the GPU did not bind. Since
the trace-enable bit did not latch in an earlier trial, PC zero alone does
not prove that the VCPU never ran. Another guarded module made a third PSP
firmware-load request after the host's VCPU/LMI reset-release writes. The
signed driver reapplied the same cache map and cleared reset through PSP
service `0x7c`; the request returned success (`ret=0`, PSP status `0`), but
status again remained `0x4` through ten waits with unchanged PC/fault/latency
samples. A preceding PSP-side reset-clear/readback trial also returned
success. The next useful distinction is the PSP-visible `UVD_SOFT_RESET`
value **after** the host's read-modify-write sequence and before another PSP
write, or an equivalent VCPU execution/isolation signal. Host MMIO reads of
the reset/cache registers continue to return `0xffffffff` and should not be
used as evidence of their hardware values. Journals:
`output/video-decode-20260922/results/late-vcn-map-rx-reset-release-v01-20260927.jsonl`,
`late-vcn-map-exec-trace-v01-20260927.jsonl` and
`late-vcn-postrelease-reload-v01-20260927.jsonl` in the same directory. The
BC250 remains on diagnostic boot `eecd48b5-dec9-4ea1-a73e-56f006d691ba`,
GPU unbound, one-time recovery armed and `/boot` read-only. All trials used
Pico SRAM; no BIOS EEPROM or Pico flash write. No hardware-decoded frame yet.

**Update 2026-09-27, powered VCN map verified:** The Pico USB connection was
restored. An inline one-word control and a one-word table moved to the signed
driver's executable region both returned `0x6d000001` after writing and
reading back the firmware-cache BAR low word. The same table location then
completed all 17 PSP service writes with response status `0`, but the VCPU
remained at `UVD_STATUS=0x4` through ten one-second waits and the GPU failed
to bind. A follow-up loop read all 16 firmware, stack, context and shared
cache-window words back through the PSP; every value matched. The 17th
readback, `UVD_GFX10_ADDR_CONFIG`, was `0x00100004` after writing
`0x00100044`. The VCN 2.0 register mask excludes bit `0x40`, so this is
expected masking of an unsupported graphics field, not a cache-window
failure. The host continues to read the cache and soft-reset registers as
`0xffffffff`. These results move the remaining fault past cache-window
programming, toward VCPU reset/firmware execution or another memory-interface
prerequisite. All live profiles were RAM-only; no BIOS EEPROM or Pico flash
was written. There is still no hardware-decoded frame. Full journals are in
`output/video-decode-20260922/results/late-vcn-map-*.jsonl`.

The Pi 5 SSH and sudo credentials supplied by the user are retained in a
mode-`0600`, Git-ignored local file at
`output/pi5-recovery-20260924/pi-credentials.txt`.

**Update 2026-09-27, full PSP-side VCN map attempt:** A pinned kernel module
logged VCN allocations (`bo=0xf41fd00000`, shared=`0xf41fda0000`, cache0
size=`0x64000`) and refused a second PSP firmware-load request unless those
addresses, the TMR firmware address `0xf41fa00000`, firmware length and tiling
configuration matched. They did match on the live trial. A RAM-only signed
driver hook then attempted a 17-entry PSP write table for firmware, stack,
context and shared-memory windows after all PGFSM tiles powered. PSP command
submission timed out after about two seconds (`ret=-22`, response status
still `0`), with no VCPU start. A one-entry prefix using that table timed out
the same way; the previously proven inline write to the same cache BAR had
returned normally. This narrows the new failure to the table-based hook or
table access, rather than a later register entry. Pico substitutions were
verified with no fault or routing mismatch. A one-entry inline control and
an alternative table in the driver's executable region are built and pass
native PSP instruction tests, but have **not** been tried live: after loading
the inline control into Pico RAM, its USB serial interface did not reappear
on the Pi. The BC250 remains **powered off** until the Pico USB cable is
reconnected and the profile can be armed and verified. No EEPROM or Pico
flash write was made; no hardware-decoded frame yet.

**Pico USB recovery check:** The Pi kernel saw the Pico enter RP2350 BOOTSEL
at 19:29:23 and disconnect at 19:29:24 when the inline-control UF2 was
started, but it recorded no subsequent application USB enumeration. The Pi
currently lists only its four root hubs; `vcgencmd get_throttled` is `0x0`.
The inline-control UF2 has valid UF2 block headers, a contiguous SRAM image
at `0x20000000`–`0x2000baff`, and the same RISC-V/Pico 2 image metadata as
the last working readback UF2. These checks rule out a malformed UF2 wrapper
or Pi undervoltage indication; they cannot distinguish a Pico runtime fault
from a USB connection/power fault. The Pico must enumerate again before a
RAM-only trial can be armed, and the BC250 remains off in the meantime.

**Update 2026-09-27, host PCI SMN access caution:** A host-side read via the
root PCI config SMN window returned expected domain-6 control/status values,
then stalled on VCN `UVD_POWER_STATUS` at `0x1f810`. The BC250 stopped
responding to SSH while the PDU stayed on and the Pico reported no fault.
The authorized outlet-8 cold cycle restored diagnostic boot
`1e110c30-a177-4251-ae4c-742fb1685777`; its consumed recovery entry was
cleaned. Do not retry host PCI SMN reads of VCN addresses. The PSP service
path remains the measured route for powered VCN cache-register access.

**Update 2026-09-27, PSP access to powered VCN cache registers:** Three
RAM-only Pico profiles distinguished the signed PSP driver's first VCN
firmware load from a later load using its `UVD_POWER_STATUS` read (`0x801`
before tile power-up, `0x800` afterward). With all PGFSM tiles reporting on,
the PSP read the full-address cold-reset word `0x0900c004` as `0x00000001`.
It read the VCN firmware-cache BAR low word at `0x2107c` as `0x00000000`
both before and after the host ran `vcn_v2_0_mc_resume()`, although the host
read the cache BAR, size, offset, stack BAR and soft-reset registers as
`0xffffffff`. A final trial issued PSP service `0x7c` to write the expected
firmware-address low word `0x1fa00000` to `0x2107c` after host programming;
PSP service `0x7b` immediately read back `0x1fa00000` (encoded as PSP status
`0x7fa00000`). Thus the powered PSP path can read and write that cache BAR
word, while the host's cache programming did not leave its expected value
visible through the PSP path. This does not yet prove which host access route
is wrong or that the other VCN registers behave the same way. The diagnostic
PSP status deliberately aborted GPU probe, so no decoded frame was attempted.
All three profiles passed native PSP instruction tests; the Pico reported
fault=0 and routing mismatches=0. The board is on diagnostic boot
`55b9f6ec-2d67-43bd-83a8-3c8ab2352610`, GPU unbound, one-time recovery
armed and `/boot` read-only. Neither BIOS EEPROM nor Pico flash was written.
The next focused trial is to mirror the remaining cache, stack, context and
non-cache windows through the PSP route with values derived from the kernel's
live VCN allocation, then release the VCPU and check for a decoded frame.

**Update 2026-09-27, post-power firmware reload:** A pinned diagnostic
amdgpu module powered UVDW so `UVD_PGFSM_STATUS=0`, then submitted one more
`LOAD_IP_FW` for the same staged VCN image before programming the VCPU memory
controller. The PSP returned success (`ret=0`, status `0`) and the same TMR
firmware address `0xf41fa00000`. Before and after that request, the VCN
firmware-cache BAR low read `0xffffffff` and `UVD_SOFT_RESET` read
`0xffffffff`; the later BAR, size and offset readbacks also stayed all ones.
VCPU status remained `0x4` across ten waits and GPU probe failed. The Pico
verified 4,456/4,456 substitutions over eight boot passes, fault and routing
mismatch zero. A separate offline execution of the pinned PSP driver's
post-load function shows that an already-set type-13 loaded flag does not
skip its two reset SVC `0x7c` requests for context `0xffff`; this does not
prove the whole second live request reached that function or that the reset
stores reached hardware. The board remains on diagnostic boot
`fa1071e9-44ca-40b6-b398-16b0d82ba36a`, GPU unbound, one-time recovery
armed, `/boot` read-only. No EEPROM or Pico flash write and no desktop
restore. A simple ordering fix (reload after tile power) is therefore
insufficient; focus on the remaining isolation/access path.

**Update 2026-09-27, PSP driver-slot table audit:** The suspected 32-slot
`0x5244` table is built in PSP RAM as drivers load; it is not a fixed VCN
power-gate table at BIOS offset `0x286000`. In the pinned TOS decompilation,
`FUN_00011840` clears `base+0x6000` for `0xa80` bytes (32 slots of `0x54`),
`FUN_00011a04` recognizes the `0x5244` driver-header magic and copies a
driver descriptor into one slot, and `FUN_0000fc50` later walks those slots
and invokes PSP service `0xf2`. The 16 MiB BC250 ROM has one literal
`0x5244` at `0x985014`, the signed `DRIVER_ENTRIES` header; its
`0x286000` region is erased (`0xff`). This rules out patching a purported
31-entry flash table at that offset. It does not establish which runtime
driver slots were registered on this boot, nor whether their VCN operations
ran. The useful next target is the actual registered driver's startup and
isolation operation, not an assumed static ROM table.

**Update 2026-09-27, VCPU PC and fault traces:** A pinned VCN module read
`UVD_VCPU_TRCE`, `UVD_PF_STATUS` and `UVD_LMI_LAT_CNTR` at reset release and
one second later. Both samples were `pc=0`, `pf=0`, `latency=0x0000ff00`;
VCN status stayed `0x4` and the GPU did not bind. A second otherwise identical
module set `UVD_VCPU_CNTL.TRCE_EN` immediately before reset release. The
control register still read `0x0ff20200`, with that bit clear, and both PC
samples and VCN startup were unchanged. The trace-enable write either did not
latch or self-cleared, so PC zero cannot by itself prove that the VCPU never
executed. The unchanged latency value is consistent with no observed memory
traffic but has no board-specific baseline under a known working VCPU. The
Pico verified 3,342/3,342 substitutions over six boot passes, fault and
routing mismatch zero. The board remains on diagnostic boot
`b6240602-f5c0-4037-8af0-32a60abba5d0`, GPU unbound, one-time recovery
armed. No flash writes or desktop restore. Investigate the earlier PSP
power/isolation path rather than repeating the same VCPU reset sequence.

**Update 2026-09-27, UVDW power trial:** The previous VCN startup trace had
`UVD_PGFSM_STATUS=0x00200000`. In the VCN 2.0 register definitions, that is
`UVDW_PWR_STATUS=2` while the ten lower tile fields are zero. A pinned
diagnostic module added only `UVDW_PWR_CONFIG=1` to the existing static
power-up sequence and logged the result. On the BC250, it read back
`UVD_PGFSM_CONFIG=0x00155555` and `UVD_PGFSM_STATUS=0x00000000`: this tile
*did* power on. VCN firmware still loaded at `0xf41fa00000`, but VCPU status
remained `0x4` across ten one-second waits and the GPU did not bind. Thus
the one off UVDW tile is not sufficient to start the VCPU. Even with all
PGFSM tile fields reporting on, the firmware-cache BAR, size and offset
register readbacks remained `0xffffffff`. This establishes unusable readbacks
after tile power-up, not whether the cache-register writes reached hardware.
The Pico SRAM profile verified 1,114/1,114 substitutions over two boot passes, with no
routing mismatches or faults. Its first RAM reload failed to enumerate on the
Pi's original USB port; after replugging to another port, the same UF2 loaded,
armed and booted normally. The board remains on diagnostic boot
`ff8378e2-0eee-4773-b60c-165d5a5ec1cb`, GPU unbound, one-time diagnostic
recovery armed. Neither BIOS nor Pico flash was written and the normal desktop
was not restored. No hardware-decoded frame yet.

**Update 2026-09-27, PSP cache-register access:** Two further RAM-only Pico
profiles tested PSP service `0x7b` on the VCN firmware-cache BAR low register
at word address `0x2107c`. The first read, after an intact firmware load but
before host VCN initialization, returned diagnostic status `0x7eadbeef`:
the observed low 28 bits were `0xeadbeef`, matching the host's earlier
`0xdeadbeef` pattern. A second profile issued service `0x7c` to write the
observed TMR address low word `0x1fa00000` to `0x2107c`, then read that same
address. The write service returned zero, but the read still returned
`0x7eadbeef`. Ten offline instruction cases verified the write address/value,
error paths and read order before the live trial. These observations do not
establish whether this cache register is unreadable, the write was discarded,
or a further power/security prerequisite is missing. A third RAM-only control
read `UVD_POWER_STATUS` at word address `0x1f810` through the same PSP service.
It returned low 28 bits `0x801`, matching the host read on that boot. The PSP
read mechanism therefore works for at least one VCN register; the poison
pattern is specific to the cache-register path at this stage. Each profile
verified two fault-free Pico boot passes (1,198/1,198, 1,210/1,210 and
1,198/1,198 substitutions). The board remains on diagnostic boot
`004ff632-efda-4340-baa3-1e3f8718099d`, GPU bound with VCN registration
off, and one-time diagnostic recovery armed. Neither flash device was written;
the normal desktop was not restored. No hardware-decoded frame yet.

**Update 2026-09-27, discovery and VCPU memory-interface trace:** The live
10,240-byte GPU IP-discovery blob (SHA-256
`d56adee33131f7093ffb0af4e32e91052d3ee1577e6ea9c7e60a66a5e4e6e75d`)
reports VCN 2.0.3, revision `0x03`, with harvest `0`; its harvest table is
empty. The optional `VCN_INFO` codec-fuse table is absent, so it supplies no
codec-disable mask. These firmware tables report VCN as present, although a
later live `CC_UVD_HARVESTING` read returned `0x3`, as documented above. The
installed Navi10, Navi12, Navi14,
and Renoir VCN 2.x files contain the same microcode payload; selecting another
of those names cannot change the VCPU code under test.

A locally built diagnostic module read VCN memory-interface state at reset
release and one second later. Both samples were identical:
`LMI_STATUS=0x007c337f`, `LMI_CTRL=0x00307340`,
`LMI_CTRL2=0x003e0010`, `VCPU_CNTL=0x0ff20200`. The VCPU clock-enable bit
was set and the UMC arbitration-stall bit was clear. No MMHUB page fault was
logged, yet VCN status stayed `0x4`, the decode ring timed out, and the GPU
driver did not bind. Thus clock enable and removal of that stall are not
sufficient. A broad read through `amdgpu_regs` on a previous bound diagnostic
boot wedged the board; the authorized PDU cycle returned it to the diagnostic
entry. Avoid that debugfs register path. The current board remains on a
diagnostic boot after the LMI trial, with a one-time diagnostic recovery entry
armed. No desktop restore, BIOS EEPROM write or Pico flash write occurred.

**Update 2026-09-27, client-12 policy and VCN start:** A RAM-only PSP-driver
profile replayed the 51 client-12 `SEC_GASKET` writes that are byte-for-byte
identical in pinned Cezanne and Renoir policies and absent from the BC250
policy. Eight native TMR cases verified write order, allocation-failure skip,
and error propagation. On the BC250, the GPU bound and intact type-13 VCN
firmware loaded at `0xf41fa00000`. Host `UVD_POWER_STATUS` changed from
`0xffffffff` to `0x801`, but `UVD_VERSION` and `UVD_STATUS` read `0xdeadbeef`
before the load. A PSP-side readback of policy descriptor `0x0900c9a0`
returned its programmed low 28 bits, `0x20180`, confirming that descriptor is
visible to the PSP. A PSP-side read at plain address `0x20180` returned low
28 bits `0xeadbeef`; the address namespace and high nibble remain uncertain.

With VCN enabled, the kernel reached `vcn_v2_0_start` but the VCPU never
reported ready: status remained `0x4` through ten retries, the decode ring
timed out with `-110`, and the GPU driver did not bind. A register trace found
the PSP firmware address correct at `0xf41fa00000`, while VCN firmware-cache
address, size and offset register *readbacks* were all `0xffffffff`; the
soft-reset register also read all ones. A BC250-only kernel module that wrote
explicit reset values instead of using those poisoned read-modify-write values
produced the same status and timeout. The reference policy covers the firmware
cache, stack and reset register address ranges, so simply replaying those
descriptors or changing the reset write is insufficient. Next work should
identify whether those register reads are intentionally unavailable, which
power/isolation or harvest state still prevents VCN execution, and whether
the VCPU can actually fetch its code. No decoded frame has been produced.

A direct-VRAM control then skipped the PSP VCN firmware-load path. It placed
firmware in a VRAM buffer at `0xf41fc00000` instead of the PSP TMR address,
but the VCN cache-window readbacks remained all ones and status stayed `0x4`
through ten waits. The ring still timed out with `-110`. Firmware placement
alone does not explain this failure. The remaining investigation is the VCN
block's actual power/isolation/harvest state or inaccessible register fabric,
not another firmware-address adjustment.
The board remains on its diagnostic boot with a one-time diagnostic recovery
entry armed; there was no desktop restore, BIOS EEPROM write or Pico flash
write.

**Update 2026-09-27, service-status and native RSMU trials:** Three successive
RAM-only Pico 2 profiles kept the signed PSP driver and authentic VCN key active
without writing either flash device. A guard on the driver's video-region
control service still allowed intact type-13 firmware to load at
`0xf41fa00000`; an injected nonzero service result takes the original allocator
error path in seven offline instruction cases. The next profile called the
signed driver's own four-store client-12 RSMU initializer during `SETUP_TMR`,
with VCN clocks enabled before module insertion. The GPU bound and firmware
load returned zero, but VCN registers remained `0xffffffff`. A final guard
made failures from both type-13 post-load reset services visible to the PSP
caller. In 27 instruction-level cases it propagated either failure and avoided
marking firmware loaded; on the BC250, the intact firmware still returned
`ret=0`, PSP status `0`, and the same address. Thus both reset *services*
returned zero, while VCN version/status/power remained `0xffffffff` before
and after the load. The actual SVC `0x7c` implementation does not read back
the register, so this is not proof the hardware accepted those stores.
The Pico verified 754/754 changed replies across two boot passes for the last
profile, with no routing faults. The board remains on the isolated diagnostic
boot, GPU bound with VCN registration off; no ring or frame was decoded. The
next experiment needs an independent observation of VCN fabric access or the
missing isolation/power prerequisite, rather than another unguarded ring test.

**Update 2026-09-27, full-address reset-page read:** On a fresh diagnostic
boot, the bound GPU again accepted intact VCN firmware at `0xf41fa00000`.
With the measured VCN clock/power settings held active afterward, full PCI
SMN controls for domain 6 returned their expected `0` and `0x01010101`, but
the VCN reset-page word at `0x0900c004` returned `0xffffffff`. BAR VCN
version/status/power also remained `0xffffffff` before and after the SMN
read. The temporary clock controls were restored, and the unused diagnostic
reboot timer and GRUB entry were removed. The board remains in diagnostic
mode. This rules out firmware acceptance alone exposing either register path;
it does not distinguish hardware rejection, gating or a missing earlier
configuration step.

**Update 2026-09-27, post-auth register and reset trial:** With the GPU bound
under a default-off probe module and VCN registration disabled, an intact late
type-13 PSP request returned `ret=0`, status `0`, and firmware address
`0xf41fa00000` in the separate video TMR. PSP control read `0xf4`, while VCN
version, status and power registers all read `0xffffffff` both before and
after the accepted load. A guarded repeat of the previously tested client-12
down/up sequence then completed after that load: commands 7 and 6 each returned
full PSP success `0x80000000`, all eight primary controls returned to their
measured baseline, and temporary SMU code and clocks were restored. The same
three VCN registers still read `0xffffffff`. A direct diagnostic reboot was
completed to clear the cycle's unknown window side effects; the consumed GRUB
entry was removed and `/boot` is read-only. Neither firmware
authentication nor this bounded SMU transition is sufficient to make VCN
registers accessible. The next useful work is to identify the omitted access,
reset or power prerequisite. The signed PSP driver's generic RSMU startup
explicitly skips client 12, and its VCN post-load reset stores ignore the SMN
service return; a successful load cannot establish that either reset store
reached hardware. Those are the next offline trace targets. Repeating the same
ring startup would only time out. No BIOS EEPROM or Pico flash writes were
made, and no desktop restore was performed.

**Update 2026-09-27, driver-startup trials:** A RAM-only signer and VCN-key
interposer booted the BC250 with a no-op PSP-driver wrapper; the same early,
deliberately tampered type-13 VCN request returned `0x80000029`. A second
boot changed only the driver's 56-byte video metadata initialization. That
request returned `0xffff3072`, the expected signature-rejection path, with
no MMHUB page fault in the diagnostic log. The Pico verified all 626 changed
SPI replies across two passes with no reported timing or routing fault. This
isolates missing PSP video metadata as an earlier barrier than firmware
signature verification. On the next metadata-only boot, the same guarded
type-13 request with **intact** `navi10_vcn.bin` returned PSP status `0x0`
and firmware address `0xf41f800000`, the TMR base. The runner restored the
temporary clock controls and left the GPU unbound. Firmware acceptance is
now established; register access, VCN ring startup and decoded frames remain
unverified. Trials leave the BC250 on the diagnostic path, with no desktop
restore or BIOS flash write.

The first opt-in VCN 2.0.3 module kept PSP firmware loading but failed its
graphics KIQ test (`-110`) under metadata-only firmware. A control boot using
the same module, clock sequence and Pico profile with VCN registration off
bound successfully and created a render node. The RAM-only profile that also
allocates a separate 1-MiB video TMR then booted cleanly: the intact PSP
request returned address `0xf41fa00000`, exactly 2 MiB above the TMR base.
With this profile, graphics KIQ passed and the opt-in driver reached VCN
initialization, but `mmUVD_PGFSM_STATUS` read `0xfffff` under its mask and the
VCN decode ring timed out (`-110`). The remaining barrier is register access,
power/reset state or a related VCN initialization prerequisite; no decoded
frame has been produced.

**Update 2026-09-27:** The [Pico 2 interposer trial](pico2-type51-vcn-trial.md)
has now booted Fedora with the authentic VCN2 usage-6 key substituted only
for the type-51 copy read. A live PSP control confirmed key recognition. The
unmodified VCN firmware load still returns `0x80000029`, the VCN registers
remain inaccessible, and the stock amdgpu driver registers no VCN block.
Changing one byte of the signed firmware body on a separate guarded boot
produced the same PSP status. An RLC control on the same PSP ring returned
the expected signature rejection, while VCN still returned `0x80000029`.
The VCN response also persists before graphics firmware loading. Early VCN
requests coincided with an MMHUB fault outside the reported VRAM and GART
ranges, including when firmware staging itself was in VRAM. A full log from an
earlier late VCN request shows the same `0x80000029` status with **no MMHUB
fault**, so that fault is not a required cause of the status. The missing
VCN-specific PSP initialization/TMR state is the more useful boundary.
A RAM-only signer-only control subsequently booted Fedora with 416/416
substituted words verified, establishing a path to re-signing a driver trial.
Hardware video decoding is not working. The capture and equipment plan below
is earlier background.

2026-09-25. [Positive Technologies demonstrated a working active SPI
interposer on a BC250](https://habr.com/ru/companies/pt/articles/979470/): it
substituted a PSP key during one read and supplied the original during the
later verification read. Our [offline tests](../output/video-decode-20260922/BC250_INTERPOSER_ROUTE.md)
now reproduce that split for this P3 key database and authenticate a VCN2
firmware payload when its usage-6 key occupies one runtime database slot. This
is the most concrete route to try. A private clean/patched image pair is
prepared for a future **isolated external-flash interposer**; the patched image
is invalid as a standalone BIOS and must never be written to the on-board
EEPROM. No physical interposer was ready at that stage, and no hardware frame
had been decoded.

Update 2026-09-26: two Pico input-only reboot traces now show about 33.27 MHz
SPI and the same 2,133 complete reads matching the working BIOS. The Pico is
still at 150 MHz. [Measured timing and next implementation work](pico2-measured-timing.md)
supersede the earlier equipment plan below. The current active router fails
these timings; no active interception or VCN decoding has been demonstrated.

The next hardware measurement should establish the repeat-read order around
the key databases on **this** board at
`9dad00` and `9dbb00`. It can also check accesses to the encrypted bootloader
at `821000` and directory-listed copy at `8e0400`.
The [published Pico 2 switcher](https://habr.com/ru/companies/pt/articles/979470/)
used trigger `0x039db8dc` and a `0x338`-command window for its own
`BL_PUBLIC_KEY` reads. Those constants are not portable: the pinned P3 type-50
body here ends at `0x9db8d0` (last four-byte read `0x9db8cc`), and the
type-51 body ends at `0x9dc040` (last read `0x9dc03c`). The Pi analyzer now
reports complete-pass endpoints and observed command counts, but a full trace
and CS-high timing are still needed before configuring any active switch.

## Equipment and feasibility

The Waveshare CH347 remains useful for recovery programming. Its manufacturer
explicitly documents [SPI as host/master mode](https://www.waveshare.com/wiki/USB_TO_UART/I2C/SPI/JTAG).
It is not a passive SPI analyzer. Do not attach its programming outputs or
power supply to J4004 while the BC250 is running for this measurement.

The Pi can host capture software and store results. Its RP1 has a PIO block;
[Raspberry Pi's PIOLib](https://www.raspberrypi.com/news/piolib-a-userspace-library-for-pio-control/)
can run autonomous PIO programs with DMA-backed FIFO transfers. An
[input-only Pi 5 command/address sniffer](../tools/pi5-spi-capture/README.md)
now compiles against Raspberry Pi's PIOLib. It and a Pi-only SPI0 sender are
built on the Pi; a no-wire probe armed RP1 PIO/DMA and restored the GPIOs after
interruption. **No loopback traffic or board SPI has been captured**; sustained
capture rate and edge timing remain unknown. A separate compatible logic
analyzer is the established direct
SPI-capture approach. Its supported voltage, sample rate at the required
channel count, and capture depth must suit the observed bus; no exact model or
clock rate has been selected or measured yet.
For a later active trial, the published method used a Pico 2, two external SPI
flash devices and an interposer in place of the board's flash chip. J4004 and
the CH347 alone do not provide that function. Electrical isolation of the
on-board flash must be designed and checked before attaching an active device.

The user has the Pi 5 and CH347, and on 2026-09-26 ordered a Pico 2, SPDT
switches, 10 kΩ resistors and wiring. [Firmware, a private payload and staged
wiring instructions](../tools/pico2-interposer/README.md) are prepared for
passive capture and an isolated bench test. The published *active-trial*
hardware used a [Raspberry Pi Pico 2](https://www.raspberrypi.com/products/raspberry-pi-pico-2/),
two compatible 128-Mbit/16-MiB 3.3-V SPI NOR devices, and a dual-flash
socket/interposer that isolates the board's original flash. An [experimental
one-original-flash/Pico-SRAM overlay](pico2-original-flash-overlay.md) could
avoid buying extra flash chips, but still requires physically isolating the
original chip's CS# and has a harder SPI-response timing problem. The recovered
chip identifies as JEDEC `C2 20 18`; the likely
[Macronix MX25L12872F](https://www.macronix.com/Lists/Datasheet/Attachments/8935/MX25L12872F,%203V,%20128Mb,%20v1.1.pdf)
is 2.7–3.6 V and exists in 200-mil SOP8, but the actual package/marking
should be confirmed before ordering the fixture. A separate high-speed
four-channel input-only analyzer is strongly useful for the first capture and
signal-integrity/debug checks, though the Pi 5 PIO command-capture experiment
could be tried before buying one. Sampling capability must be considered **with
four channels enabled**; [Saleae recommends at least four samples per signal
period](https://www.saleae.com/support/specifications-hardware/electrical-characteristics/what-is-the-maximum-bandwidth),
and the board's actual SPI clock remains unmeasured. The published Pico 2 PIO
command sniffer could reduce reliance on a separate analyzer, but that firmware
has not been prepared or tested here, and it would not show the full data bus.

UART reception is supported by the Waveshare, but that alone does not establish
a BC250 serial logging route. Our earlier inspection found the SuperIO POST
UART mux disabled, and no accessible early-boot output has been verified.
Locating that signal is a possible investigation, not a ready wiring plan.

## Capture plan once suitable equipment is identified

With only the available Pi 5, first validate the
[PIO sniffer](../tools/pi5-spi-capture/README.md)
against a known local SPI source. Its separate four-wire J4004 setup captures
CS#, SCLK and MOSI commands, not MISO data or a measured SPI clock. Treat any
gaps as capture uncertainty. The fuller analyzer procedure is:

1. Identify the analyzer model and verify its input-only capture configuration
   and electrical limits before connecting it.
2. With the board powered down, prepare passive inputs for J4004 CS#, SCLK,
   MOSI and MISO, with a common ground. The programmer remains disconnected;
   this is not the existing six-wire programming/power connection. The
   [board reference](https://github.com/mothenjoyer69/bc250-documentation/blob/main/hardware.md#j4004)
   documents the header; analyzer-specific wiring remains to be prepared.
3. Arm capture before a normal power-on. First validate signal levels, clock
   sampling and decoder settings. Preserve the raw capture and any overflow
   indicators. There is no BIOS write in this experiment.
4. Decode command/address/data transactions and compare returned bytes with
   the saved image. Account for the actual SPI command mode and capture gaps;
   do not infer missing reads from a lossy trace.
5. Correlate access order with both bootloader locations and the two key
   databases. Confirm whether the relevant body reads occur twice and which
   read is used for the copy versus the signature hash. [PSPTrace](https://github.com/PSPReverse/PSPTrace)
   documents this workflow using exported Saleae SPI data; another analyzer
   may need a format conversion or a separate decoder.

The result is an access chronology, not an instruction trace. Reads of a
bootloader do not alone prove execution; an incomplete trace cannot prove a
region was never accessed. The capture does not guarantee hardware decoding.
It measures whether the published switch strategy applies at the expected
offsets and timing on this particular board.

## What happens after the capture

If the read chronology matches the published exploit, one small first physical
experiment is an **external** two-flash interposer selecting a same-length
type-51 database whose usage-44 record is replaced by the authentic usage-6
VCN2 key during the copy read, then the clean database for the verification
read. A [private clean/patched pair](../tools/vcn-interposer-pair/README.md)
has been prepared and independently checked for that experiment; the patched
image must never be written to the on-board EEPROM. The signed header must
stay original: changing its stored body digest
fails even when the later body read is clean. This is an offline-proven
authentication route, with an untested loss of usage 44 and a stale ordinary
body digest; it must be tested for ordinary boot and key lookup before trying
VCN power or ring changes. A more complete route would use the published TOS
signer substitution and [an offline-tested TOS component with a prepared
external-flash-only image pair](../output/video-decode-20260922/TOS_VIDEO_INTERPOSER_COMPONENT.md)
to add the VCN key without losing any key. Its actual access to the runtime
database has not been measured on this board. Keep the original EEPROM intact.

Only after a required video key is accepted can we test compatible VCN firmware,
power/reset state, ring operation and actual decoded frames. Those requirements
remain separate; the missing key is not proven to be the decoder's only barrier.
The Fedora bootc image currently uses the stock amdgpu driver, whose pinned
7.2.5 source leaves VCN 2.0.3 unregistered. A [previously built experimental
module](../output/video-decode-20260922/RESULT.md) reached the PSP
firmware-load command but received a rejection consistent with the missing key;
it is a diagnostic path for a future isolated trial, not a deployed decoder.
After authentication, a successful PSP response still needs accessible VCN
registers, working decode rings and a forced hardware-frame playback test
before any driver change belongs in the bootc image.

The archived P1 BIOS already has the same relevant bootloader and key databases;
it supplies no new video key. The tested internal P3, Deck and 4700S alternatives
also provide no established deployable fix. See
[the progress log](../progress.txt) for the full evidence and current state.
