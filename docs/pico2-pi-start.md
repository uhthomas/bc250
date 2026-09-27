# Pico 2 connected to the Pi 5

The Pi 5 at `192.168.0.27` runs the USB flashing, capture and bench tools.
The prepared kit is `/home/pi/bc250-pico2-20260926`.

**Current state, 2026-09-27:** The Pico's persistent image is input-only
`bc250_passive_usb_reset.uf2`, with vendor USB reset. It currently runs a
RAM-only CS# pass-through diagnostic, with its output cancelled and disabled;
unplugging USB returns it to the passive image on the next boot. The prepared
pass-through image and [board wiring](pico2-cs-pass.md) are in
`candidates/cs-pass-v02/`. The guarded GP7 PATCH candidate remains an
isolated bench experiment in `candidates/select-guard-gp7-v07/`.

For the first BC250 capture, the connections are:

```text
Pi 5 USB port ── USB cable ── Pico 2 ── five signal/ground wires ── BC250 J4004
```

The Pi's GPIO header is **not connected** during this capture. Its SPI0 header
is used only for the later isolated Pi-to-Pico bench, with the BC250 detached.
See the [wiring guide](pico2-wiring.md) for the five exact pin connections.

## 1. Plug in and flash the Pico over SSH

Keep all Pico GPIO leads disconnected. Hold the Pico's BOOTSEL button while
plugging its USB cable into the Pi 5, then release BOOTSEL. From an SSH session
as `pi` on the Pi 5:

```sh
cd /home/pi/bc250-pico2-20260926
sha256sum -c SHA256SUMS
/home/pi/.local/bin/picotool info --vid 0x2e8a --pid 0x000f
/home/pi/.local/bin/picotool load -v -x bc250_passive.uf2 --vid 0x2e8a --pid 0x000f
ls -l /dev/serial/by-id/
```

`picotool` 2.3.1 is installed for ARM64 and uses the Pi's existing USB access
rules. No desktop, mounted USB drive or `sudo` is needed. The load command
verifies the Pico's flash contents, then starts the capture firmware. It only
targets the RP2350 BOOTSEL USB device; it does not access the BC250 EEPROM.

Before connecting any GPIO leads, test the full USB transfer with the actual
serial path from the listing above:

```sh
python3 capture.py usb-test --port PICO_SERIAL_PATH --output captures/usb-selftest-v02.bcraw
```

This checks a full 393,248-byte packet and its CRC without accessing SPI. The
synthetic test file is marked as such and must not be treated as a boot trace.
Passive v0.2 corrects a buffering bug found during the first hardware capture.
Complete this test before attaching J4004.

## 2. Connect the passive wires and capture

Unplug the Pico USB cable and BC250 PSU, then make the five connections in the
wiring guide. Reconnect Pico USB to the Pi, leaving the BC250 off for now.
List `/dev/serial/by-id/` again and use the Pico's actual path below (replace
`PICO_SERIAL_PATH`; `/dev/ttyACM0` also works if it is the only Pico):

```sh
cd /home/pi/bc250-pico2-20260926
python3 capture.py collect --port PICO_SERIAL_PATH --output captures/boot-0a.bcraw
```

Wait for `ARMED`, then power the BC250 normally. The capture writes to the Pi.
The script checks that the Pico is running the input-only firmware before
arming. It does not switch board power. For the repeat measurement, turn the
BC250 off, run the same command with `captures/boot-0b.bcraw`, wait for `ARMED`,
then power the BC250 again. Leave the Pico powered while attached to the board.

Two software-reboot captures now work with the corrected wiring and show
about 33.27 MHz SPI; see [measured timing](pico2-measured-timing.md). Arming
before a complete APC off/on cycle caught the power-down transition instead
of boot traffic, even with `--skip 1`. For a cold capture, turn the board off
**before** arming. A software reboot after `ARMED` avoids this power-edge
trigger and was used for the first repeatable windows.

