# BC250 Pico 2 implementation

Two Pico 2 UF2 images and their host tools are prepared. The passive v0.2 image
has booted on the physical Pico and passed its full 393,248-byte USB pattern/CRC
test after correcting the first capture's buffering bug. Two passive reboot
captures now show the same 2,133 complete reads, all matching the ROM, at about
**33.27 MHz SPI**. The passive Pico ran at **150 MHz**. The current interceptor fails
the measured timing, including an offline 480 MHz replay; see the
[measurement report](../../docs/pico2-measured-timing.md). It remains locally
tested only. Start with the
[wiring guide](../../docs/pico2-wiring.md), which includes passive, isolated
bench and later CS#-switch connections.

The Pico will be hosted by the Pi 5. The [Pi quick-start](../../docs/pico2-pi-start.md)
uses its installed ARM64 picotool and included working-ROM reference, so
flashing, capture collection and initial decoding can all run on the Pi.

An optional passive v0.3 address-hunt candidate is staged separately under
`output/pico2/candidates/hunt-v03/` and on the Pi in the same relative path.
It has been built, checked against recorded edges, flashed and USB-tested
with all GPIO leads removed. It then measured the key, TOS and driver read
locations with the five passive wires attached. Four raw windows cover all
318 changed four-byte words at least once, each with the working-ROM reply.
The main two-image kit still contains the previous tested passive v0.2.
The [measurement report](../../docs/pico2-measured-timing.md) records this
candidate and the isolated 200/480 MHz reply models. Neither is an active board
interceptor.

A separate `output/pico2/candidates/fast-bench-v01/` image is linked into
RP2350 **RAM**, so `picotool load -v -x` can execute it without another Pico
flash write. It runs the preselected reply PIO at an experimental 200 MHz on
the isolated Pi 5 SPI0 bench only. Its [bench guide](../../docs/pico2-fast-bench.md)
requires every BC250 lead removed and the BIOS chip left untouched. The image
was loaded and verified in Pico RAM on 2026-09-26. After the user corrected
the jumper orientation, it returned all 128 words correctly at requested Pi
SPI speeds of 1, 5, 10, 20 and 33 MHz, and all 1,024 words at requested
33 MHz. DMA completed in every passing run. These are isolated Pi functional
checks, not an analogue BC250 timing qualification.

The `output/pico2/candidates/select-bench-v01/` image combines the
preselected PASS/PATCH route and reply in one 30-instruction PIO state machine.
It has passed modeled 200 MHz replay around five measured read windows and
the 48 local tests. On the isolated Pi, v0.1 passed mixed routing and replies
through requested 20 MHz, but the GP6 first-clock observer found intermittent
route errors at requested 33 MHz while all PATCH replies remained correct.
The `select-bench-v02/` RAM-only diagnostic sampled GP6 on the first and
second clocks. At requested 33 MHz the failures were PASS rows, with GP6
high on both sampled clocks; a 1,024-read run failed on 229 PASS rows despite
a requested 1 ms extra gap. The `select-bench-v03/` candidate preselects PASS
while host CS# is idle. Its 32-instruction PIO passed 48 local tests and 50
measured-edge replay cases. The physical v0.3 run still failed on 14 PASS
rows in a requested 33 MHz run. `select-bench-v04/` keeps that selector but
adds an idle USB peek of the GP6 pad and PIO output latch. Its 1,024-read
physical run at requested 33 MHz found 225 PASS rows where PIO reported
output-low/enable-high but the GP6 pad stayed high; a 1,024-read 20 MHz run
passed. A RAM-only `select-bench-v05/` candidate reads GPIO6's function mux,
final output-to-pad, output-enable-to-pad and pad configuration.
The user measured GP6→3V3 open and GP6→GND as 473 Ω on the 2 kΩ range.
The v0.5 candidate was subsequently loaded into Pico SRAM. Its 100 kHz and
20 MHz controls passed, but 244 PASS rows failed in a 1,024-read requested
33 MHz run, starting at row 51. The PIO output and final `OUTTOPAD` were low,
output enable was on, and the pad input remained high. The GPIO mux and
override registers were normal. A same-selector GP7/pin-10 comparison is
built and staged on the Pi at `select-bench-gp7-v05/`. It passed the same
1,024-read requested-33-MHz run with zero route, idle-pad or PATCH-reply
errors. That supports moving the eventual flash-CS output to GP7, but the
current active interceptor still uses GP6 and is not board-ready.
An isolated v0.6 GP7 candidate adds a PIO1/DMA capture of each 32-bit SPI
command for **post-run** comparison with the Pi script. It is staged at
`select-commands-gp7-v06/`; it cannot reject a wrong command before the
current transaction drives data, and it has no board-arm command.
It has now passed the 1,024-read requested-33-MHz isolated run with every
command, route and PATCH reply correct. An injected one-bit address error was
reported on the exact row in a separate low-speed negative control. A
real-time fault path and complete board profile are still missing.
All candidates use the same five isolated Pi jumpers
with **GP6 / Pico pin 9 entirely unconnected**; the GP7 comparison also
requires **GP7 / Pico pin 10 entirely unconnected**.
None has an address check or BC250 board-arm command. The
[measurement report](../../docs/pico2-measured-timing.md) records the results
and limits.

