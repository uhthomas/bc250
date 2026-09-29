# RAM-only VCN driver startup trial

**2026-09-29 PSP TMR read control:** A signed, RAM-only hook asked the PSP
mapping helper to read the VCN firmware TMR page after the first VCPU
wait. The helper returned a nonzero value whose low 28 bits were `0xf`
before any payload word was read. The same delayed call also returned
`0xf` for a PSP bookkeeping address used by the signed driver in another
context, so the mapping result is inconclusive about firmware presence.
The two targets each passed ten native ARM cases, and Pico verified
2,086/2,086 and 2,090/2,090 substitutions over two BIOS passes without
fault or stall. The normal boot is
`e8d08497-33f8-4f87-befb-d26a04cd0d98`, with Pico CS-PASS armed in
SRAM; no flash write or decoded frame. See the
[investigation](../../docs/video-decode-next-step.md) for logs and limits.

**2026-09-29 MPC mux comparison:** The signed
[`driver-delayed-vcn-mux-premap.S`](driver-delayed-vcn-mux-premap.S)
compared three VCPU fetch mux registers at full 32-bit width after the
first VCPU wait and before any second-call cache-map replay. It returned
`0x72000003`, matching Linux's MUXA0 and MUXB0 `0x040c2040` and MUX
`0x88`. The VCPU still did not reach ready (`UVD_STATUS=4`). Ten native
instruction cases and 2,010/2,010 Pico substitutions across two BIOS
passes passed without fault or stall. The reused kernel runner labels the
event `cache-size0`, but this hook compared the muxes. The normal BC250
boot is `ae0f6a38-2e7c-4be3-af63-b9cb9d45dac1` with Pico CS-PASS in
SRAM; neither flash device was written. See the
[investigation](../../docs/video-decode-next-step.md) for hashes and
limits.

**2026-09-29 MPC control read:** A pre-map signed PSP hook sampled
`UVD_MPC_CNTL` after the first VCPU wait and reported low 28 bits `0x10`,
matching replacement mode 2. The feared poisoned host read-modify-write
would have reported `0x0fffffd7`; that failure was not seen. Twelve native
cases and 1,934/1,934 Pico substitutions passed. VCPU-ready remained
absent. The [investigation](../../docs/video-decode-next-step.md) records
the exact hashes and limits. The normal BC250 boot is
`a1f29978-e69a-4df7-8155-03e35733675d` with Pico CS-PASS in SRAM;
neither flash device was written.

**2026-09-29 full pre-map cache comparison:** The new signed
[`driver-delayed-vcn-map-premap.S`](driver-delayed-vcn-map-premap.S)
compares all sixteen VCPU firmware, stack, context and shared-memory
cache-window words at full 32-bit width after the first VCPU wait, before
the second PSP call replays a window. It returned `0x70000010`: all sixteen
matched. `UVD_STATUS` stayed `4`, so firmware fetch and VCPU execution
remain unproven. The 23-case native test covered every mismatch index and
the unmarked startup; Pico verified 1,978/1,978 substitutions across two
BIOS reads. The reused Linux runner calls its status `cache-size0`, but
this hook compares all sixteen words. No frame or flash writes. See the
[investigation](../../docs/video-decode-next-step.md) for hashes and limits.

**2026-09-29 delayed firmware BAR control:** A second pre-map variant
sampled PSP `UVD_VCPU_CACHE_BAR_LOW0` after the VCPU wait but before map
replay. Its low 28 read bits were `0x0fa00000`, matching the programmed
BAR low `0x1fa00000`; VCPU status stayed `4`. The kernel runner reused the
`cache-size0` event name, but the signed hook actually sampled `0x2107c`.
Ten native cases and 1,934/1,934 Pico substitutions over two BIOS passes
passed. This shows BAR low and cache size retained their observed values,
not that the firmware was fetched or that the VCPU executed. See the
[investigation](../../docs/video-decode-next-step.md) for hashes and limits.