The raw window is about 5.24 ms. Both captures must use the same `--skip` value
(default 0). Capturing additional windows will be guided by the first results.
The collector refuses to overwrite existing files.

## 3. Decode and compare entirely on the Pi

The hash-verified working BIOS reference is included for read comparisons:

```sh
cd /home/pi/bc250-pico2-20260926
python3 capture.py decode captures/boot-0a.bcraw \
  --rom CLEAN-working-backup.rom --output captures/boot-0a.json
python3 qualify_capture.py captures/boot-0a.bcraw captures/boot-0b.bcraw \
  --rom CLEAN-working-backup.rom --output captures/boot-0-comparison.json
```

This checks the read sequence, original data and sampled timing. It does not
turn a short capture into an approved board profile. The signing key stays on
the workstation; it is not required for capturing or testing on the Pi.

## Optional address hunt after the measured 33 MHz capture

The prepared v0.3 candidate records matching command addresses across a
normal boot. It is staged at
`/home/pi/bc250-pico2-20260926/candidates/hunt-v03/` and is now **flashed on the
Pico**. Its full USB test and USB-only no-bus hunt passed. The main kit retains
the previous working v0.2 UF2. The address hunter runs at 150 MHz and leaves
GP2–GP6 as inputs with output enables forced off.

If reflashing it, power off the BC250, unplug Pico USB and remove all
five J4004 signal/ground leads from the Pico. Hold BOOTSEL while reconnecting
the Pico USB to the Pi. Once `picotool info` sees a single RP2350 BOOTSEL
device, load the candidate using its absolute path and `picotool load -v -x`.
First run `capture.py usb-test` with **only USB attached**. This has passed for
v0.3. Next unplug the Pico, reconnect the same five passive wires, reconnect
Pico USB, and arm `hunt.py` while the BC250 is off. Start the board through
the APC outlet after `ARMED HUNT`:

```sh
cd /home/pi/bc250-pico2-20260926/candidates/hunt-v03
python3 hunt.py --port /dev/serial/by-id/usb-Raspberry_Pi_Pico_DDD62380365DE594-if00 \
  --first 9dad00 --last 9dc240 --timeout 35 \
  --output /home/pi/bc250-pico2-20260926/captures/key-address-hits.json
```

The host output includes total command count, saved hits, overflow and PIO
FIFO-stall indicators. A hit report with either nonzero overflow or stall
cannot establish the read order. This step requires **no soldering** and no
BC250 BIOS write. Keep GP6 disconnected.

This step has now run on the wired board. The broad cold-boot hunt overflowed,
but three narrower warm-reboot hunts had no overflow or FIFO stalls. Four raw
capture windows then covered every changed interposer word with ROM-matching
data. See [measured timing](pico2-measured-timing.md) and
`output/pico2/measured-patch-coverage.json` on the workstation. The Pico is
still running the input-only v0.3 image at 150 MHz; no CS# rework is ready.

## 4. Isolated bench, after capture

Use the Pi-to-Pico wiring table in the wiring guide, with **all BC250 and
Waveshare leads removed and Pico GP6 disconnected**. Reflash only with Pico
GPIO leads removed, using BOOTSEL again:

```sh
cd /home/pi/bc250-pico2-20260926
/home/pi/.local/bin/picotool load -v -x bc250_interceptor.uf2 --vid 0x2e8a --pid 0x000f
```

Disconnect USB, connect the isolated bench wires, reconnect USB, then run:

```sh
python3 router_bench.py --port PICO_SERIAL_PATH --isolated-pi-wiring \
  --profile router_profile.json
```

The supplied interceptor uses the synthetic test profile. It is not yet an
active BC250 trial image. The initial bench uses 250 kHz; later speed and fault
tests depend on those results. Return to the passive image before reconnecting
the BC250 for further measurements.

Flashing commands follow the [official picotool documentation](https://github.com/raspberrypi/picotool).