| Artifact | Purpose | BC250 connection |
|---|---|---|
| `bc250_passive.uf2` | Input-only four-channel raw capture, USB transfer with CRC32 | Five passive wires; BIOS chip untouched |
| `bc250_interceptor.uf2` | Command/address-checked CS routing and SRAM replies; real signed words in a synthetic replay | **None**; isolated Pi 5 only; keep GP6 disconnected |
| Private `overlay.bin` | Original/patched type-50 database and signed TOS/driver segments | Not a firmware/UF2; board timing/profile not ready |

Pin contract: GP2=host CS#, GP3=SCLK, GP4=MOSI, GP5=MISO. The passive image
leaves GP6 and GP7 as inputs. The existing experimental interceptor still
drives GP6 only after `arm-isolated`; its eventual board version must be
rebuilt for GP7 and qualified before attaching any flash CS#. UART
stdio is disabled. The passive build forces output enable off on GP2–GP6
and has no PIO output instructions. Its default clock is the stock 150 MHz.

## Verify USB transfer before connecting GPIO

Passive v0.2 fixes mixed libc/SDK output buffering that could leave a capture's
last binary bytes unsent. It uses direct SDK output for headers, data and the
trailer, with newline translation disabled. After flashing over USB, leave
GPIO disconnected and run on the Pi:

```sh
python3 capture.py usb-test --port /dev/ttyACM0 --output captures/usb-selftest-v02.bcraw
```

This transfers the full 393,248-byte packet and checks every payload byte plus
its CRC. It touches no SPI pins. The synthetic flag `0x80000000` prevents it
from being accepted as a board capture. Status includes `transport=direct` and
`usb_test=1`. Failed USB transfers now preserve received bytes in a `.partial`
file for diagnosis, rather than losing all data.

## First passive capture

Hold BOOTSEL while connecting the **unwired** Pico by USB and copy
`bc250_passive.uf2` onto its `RP2350` drive. After reboot, use the actual
`/dev/serial/by-id/...` USB serial path (`ls /dev/serial/by-id/`). Make the five
passive connections in the guide with both devices unplugged, power the Pico,
then run on the Pi/workstation:

```sh
python3 capture.py collect --port /dev/ttyACM0 --output boot-0.bcraw
```

Wait for `ARMED`, then power the BC250 normally. No board command or power
operation is performed by this script. A capture times out after 60 seconds;
Ctrl-C cancels. Decode on the workstation against the known working backup:

```sh
python3 tools/pico2-interposer/capture.py decode boot-0.bcraw \
  --rom output/pico2/private-20260926/CLEAN-working-backup.rom \
  --output boot-0.json
```

