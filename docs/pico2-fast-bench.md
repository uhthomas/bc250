# Pico 2 fast-reply test with only the Pi 5

The `bc250_fast_bench.uf2` candidate exercises the **preselected MISO reply
engine only**. It cannot route the BC250's original flash and has no BC250
board-arm command. It is linked at RP2350 SRAM address `0x20000000` and is
loaded as a **RAM image** with `picotool load -v -x`; this does not overwrite
the Pico's persistent passive firmware. Its PIO reply engine passed offline
replay around six measured patch addresses. On 2026-09-26, the image loaded
and verified in Pico RAM and reported its 200 MHz clock. The first isolated
100 kHz run failed before the user corrected the jumper orientation. After the user
corrected the wiring, every reply matched in the runs below. The RP2350 is
specified for 150 MHz; this candidate sets 200 MHz and the internal regulator
to 1.20 V as an isolated experiment.

| Pi SPI speed requested | Reply words | Mismatches | DMA complete |
|---:|---:|---:|---|
| 100 kHz | 8 | 0 | Yes |
| 1, 5, 10, 20 and 33 MHz | 128 at each speed | 0 at each speed | Yes at each speed |
| 33 MHz | 1,024 | 0 | Yes |

The host speed is a **request**, not an independent measurement of the wire
clock. This establishes sustained, correctly ordered replies on the isolated
Pi bench; it does not yet qualify the BC250's measured 33.27 MHz clock or its
short CS-high gaps.

**Before any Pico RAM load or Pi SPI transfer:** power the BC250 off. Unplug
Pico USB, remove **all five** J4004-to-Pico leads, and leave the BC250 and
Waveshare disconnected from the Pico and Pi GPIO. The BIOS flash chip leg and
switch remain untouched. The Pi 5 powers the Pico by USB. With both Pi and
Pico unpowered while making jumpers, connect only:

![Isolated Pi 5 to Pico 2 bench wiring](pico2-pi-bench-wiring.svg)

| Pi 5 physical pin | Signal | Pico 2 physical pin (USB at top) |
|---:|---|---:|
| 24 | SPI0 CE0# | 4 / GP2 |
| 23 | SPI0 SCLK | 5 / GP3 |
| 19 | SPI0 MOSI | 6 / GP4 |
| 21 | SPI0 MISO | 7 / GP5 |
| 25 | GND | 8 / GND |

The physical positions match Raspberry Pi's
[SPI0 header map](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#spi0)
and [Pico 2 pinout](https://datasheets.raspberrypi.com/pico/Pico-2-Pinout.pdf).
The Pi and Pico headers are both male, so use the female-to-female jumpers.
Do not connect VCC, 3V3, VSYS, VBUS or Pico GP6/pin 9. Check that the five
Pico leads go to the **Pi header**, not J4004. The bench host refuses to open
SPI without `--isolated-pi-wiring`; the flag is a human wiring assertion, not
an electrical interlock.

With the Pi and Pico unpowered, make the five Pi-only connections above and
plug the Pico USB cable into the unpowered Pi. Hold BOOTSEL while powering the
Pi, then release it after the Pi receives power. The Pico should appear as one RP2350
BOOTSEL USB device. Verify `sha256sum -c SHA256SUMS` in the staged candidate
directory, and verify `picotool info bc250_fast_bench.uf2` reports binary
start `0x20000000`. Then use `picotool load -v -x bc250_fast_bench.uf2` with
the single BOOTSEL device selected. The load target must be **SRAM**, not
`0x10000000` flash. The image is staged at
`/home/pi/bc250-pico2-20260926/candidates/fast-bench-v01/`. A Pico power
cycle discards it and restores the persistent passive firmware; reload the
RAM image before further bench runs if that happens.

Once the Pico reports its 200 MHz clock and outputs-off status, run
`fast_bench.py` first at 1 MHz, then 5, 10, 20 and a requested 33 MHz if
each prior run passes. The Pi's requested SPI speed is not an independent
physical clock measurement; scope/logic-analyzer evidence would be needed for
an analogue timing qualification.

All runs use 128 diverse response words, including all-zero, all-one and
alternating patterns. The host compares every returned word and requires the
Pico's reply DMA to complete. The Pico drives **only GP5** during an armed
bench run; GP6 remains input. It returns GP5 to forced-off after the host's
`done` message, timeout or abort. No BC250 EEPROM operation occurs.

The test does not yet verify the separate original-flash CS selector, output
contention, unexpected command handling or board boot. Do not solder the
BIOS CS leg based on a passing reply-only bench.