**2026-09-29 delayed cache persistence control:** The first delayed
cache-size diagnostic read occurred after the hook replayed all 17 map
writes, so it did not prove persistence. The corrected
[`driver-delayed-vcn-cache-premap.S`](driver-delayed-vcn-cache-premap.S)
reads `UVD_VCPU_CACHE_SIZE0` after the first Linux VCPU wait but before
any cache-window replay in its marked call. It returned `0x64000`, the
value programmed in the first successful PSP load, while VCPU status
remained `4`. Ten native cases checked the order; the Pico verified
1,934/1,934 substitutions across two BIOS reads with no fault or stall.
One cache size setting persisted, but the other map words and VCPU fetch
have not been shown to work. No frame decoded or flash device was written.
The [investigation](../../docs/video-decode-next-step.md) records hashes
and normal-boot recovery.

**2026-09-29 delayed reset result:** The first three delayed-read profiles
relocated the original VCN address table to PSP data address `0xe19010` and
stalled powered `LOAD_IP_FW` before the read. A relocation-only control
stalled identically, matching an earlier failed writable-data table path.
Do not use those profiles for another live run. The corrected
[`prepare_delayed_vcn_reset_code_trial.py`](prepare_delayed_vcn_reset_code_trial.py)
keeps both proven RX-region tables at `0xe17d98/0xe17fb8` and places only
the 72-byte hook dispatch in zero code space at `0xe00200`. Its signed
RAM-only view passed nine native PSP cases, and the Pico verified all
1,926 substitutions across two BIOS passes without a fault. The initial
powered PSP firmware reload succeeded. After one full VCPU wait, a second
PSP call read `UVD_SOFT_RESET` without writing it and reported low 28 bits
`0`; VCPU-ready still did not appear (`UVD_STATUS=4`). Reset bits 3 and 19
therefore had not reasserted during that interval. The [investigation
log](../../docs/video-decode-next-step.md) has the exact hashes, evidence
and limits. No flash device was written or frame decoded. BC250 is back
on normal Fedora boot `f9330749-003d-404b-bc7e-a46343dd5a17`.

The 2026-09-29 [cache-route generator](prepare_cache_route_trial.py)
produced two signed, RAM-only profiles with the same verified early policy.
The PSP read of cache BAR low `0x2107c` **before** any PSP window write
reported low 28 bits `0`; the host had attempted to write `0x1fa00000` but
read back all ones. A second profile wrote the 17 cache windows through the
PSP and reported low 28 bits `0x0fa00000` afterward, matching the PSP's
own write. Both hooks first checked PSP VCN power `0x800`. The diagnostic
status intentionally aborts firmware loading and discards the high four
data bits. This isolates a host/PSP access-path difference without proving
which routing or isolation control causes it. The earlier successful PSP
cache/reset replay still produced no VCPU-ready bit. See the
[full result](../../docs/video-decode-next-step.md). Both trials passed
native ARM checks and Pico physical substitution checks; no flash writes
or decoded frame occurred. BC250 is back on normal Fedora boot
`9ce1c8eb-de37-4d7b-b159-22974eee2bb4`.

The 2026-09-29 combined early-gasket/late-reset profile closes a limitation
of the reset-stability trial below: that diagnostic hook returned a nonzero
status, preventing a successful post-release PSP firmware reload. The new
hook returns success after its PSP-side reset-bit check. The Pico verified
1,854/1,854 substitutions, and post-release `LOAD_IP_FW` returned
`ret=0/status=0`, but VCPU-ready bit `0x2` remained clear (`UVD_STATUS=4`).
Linux sets the `0x4` busy bit itself. The PSP-side reset readback does not
prove the host reset/cache aperture is responding. See the [full result](../../docs/video-decode-next-step.md)
and ignored physical logs under
`output/pico2/tos-entry-gasket12-postcache-success-20260929/physical/`.
Neither BIOS EEPROM nor Pico QSPI was written; no frame decoded.

