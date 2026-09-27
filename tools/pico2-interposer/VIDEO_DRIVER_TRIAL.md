# RAM-only VCN driver startup trial

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
it did not attempt VCN registers, rings or a decoded frame. A separate
video-TMR allocation has not been established. The BC250 remains in
diagnostic mode for the driver-startup trial.

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
Register I/O, protection and SMU services are modeled. A physical type-13
allocation has **not** been observed.

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
then completed. The combined metadata-and-video-TMR profile has passed only
offline tests. Keep the board on its diagnostic path between trials. Only
accessible VCN registers and an actual hardware-decoded frame can establish
that VCN decoding works.