The buffer holds 786,432 four-bit samples: about **5.24 ms at 150 MHz**.
`--skip N` skips N complete CS# assertions before capturing the next one;
several normal boots with different skips may be needed to reach key/TOS
reads. The initial/final partial transactions are excluded. The raw decoder
handles both modes 0 and 3, short commands, full MISO data and optional ROM
comparison. An invalid CRC rejects the file; PIO/DMA stalls and low sampling
margin are reported. At 50 MHz SPI, 150 MHz sampling gives only three samples
per clock and is insufficient for a timing approval. This capture is a
measurement aid, not proof of a working active interposer.

## Check repeated captures on the workstation

Collect the same window during two separate normal boots, using the same
`--skip` value and different output filenames. Arm before powering the BC250
on each boot. Then compare the raw files against the working ROM:

```sh
python3 tools/pico2-interposer/qualify_capture.py boot-0a.bcraw boot-0b.bcraw \
  --rom output/pico2/private-20260926/CLEAN-working-backup.rom \
  --output boot-0-comparison.json
```

The script rechecks raw CRCs and ROM bytes, compares the common sequence of
complete reads, and reports minimum clock, CS setup/hold and CS-high intervals.
It subtracts one sample from each interval to account for sampling uncertainty.
For example, a sampled 100 ns half-cycle is too close to the model's 100 ns
limit to establish margin. It rejects discontinuities, conflicting captures,
unsupported read shapes/modes and intervals outside the modeled bounds.
`--commands N` explicitly limits the common prefix; any unexamined tail is
reported. Identical raw files cannot establish independent repeated boots.

A successful exit means only that the compared window passed this digital
screen. It does **not** identify copy/check passes, prove full boot coverage,
measure analogue output handover, or generate an armable board profile. The
first and last partial transactions are excluded, and an unobserved CS-high
gap before the first complete read is reported as missing. Captures from
different skip values must not be silently joined as one continuous trace.

## Interceptor: isolated bench first

Disconnect the BC250 and CH347 completely. The interceptor image also runs
the isolated Pi-to-Pico bench; no third UF2 is needed.

The prepared interceptor contains **638 synthetic transactions covering every one
of the signed pair's 318 changed words**. Its compressed command runs and replacement words use 2,468 bytes of SRAM.
A dedicated core expands the runs into the PIO FIFO ahead of each reply. It first searches for a PASS anchor with MISO forced off, ignoring
earlier unrelated or short requests. After that read completes, it checks the
next PASS guard read and remaining sequence strictly. It compares the complete
command/address before selecting a patch,
leaves ordinary reads with the original chip, and stops patching on a wrong
command or transaction length. A separate PIO state machine mirrors CS# after
the finite script ends. The PIO compares the header and starts a prepared reply without a CPU
interrupt; the CPU must keep its FIFO supplied, so feed latency still needs
physical measurement.

Use the same isolated Pi wiring, with GP6 left disconnected. Flash `bc250_interceptor.uf2`
with GPIO leads removed, reconnect the isolated bench, and run:

```sh
python3 router_bench.py --port /dev/ttyACM0 --isolated-pi-wiring \
  --profile router_profile.json
```

Start at 250 kHz. Later runs can use `--speed-hz 1000000` through `5000000`;
reset the isolated Pico between runs. `--wrong-address-after-anchor` is a negative
test that must latch an address fault. The runner also sends three unrelated or
short preamble transactions, which must be skipped without substitution.
With no original chip connected, this
bench checks substituted words and status; it cannot check original-chip MISO
or its electrical release. The digital model includes a separate original flash.

**This is not a captured BC250 boot profile.** The firmware has no board-arm
command. The modeled envelope is mode 0, exactly 64 clocks, at most 5 MHz,
at least 100 ns clock half-period/setup and 1 µs CS-high gaps. CPU response to
faults and analogue timing still need measurement; 25 MHz fails the local model.
See [validation and remaining measurements](../../docs/pico2-router-validation.md).

## Private payload preparation

`prepare_private.py` retains a new RSA-2048 signing key, re-signs the pinned
TOS and driver images, checks four native copy/check model cases and twenty
TOS component cases, then stores mode-0600 files inside a mode-0700 directory.
It refuses to overwrite an existing key/bundle. The first retained bundle is
`output/pico2/private-20260926/`, excluded from Git by `output/`.