The `...postcache-map-rx-uvd-reset-stability` profile writes zero once to
the powered VCN `UVD_SOFT_RESET` register, then reads it 128 consecutive
times via the PSP without another write. The last read was zero with native
VCLK clock code 16, but VCPU status stayed `4` and the decode ring timed
out. The [journal](../../output/video-decode-20260922/results/native-reset-stability-20260929.jsonl)
and [kernel log](../../output/video-decode-20260922/results/native-reset-stability-20260929.dmesg)
record the result. The 29-case native model and 1,414/1,414 Pico
substitutions passed. This does not prove reset stayed clear after the
hook returned. BC250 is back on normal boot
`8e5cc91a-8355-4f3e-adee-716d66b7c255`; neither flash device was written.

The `...postcache-map-rx-uvd-reset2-before-write` profile adds a PSP read of
VCN `UVD_SOFT_RESET2` at `0x1ff98` without writing the target. On a native
1250 MHz VCLK diagnostic boot, it returned `0x00030000`: both MMSCH clock
reset-status bits were set and the atomic-reset control bit was clear. The
Pico verified 1,402/1,402 substitutions, fault 0; VCPU status stayed `4` and
the decode ring timed out. The runner's generic `reset_low28` field contains
this `SOFT_RESET2` value. See the [journal](../../output/video-decode-20260922/results/native-reset2-beforewrite-20260929.jsonl)
and [kernel log](../../output/video-decode-20260922/results/native-reset2-beforewrite-20260929.dmesg).
The BC250 is back on normal boot `a6329fe6-db36-4bc7-9965-94152bfef2b6`
with Pico CS-PASS v2 armed in RAM. No BIOS EEPROM or Pico QSPI write occurred.

The `...postcache-map-rx-uvd-reset-before-write` profile replays the pinned
VCN memory windows and then reads PSP address `0x20180` without first writing
that register. The corrected build uses the proven 52-byte TMR hook; its
signed ROM view differs from the earlier powered reset-status profile only
in this readback hook, hashes and signatures. The 28-case native ARM check
passed. With native SMU clock code 16 applied, the live PSP read returned
`UVD_SOFT_RESET=0x00080008` after Linux's release sequence. VCPU reset and
its VCLK reset-status indication therefore remained asserted. The earlier
zero readback was produced by a diagnostic hook that explicitly wrote zero
first, and that trial also left `UVD_STATUS=4`. The first build of the new
profile accidentally used an older 40-byte TMR hook and yielded all-ones
VCN MMIO; discard that run. The corrected Pico image verified 1,402/1,402
substitutions with no faults. Raw evidence is in
`output/video-decode-20260922/results/native-reset-beforewrite-v2-20260928.*`;
see [the investigation log](../../docs/video-decode-next-step.md) for the
recovered normal-boot state. No BIOS EEPROM or Pico QSPI write was made.

The `vcn-skip-both-1f820` profile also guards the earlier signed
`SEC_GASKET` section `0x201` write. It suppresses the service call only when
both the address and value match `(0x1f820, 0x185103)`, while retaining every
other policy write and the original policy bytes. Offline execution of the
real policy loop yielded 1,230 writes before and 1,229 after the guard, with
three predicate controls. The re-signed driver and physical profile passed
the RAM-only boot: 1,458/1,458 substitutions, zero faults and routing
mismatches. On boot `5eeba018-0e66-43c9-81a9-dbcdd927b49d`, powered host
MMIO still read `CC_UVD_HARVESTING=3`; PSP firmware load returned zero status,
but VCPU status stayed `4` and the decode ring timed out `-110`. This excludes
both observed `0x1f820` requests as a sufficient fix if the early policy
loop ran; no direct live marker established that it did. The ignored trial is
`output/pico2/driver-video-skip-both-control-20260928/`, prepared by
[`prepare_policy_control_trial.py`](prepare_policy_control_trial.py) and
checked by [`test_policy_control_trial.py`](test_policy_control_trial.py).
Neither flash device was written.

