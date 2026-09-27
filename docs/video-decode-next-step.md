# Next hardware-decode investigation step

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