Its `overlay.bin` is **198,240 bytes**: two type-50 variants, patched TOS and
re-signed driver entries. It preserves the original type-51 keys and includes
the tested TOS routine that appends the authentic VCN key in modeled RAM.
The key stays in `signer-private.pem`; only public material/signed components
belong in the Pico image. The full patched ROM is invalid by itself and must
never be programmed into the BC250 EEPROM.

The Pico router still needs a trace-derived profile identifying each module
read and the correct type-50 copy/check pass. No such profile is embedded and
no approved board UF2 is supplied. The address-checking router candidate is
implemented and locally tested; timing on real hardware remains to be measured.

## Build and local checks

Built with Pico SDK **2.3.1** (`079c6f39023649b154152db30f1d781e884879bc`), its
pinned TinyUSB submodule, and Raspberry Pi's **v2.3.1-0 RISC-V toolchain**.
The Pico 2 uses its supported Hazard3 core; PIO operation is independent of
whether the CPU runs Arm or RISC-V code. The passive and legacy router images
use 150 MHz; the two isolated RAM bench images explicitly set 200 MHz and
1.20 V for testing.

```sh
cmake -S tools/pico2-interposer -B output/pico2/build -G Ninja \
  -DPICO_SDK_PATH=/tmp/bc250-pico-sdk -DPICO_PLATFORM=rp2350-riscv \
  -DPICO_TOOLCHAIN_PATH=/tmp/bc250-pico-tools/riscv-toolchain-16-x86_64-lin \
  -Dpicotool_DIR=/tmp/bc250-pico-tools/picotool-2.3.1-x86_64-lin/picotool \
  -DBC250_ROUTER_PROFILE_HEADER="$PWD/output/pico2/router-v3-20260926/router_profile.h" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build output/pico2/build
PIOASM=output/pico2/build/pioasm/pioasm \
  BC250_OVERLAY_MANIFEST=output/pico2/private-20260926/MANIFEST.json \
  python3 -m unittest discover -s tools/pico2-interposer -p 'test_*.py' -v
```

The tests exercise byte order in both SPI modes, short-command resynchronizing,
CRC/length rejection, wrong-ROM detection, sampling warnings, and execute the
**assembled** reply PIO against a synthetic SPI master at 250 kHz–1 MHz with
an input synchronizer delay. They check output release on an aborted data
phase. These are local logic checks, not physical/analogue timing tests.
The router tests also execute its three assembled PIO programs against a
separate flash model, reject wrong addresses/opcodes, check every short length,
and replay the retained signed pair. `verify_router_build.py` checks that the
linked ELF has the same PIO instructions and exact command/reply words as the
model, and that the compressed tables and complete feed/fault loop are in SRAM.
All 44 local tests pass. The same C stream decoder also expands a 97,354-read
full-object stress profile exactly; its 2,636-byte compressed representation
replaces 1,168,248 bytes of literal triples. This is a synthetic capacity check,
not a measurement of the BC250 boot sequence.
The search/boundary decisions are compiled from the same `router_policy.h` as
the firmware and coupled to the PIO model. Injected monitor latencies exercise
short requests, insufficient gaps, bad anchor lengths, and a wrong guard read;
they do not establish the physical RP2350 monitor's execution time.

The earlier reply-only experiment remains in source for development and is
excluded from the normal build/kit (`BC250_BUILD_LEGACY_BENCH=ON` enables it).
The normal workflow uses only capture and interceptor images.

`patch_coverage.py` checks the four decoded physical traces against the two
retained ROMs and manifest, and writes a report without exposing the private
signer. It confirms address/byte coverage only; the active CS selector and
physical response timing are still untested. Leave the BIOS chip leg intact.

Official sources: [SDK release](https://github.com/raspberrypi/pico-sdk/releases/tag/2.3.1),
[toolchain release](https://github.com/raspberrypi/pico-sdk-tools/releases/tag/v2.3.1-0),
[Pico 2 datasheet](https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf).