The preceding `...postcache-map-rx-skip-1f820` profile omits the original
type-13 setup write `0x1f820 <- 0x185103` by replacing its `SVC #0x7c`
with a zero-result Thumb instruction. Eight native startup and 25 post-load
offline cases pass. The Pico verified 1,406/1,406 substitutions over two
boot passes with zero faults and routing mismatches. On boot
`960c4549-0a87-475f-8952-297b3eedff7f`, powered host MMIO still read
`CC_UVD_HARVESTING=3`; PSP firmware load succeeded but the VCPU never
started and the decode ring timed out `-110`. This single original write
does not explain the live disable value. A separate signed `SEC_GASKET`
record contains the identical tuple and was not altered; Cezanne and Renoir
reference policies contain it too. The profile and UF2 are ignored
under `output/pico2/driver-video-skip-native-control-20260928/`; neither
flash device was written. See `docs/video-decode-next-step.md` for the full
trace and the remaining uncertainty about the value's source.

Two RAM-only PSP readback profiles now target VCN firmware-cache BAR low at
word address `0x2107c`. Plain read returned low 28 bits `0xeadbeef`. A
profile that first wrote the observed TMR low word `0x1fa00000` through PSP
service `0x7c` received zero service status, but read the same `0xeadbeef`
pattern. The second profile's ten real-instruction cases checked the write
value, read order and error paths. Its two live boot passes verified
1,210/1,210 Pico substitutions without fault. The readback cannot distinguish
a blocked write from an unreadable register. A third control profile used the
same PSP read service on VCN power status at `0x1f810` and obtained low 28 bits
`0x801`, matching the host read, with 1,198/1,198 fault-free Pico
substitutions. The cache-register poison value is specific to that path at
this stage. No flash device was written.

The latest diagnostic boot used the same RAM-only gasket profile. IP discovery
lists VCN 2.0.3 with no reported harvest or codec-disable table. Its LMI
registers were readable during VCPU startup, and the VCPU clock was enabled,
but status stayed `0x4` and the ring timed out. The four installed Navi10,
Navi12, Navi14 and Renoir VCN 2.x firmware files share one microcode payload,
so renaming that firmware is not a useful next experiment. See
`docs/video-decode-next-step.md` for the register values and limits.

The `metadata-tmr-svc-guard-rsmu12-gasket` profile replays 51 client-12
`SEC_GASKET` records from matching pinned Cezanne/Renoir policies after the
video TMR and native RSMU setup. The BC250's own policy contains no such
records. `prepare_gasket12_table.py` checks both source hashes and emits the
assembly table. The cave is 440 bytes in a verified 512-byte zero run, and
the generated ROM is invalid as standalone BIOS. A live PSP-side read of
descriptor `0x0900c9a0` returned low 28 bits `0x20180`, matching the written
value. Intact VCN firmware loaded at `0xf41fa00000`, and host power status
became `0x801`, but full VCN initialization still timed out waiting for the
VCPU. The host's VCN cache-window and soft-reset register readbacks remained
all ones. A separate BC250-only direct-reset kernel module did not change
the failure. A direct-VRAM VCN firmware control also stalled at status `0x4`
with VCN cache-window readbacks all ones. The Pico verified 3,342/3,342
changed replies across six boot passes of the base gasket profile, with no
fault. The live journals and private profiles are under
ignored `output/pico2/driver-video-gasket*-20260927/`. These are research
artifacts, never BIOS EEPROM images. The BC250 remains in diagnostic mode.

