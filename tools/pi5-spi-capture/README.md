# Experimental Pi 5 input-only boot-SPI capture

2026-09-25. This is an **experimental hardware capture**, not a trace from the
BC250. The Pi-side PIO setup has been armed and interrupted successfully, but
no SPI traffic has been captured. It does not program any flash, switch between
images or read MISO. The existing [external-flash interposer pair](../../output/video-decode-20260922/TOS_VIDEO_INTERPOSER_COMPONENT.md)
must not be put on the board's on-board EEPROM.

The [Positive Technologies BC250 report](https://habr.com/ru/companies/pt/articles/979470/)
observed single-I/O `03` commands, often four data bytes per transaction, and
used the first 32 MOSI bits to trigger a Pico 2 interposer. `capture.c` applies
that limited observation to the Pi 5's RP1 PIO: it records one 32-bit
opcode/address word per CS# assertion. It supports SPI modes 0 and 3, and
configures its three Pi GPIOs as **inputs with output enable forced off**.
The [RP1 datasheet](https://datasheets.raspberrypi.com/rp1/rp1-peripherals.pdf)
defines output-enable override `2` as disabled. No PIO instruction in this
program drives a pin.

The RP1 PIO clock is 200 MHz in the pinned PIOLib implementation. This loop
needs four PIO cycles per SPI bit, so a bus near 50 MHz is at its theoretical
limit, before synchronization and wiring delays. The board's actual SPI clock,
command mix and Pi capture reliability are **unmeasured**. A logic analyzer
remains the stronger measurement, especially for timing and MISO data.

## Current validation

- Built `capture.c` on the workstation with `-Wall -Wextra -Werror` against
  [Raspberry Pi PIOLib](https://github.com/raspberrypi/utils/tree/master/piolib)
  commit `ebc4a56bac3a896d5c14e56fe27dcd6cb36dd373`.
- Built both `capture.c` and the Pi-only `loopback-spi.c` SPI0 source on the Pi
  with the same warnings-as-errors flags; the loopback sender has not yet run.
- `test-analyze.py` passes complete, gapped and implausible-command controls.
- Over a pinned-host-key SSH session at `pi@192.168.0.27`, a no-wire probe
  opened RP1 PIO, claimed a state machine, configured DMA, and printed `READY`.
  Interrupting it removed the incomplete raw file and left GPIO17, 22 and 27
  in `no pn` (no function, no pull) state. This avoids biasing a live bus after
  exit and checks software setup and cleanup,
  **not** sampling accuracy or safety of physical wiring. No Pi-only loopback
  or BC250 SPI trace exists yet.

## Physical wiring for a future board capture

Disconnect the CH347 and all programmer/power leads from J4004. Power down
both systems before wiring. Connect only four signals with female-to-female
leads; do **not** connect either device's 3.3 V pin:

| BC250 J4004 signal | Pi 5 GPIO | Pi physical pin |
| --- | --- | --- |
| CS# | GPIO17 | 11 |
| SCLK | GPIO27 | 13 |
| MOSI | GPIO22 | 15 |
| GND | GND | 14 |

Check the [J4004 orientation and signal layout](../../docs/pi-j4004.md) against
the board's white pin-1 marker. That linked guide's **six-wire programming
pinout does not apply** to this passive capture. The Pi 5 GPIOs must be
confirmed unused/input before connection. Check that the board's J4004 VCC is
about 3.3 V relative to J4004 GND during a normal standalone power-on, then
power it down before wiring. Only the BC250 should power its flash. The Pi
shares ground and listens; it must not supply J4004 VCC. Keep the Pi powered
whenever the BC250 is powered; power the BC250 down before the Pi. This
four-wire setup cannot capture MISO and cannot substitute for the active
interposer. Do not connect the Pi's SPI0 programmer pins to the live bus.

## Pi installation and bench test

The source, pinned PIOLib snapshot and binaries are installed at
`/home/pi/bc250-spi-capture-20260925`. To reproduce the build from a fresh
copy, obtain the pinned upstream PIOLib source. The Pi has `gcc` but not
`cmake`, so this uses a direct compile of the three PIOLib source files:

```sh
git clone https://github.com/raspberrypi/utils.git /tmp/bc250-rpi-utils
git -C /tmp/bc250-rpi-utils checkout ebc4a56bac3a896d5c14e56fe27dcd6cb36dd373
gcc -std=gnu11 -O2 -Wall -Wextra -Werror \
  -I/tmp/bc250-rpi-utils/piolib/include capture.c \
  /tmp/bc250-rpi-utils/piolib/piolib.c \
  /tmp/bc250-rpi-utils/piolib/pio_rp1.c \
  /tmp/bc250-rpi-utils/piolib/library_piochips.c \
  -lpthread -o bc250-spi-capture
gcc -std=gnu11 -O2 -Wall -Wextra -Werror loopback-spi.c -o bc250-loopback-spi
```

Check that `/dev/pio0` and `/dev/spidev0.0` are available. For a **Pi-only
loopback**, disconnect all BC250/CH347 leads, power the Pi off, and join these
three pairs of header pins with female-to-female jumpers:

| Pi SPI0 output | Pi PIO input |
| --- | --- |
| GPIO8 / physical 24 (CE0) | GPIO17 / physical 11 (CS#) |
| GPIO11 / physical 23 (SCLK) | GPIO27 / physical 13 (SCLK) |
| GPIO10 / physical 19 (MOSI) | GPIO22 / physical 15 (MOSI) |

They already share ground internally. Power the Pi on. With **only those three
Pi-to-Pi jumpers attached**, run:

```sh
cd /home/pi/bc250-spi-capture-20260925
python3 bench.py --pi-only-wired --hz 1000000
```

`bench.py` refuses to drive SPI0 without the explicit wiring flag. It arms the
capture, waits for `READY`, sends two complete passes of each key-database
body and filler reads, then checks all 2,300 captured command words against
the expected sequence. It keeps a private raw trace and JSON report under
`/tmp/bc250-pi-loopback-*`, and interrupts a stuck capture. **This runner has
not yet been tried with physical jumpers.** Repeat at 10, 25 and 50 MHz only
if each lower-rate run matches exactly; reject the Pi method if coverage
degrades. This loopback tests word ordering and command capture, but not the
BC250's wiring, timing or MISO.

Remove the loopback jumpers with the Pi powered off. For the board trial, start
`bc250-spi-capture` while the BC250 is off, wait for `READY`, then power on the
BC250 normally:

```sh
./bc250-spi-capture --output boot-spi.raw --words 16000
python3 analyze.py boot-spi.raw --json boot-spi.json
```

The program creates a new output file and will not overwrite an existing
capture. It waits for exactly the requested number of 32-bit commands; if the
boot produces fewer, it may block, and an interrupted transfer is not usable.
`--words` can be reduced for a preliminary shorter capture. `--mode3` is
available if a controlled test shows mode 3; mode 0 is the default. The raw
binary file is a sequence of little-endian `uint32` values whose high byte is
the sampled opcode and low three bytes are the sampled address. It may contain
board boot addresses, so keep it private until reviewed.

`analyze.py` reports contiguous complete body reads for the type-50 and
type-51 databases, their start/end command indexes, and the command count
between successive pass endpoints. These are observed counts, **not** safe
interposer switch settings: lost commands, other transactions and the absence
of CS-high timing could make a hardware count wrong. It also flags missing
passes or implausible opcode ratios. A
short trace, dropped commands, unknown SPI mode or shorter-than-32-bit
transactions can produce false gaps. Even two complete command passes do not
establish which bytes the flash returned, which pass the PSP used, or whether
video firmware authenticates. The next step after a good trace is an isolated
external interposer trial and then a real decoded-frame test.
