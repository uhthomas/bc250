# RAM-only VCN driver startup trial

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