The `metadata-tmr-svc-guard` profile also guards the original type-13
allocator's `0x1f820 <- 0x185103` service result. An injected nonzero result
now follows its existing error cleanup instead of being overwritten. On the
BC250 the GPU bound and intact VCN firmware loaded at `0xf41fa00000`, so the
software service did not report an error. One setup-order mistake briefly
booted the ordinary entry before the diagnostic entry was restaged; that boot
failed `SETUP_TMR` because VCN clocks were not enabled before module insertion.
The board was then cold-booted into the isolated diagnostic path.

The `metadata-tmr-svc-guard-rsmu12` profile additionally calls the signed
driver's native four-store RSMU client-12 initializer during `SETUP_TMR`.
Its real instructions request `0x0900c814 <- 0x03810100`,
`0x0900c818 <- 0`, `0x0900c824 <- 0`, and `0x0900c810 <- 0x8000`.
Seven native TMR tests verify the ordering and skip the helper on allocator
failure. The BC250 bound its GPU and loaded intact firmware with zero status,
but VCN MMIO stayed all ones.

The `metadata-tmr-svc-guard-rsmu12-postload` profile guards both type-13
post-load reset services: `0x0900c004 <- 1` and `0x1f8a4 <- 1`. The stock
driver ignores the first status and its second helper forces zero. The guard
uses the original nonzero-helper return path if either reports an error.
Twenty-seven native-instruction cases cover physical-function and other
contexts, either failure, mapping outcomes and loaded-flag behavior. On the
BC250, the intact load still returned `ret=0`, PSP status `0`, address
`0xf41fa00000`; VCN version, status and power stayed `0xffffffff`. This
establishes zero *service* results, not register readback or power release.
The Pico confirmed 754/754 changed replies over two passes with no fault.
Private ROMs and UF2s are under ignored `output/pico2/driver-video-{svc-guard,
rsmu12,postload}-20260927/`; all are RAM-only interposer candidates and the
ROMs must never be flashed to the board. The BC250 remains in diagnostic mode.

The combined metadata/video-TMR profile booted repeatedly with fault-free Pico
substitutions. The accepted intact VCN firmware address moved from TMR base
`0xf41f800000` to `0xf41fa00000`, matching the requested 2-MiB video offset.
A bound-GPU, VCN-disabled diagnostic probe later accepted the same firmware at
that offset but found VCN version, status and power registers reading
`0xffffffff` before and after loading. A post-auth client-12 down/up SMU cycle
also completed with full PSP success and restored primary controls, yet those
VCN registers remained all ones. The desktop was not restored between trials.
A fresh authenticated-load boot also read full-address VCN reset-page SMN
`0x0900c004` as `0xffffffff` with clocks and power controls active, while its
domain-6 control reads matched expectations. No decoder ring or
hardware-decoded frame works yet.

Live no-op and metadata-only profiles both booted Fedora on 2026-09-27 with
two complete Pico substitution passes and zero reported faults. The no-op
profile verified 586/586 changed replies and the metadata profile 626/626.
An early signed-byte-tampered type-13 VCN request returned `0x80000029` on
the no-op boot, then `0xffff3072` on the metadata boot. The latter is the
expected signature-rejection status; its diagnostic log showed no MMHUB page
fault. This is evidence that video metadata initialization moves the PSP
request into signature checking. On a third metadata-only boot, an intact
405,696-byte `navi10_vcn.bin` type-13 request returned `ret=0`, PSP status
`0x0` and firmware address `0xf41f800000`, the reported TMR base. No MMHUB
fault was logged. The guarded hook then intentionally stopped GPU probing;
it did not attempt VCN registers, rings or a decoded frame. The BC250 remains
in diagnostic mode for driver investigation.

That driver-startup trial now shows a second effect. Without the video-TMR
allocation, enabling VCN makes graphics KIQ fail; an otherwise identical
VCN-disabled control binds successfully. With the 1-MiB video region at TMR
offset 2 MiB, the intact type-13 PSP response returns the expected base+2-MiB
address, graphics KIQ passes, and amdgpu reaches VCN hardware initialization.
The VCN `PGFSM_STATUS` poll reads all ones under its mask, and the decode ring
test times out with `-110`. The driver remains unbound. This is progress through
firmware authentication and TMR layout, not a working decoder.

