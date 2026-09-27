# Next hardware-decode investigation step

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
codec-disable mask. These firmware tables report VCN as present, though they
cannot prove the physical block works. The installed Navi10, Navi12, Navi14,
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
