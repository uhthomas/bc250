# Full BC250 SPI command trace through the Pico CS# relay

2026-09-27. The existing [five-wire connection](pico2-cs-pass-hunt-wiring.svg)
was unchanged. The Pico still relayed motherboard CS# to the original flash
on GP7; GP3 and GP4 only observed SCLK and MOSI. MISO stayed unconnected.
Both capture images ran from Pico SRAM. Neither image wrote the BIOS or Pico
flash or substituted a firmware byte. Fedora booted with the relay armed.

The first full-stream candidate sent raw 32-bit commands over USB. Its Pico
PIO observed 1,832,073 commands without an RX stall, but the USB ring lost
585,926 commands during the burst. The resulting file is explicitly invalid
for ordering. The [RLE v2 image](../tools/pico2-interposer/cs_pass_stream.c)
encodes a maximal +4 command run as a start word and count; every other word
forms its own run. A 32,768-record synthetic USB test (256 KiB) passed before
the board trial.

The RLE v2 board capture reported **1,832,116 observed and sent commands,
52,122 records, zero overflow and zero PIO stall**. Its binary SHA-256 is
`b3c22dd2d6d8bd43d8f6b696717e87b46e853e22bf837d93cbb831f48349a5ed`.
The SRAM UF2 staged on the Pi at
`/home/pi/bc250-pico2-20260926/candidates/cs-pass-rle-v02/` has SHA-256
`dbf66d271ebfb8fa4416f2738175e42766573e891a1b362bd32cb097a137748d`.
The capture and metadata are retained privately under `output/pico2/` as
`boot-rle-20260927.bin` and `boot-rle-20260927.json`.

The local [full-trace analyzer](../tools/pico2-interposer/analyze_full_cs_stream.py)
checks the RLE hash and expansion count, compares all 3,712 boot-region hits
against the earlier filtered capture, and compares the two observed command
passes. They are **identical for 878,104 complete commands** from their first
type-50 key-database read. The last changed overlay word is read at relative
transaction 872,743, leaving 5,360 further matching commands before the
first divergence. The required 872,744-command prefix consists entirely of
aligned READ03 transactions and compresses to 37 +4 runs per pass. Every one
of the 318 changed words appears in each pass. The analysis JSON is
`output/pico2/boot-rle-20260927-analysis.json`.

These facts provide a complete observed command order through the firmware
reads that matter. They do not measure MISO electrical handover or
decrypted-module behavior. The
[sparse selector PIO](../tools/pico2-interposer/sparse_select_od.pio)
passed modeled default-PASS, queued-PATCH and wrong-command-fault cases on
four physical edge windows at 340 MHz. Its CPU scheduler and board arm/fault
handling were subsequently implemented. The first [six-wire board controls](pico2-six-wire-miso.md)
stopped the BC250 despite exact-original replies; correcting the MISO output
edge subsequently made exact-original active controls boot successfully. An
extended 873,480-command scope through both type-51 reads enabled the
[copy-only VCN-key trial](pico2-type51-vcn-trial.md), which booted Fedora and
passed a bounded live PSP key-recognition test. VCN firmware and decode remain
unavailable.