The signer-only interposer boot on 2026-09-27 reached Fedora with two complete
SPI passes and 416/416 substitutions verified. The original TOS and PSP driver
bodies were unchanged. This validates the type-50 signer route on this board;
it does not make VCN work.

`driver-video-startup.S` provides PSP-driver wrappers at runtime address
`0xe17d00`, called from the original startup site at `0xe09622`. Both call the
original initializer at `0xe09890`. The `noop` wrapper then returns. The
`metadata` wrapper additionally zeros the 56-byte video cache at `0xe35cc0`
and sets the three register-list ports to `0x1f90c`, `0x1f848`, `0x1f844`, as
AMD's Cezanne video initializer does. This does **not** power VCN or prove
those ports work on the BC250.

A third `metadata-tmr` variant also wraps the existing TMR allocator call at
`0xe0e85e`. It preserves the BC250's 2 MiB graphics allocation at offset zero,
then asks the installed allocator for a separate 1 MiB type-13 video region at
offset 2 MiB. It publishes the cached video offset only on allocator success;
a nonzero allocator result propagates through the original TMR setup cleanup
path. The `test_video_tmr_trial.py` model executes those real driver
instructions under two nonzero fills, 4 MiB/8 MiB TMR sizes and occupied-region
controls: seven cases pass with no graphics/video overlap. A negative case
shows that the installed allocator **ignores an error from its video-control
SVC write**. Its zero return cannot prove that the video control took effect.
Register I/O, protection and SMU services are modeled. The later live PSP
firmware address at TMR base+2 MiB independently confirms use of the requested
video region; it does not prove the video-control SVC changed the physical
power state.

`prepare_video_driver_trial.py` combines one of those wrappers with the
measured type-51 usage-6 VCN key substitution. It re-signs the changed
`DRIVER_ENTRIES` body and unchanged TOS body using the existing private
research key. The type-50 signer is substituted only for its copy read; the
authentic VCN key is substituted only for the type-51 copy read. The clean
flash supplies the later hash reads. The generated 16-MiB view is **invalid
as a standalone BIOS**. It must never be written to the BC250 EEPROM.

Inputs are pinned to the saved clean-ROM and measured type-51 profile hashes.
The generator checks driver header SHA-256, both RSA-PSS signatures, each
changed-word address, profile geometry, and expected reply counts. The scoped
native test in `test_video_driver_startup.py` executes the real Thumb wrappers
under two nonzero RAM fills. Six cases passed: no-op has the same post-startup
memory as the clean driver, and metadata changes only its intended 56-byte
state. Hardware I/O, full PSP boot and execution permissions for the code cave
remain outside that model.

Private artifacts are under ignored
`output/pico2/driver-video-startup-20260927/`. Built Pico UF2s are RAM-only
RP2350 RISC-V images, also staged on the Pi 5 under
`/home/pi/bc250-pico2-20260926/candidates/vcn-driver-{noop,metadata}-v02/`
and `.../vcn-driver-metadata-tmr-v01/`.
The v02 images add a pre-arm watchdog so failure to establish a serial session
should reset the Pico to its installed flash image. Once armed, the watchdog
is disabled for unattended board boot. No Pico flash or BC250 BIOS write is
part of this trial.

The first v01 no-op image verified into Pico RAM but did not enumerate over
USB. The BC250 was kept off for that failed startup. Cycling Pi 5 USB VBUS
restored the Pico's installed passive image; the v02 no-op and metadata boots
then completed. The combined metadata-and-video-TMR profile also booted and
passed the guarded VCN PSP load and driver-startup trials. Keep the board on
its diagnostic path between trials. Only
accessible VCN registers and an actual hardware-decoded frame can establish
that VCN decoding works.
