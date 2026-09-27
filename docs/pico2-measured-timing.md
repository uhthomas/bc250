# First measured BC250 SPI traffic

2026-09-26. After the user corrected a one-pin wiring offset, two independent
software reboots produced repeatable passive captures. The Pico runs passive
v0.2 at **150 MHz**, with its bus outputs disabled. The BC250 boots and returns
over SSH with these wires attached. No BC250 EEPROM programming or physical
Pico overclock was performed during these measurements.

| Observation | Capture A | Capture B |
|---|---:|---:|
| Raw duration at 150 MHz | 5.24288 ms | 5.24288 ms |
| Complete transactions | 2,133 | 2,133 |
| Command / data length | `03`, four bytes | `03`, four bytes |
| SPI idle clock | Low | Low |
| Reads differing from working ROM | 0 | 0 |
| Mean clock from sampled periods | 33.271848 MHz | 33.271354 MHz |
| Shortest sampled CS-high gap | 353.3 ns | 353.3 ns |
| Shortest sampled CS-to-clock setup | 40 ns | 40 ns |
| DMA/PIO error flags | 0 | 0 |

All 2,133 complete command/data pairs occur in the same order in both captures.
Each trace also has one leading partial transaction. The first complete read
is at `0x821004`, the last at `0x823754`; this is an early bootloader window,
not the key-database substitution window. The trace does not establish the
full cold-boot sequence or distinguish the target copy/check passes.

Clock periods alternate between four and five samples. Taking only their
median would misleadingly report 30 MHz. `capture.py` now also reports the
mean period's frequency and the sample-count histogram. The sample resolution
is 6.67 ns; this is not an analogue timing measurement. Data changes coincide
with sampled rising clocks 2,492 and 2,516 times respectively, so input setup
margin remains unresolved even though all complete read bytes match.

## Current interceptor result

`qualify_capture.py` rejects both recordings for the current 150 MHz router.
Its tested conditions require SPI at most 5 MHz, at least 100 ns clock
half-period/setup and 1 microsecond CS-high gaps. The conservative bounds from
these samples are 346.7 ns CS-high and 33.3 ns setup, both below those limits.
This is a limitation of the current implementation, not a maximum SPI speed
claim for every Pico design.

The [published BC250 demonstration](https://habr.com/ru/companies/pt/articles/979470/)
sets the Pico to **480 MHz and 1.60 V**. It switches chip selection between two
external flash chips at transaction boundaries; those chips supply the data.
Our one-original-flash design must also supply replacement MISO bits. The
article's clock/voltage settings have not been applied to this Pico.

`replay_capture.py` feeds the recorded CS/SCLK/MOSI edges to the assembled
router model, with a synthetic complemented response on the third of six
reads. At modeled 150, 300 and 480 MHz, the current router fails this test.
At 480 MHz, the first replacement bit is incorrect or has overlapping drivers,
depending on modeled input synchronization/FIFO service. The assumed flash
release time is held at 13.33 ns when scaling the Pico clock; it is not allowed
to shrink with Pico instruction time. This value is a model assumption and
still requires a physical measurement.

The replay assumes exact recorded edge positions, initially filled FIFOs and
no CPU fault monitor. It does not test physical overclock stability. A passing
synthetic slow-bus control and failing fast-bus control are in the test suite.
This points to reducing reply/handover latency or selecting the source before
the transaction, alongside an overclock bench test. It does not prove that a
Pico-only implementation is impossible.

Keep the five passive wires in place. Leave the BIOS CS leg and switch alone
while the response path is revised and tested locally. The remaining capture
work is to cover the key/TOS/driver reads and identify repeatable copy/check
boundaries, then validate the proposed active implementation in isolation.

## Follow-up on 2026-09-26

The existing passive firmware captured later 5.24 ms windows after skipping
20,000, 50,000, 242,900, 256,000, 270,000 and 271,400 transactions.
Every complete `03` read in these windows matched the working ROM and none
of the windows contained a type-50/type-51 key read. The sequence moves from
`0x9c182c–0x9c3a80` at skip 256,000 to `0xe0642c–0xe08680` at skip 270,000.
That jump rules out simply extrapolating a later key address from the earlier
contiguous reads. The exact key copy/check transactions remain unmeasured.

An input-only **passive v0.3 candidate** now includes an address hunter. It
counts every 32-bit command and retains up to 4,096 READ03 hits in the chosen
address interval, preserving transaction indices. Its assembled PIO contains
no pin-output instruction. The compiled 150 MHz RP2350 UF2 and host tool are
staged on the Pi in `candidates/hunt-v03/`. The prior working v0.2 UF2 remains
in the main kit. v0.3 passed its build, 44 local tests and recorded-edge
sniffer simulations. It is now flashed on the physical Pico and has captured
several normal boots. Overflow or FIFO stall invalidates a *complete* read
order report.
The user disconnected all five GPIO leads and put the Pico in USB-only BOOTSEL.
`picotool load -v -x` flashed and verified v0.3. A physical full 393,248-byte
USB pattern/CRC check passed (CRC32 `8b8adcb3`), followed by a one-second
USB-only hunt reporting zero commands, hits, overflow and FIFO stalls.

## Key-region reads measured on the wired board

With the Pico's five passive wires restored, a cold APC boot produced
1,831,150 counted SPI commands in 35 seconds. The broad
`0x9dad00–0x9dc240` hunt retained 4,096 matching reads, overflowed by 544,
and reported zero FIFO stalls. Its saved prefix places the first type-50
region at transaction 10,979 and the first type-51 region at 883,931, but the
overflow means its overall read order is incomplete. The BC250 returned over
SSH after this capture.

Three narrower **warm-reboot** hunts completed without overflow or FIFO stalls:

| Region | Matching reads | Measured sequence |
|---|---:|---|
| Early TOS `0x8eac00–0x8eb000` | 452 | Full first 256 words at 842,646–842,901, followed by 192 overlapping words at 863,278–863,469; four later byte-addressed reads |
| Driver signature `0x99f500–0x99f670` | 128 | 32 words at 815,574–815,605; 32 more at 842,550–842,581; then a full 64-word signature at 842,582–842,645 |
| TOS code `0x8f0800–0x8f0b00` | 384 | 192 words at 848,534–848,725 and the same range again at 869,102–869,293 |

Four CRC-valid 5.24 ms raw captures around the key, driver/TOS boundary,
TOS code and TOS signature contain **7,731 complete four-byte READ03
transactions**, all matching the working ROM, with no PIO/DMA flags. Their
mean SPI clocks are 33.269–33.273 MHz. The key capture includes two reads of
each changed type-50 modulus word. The driver/TOS trace shows a sampled
279 µs CS-high interval between the driver signature and first TOS read;
the first changed TOS entry word follows inside a sequential read. These
sampled edges do not establish analogue handover margin.

`patch_coverage.py` compared the four decoded traces with the retained clean
and interposer-only patched ROMs. Every one of the **318 changed four-byte
words** was observed at least once in a clean-ROM reply: 64 type-50, 190 TOS
and 64 driver words. The reproducible result is
`output/pico2/measured-patch-coverage.json`. This is address/byte coverage,
not proof that every repeated boot pass or the copy/check role of each
type-50 read has been classified.

The experimental preselected `fast_reply.pio` passed all ten digital replay
cases (two synchronizer depths and five sampling phases) at **200 MHz and
480 MHz** around six actual changed-address windows. The 150 MHz key-region
replay failed. The 200 MHz result is model-only and above the RP2350's
[specified 150 MHz limit](https://www.raspberrypi.com/documentation/microcontrollers/microcontroller-chips.html);
the replay assumes the stock flash is already deselected and all reply words
are preloaded. A separate isolated Pi bench has now exercised the Pico at a
**firmware-reported 200 MHz**. After the user corrected the jumper orientation,
the Pico returned all 128 words with zero mismatches at each requested Pi SPI
speed of 1, 5, 10, 20 and 33 MHz; a 1,024-word run at requested 33 MHz also
passed with DMA complete. The Pi's actual wire clock was not measured. These
are reply-engine functional checks, not a qualification of the BC250 timing.
A physical combined-selector test now exists, but its mixed-route high-speed
check fails. A strict address/fault path and analogue handover test are also
still missing. **Do not lift the BIOS CS leg yet.**

An additional model-only `cs_select.pio` takes a preloaded PASS/PATCH choice
before each CS# assertion. Its default or empty-FIFO state keeps the original
flash deselected. At modeled 200 MHz it passed the same six recorded windows
across both synchronizer depths and five sample phases, with the original
flash selected at least 15 ns before the first clock on PASS reads. The
[Macronix specification](https://www.macronix.com/Lists/Datasheet/Attachments/8935/MX25L12872F,%203V,%20128Mb,%20v1.1.pdf)
requires 3 ns CS# setup. The modeled margin excludes GPIO pad delay, signal
integrity and the captured-edge sampling uncertainty. The route FIFO and Pico
MISO enable are assumed preselected; the selector is **not** in a board
firmware image and has not been driven on physical hardware.

The new `fast_select.pio` combines PASS/PATCH CS selection on GP6 and
replacement MISO on GP5 in one 30-instruction state machine. It passed all
ten synchronization/phase cases at modeled 200 MHz around five measured
key, TOS and driver windows, with no modeled overlap between flash selection
and Pico MISO drive. Synthetic tests also moved the PATCH choice through
every position in a six-read window. This is still a **preselected** route;
it has no command/address check. The RAM-only v0.1 isolated Pi bench returned
all PATCH replies correctly and sampled zero GP6 route errors in 128 mixed
transactions at requested 1, 5, 10 and 20 MHz. A 32-read batch also passed
at 20 MHz. At requested 33 MHz, all PATCH replies still matched, but the GP6
first-clock observer found roughly 6–22 route errors per 128 mixed reads,
including with a requested 1 ms extra host pause and with 32-read batches.
All-PASS and all-PATCH runs passed separately in those v0.1 tests. The Pi wire
speed and CS setup were not independently measured. The physical v0.2
diagnostic sampled both first and second clocks. At requested 33 MHz, all 18
bad rows in a 128-read mixed run were PASS reads beginning at index 59; both
samples stayed high. A 128-read all-PASS run had 18 bad tail rows from index
110. With a requested 1 ms extra gap, one 128-read run passed, but a
1,024-read run failed on 229 PASS rows beginning at index 111. All PATCH
data still matched. The first bad row's index varies, but once the failure
appears, subsequent PASS rows are consistently wrong. The cause has not been
proven by this digital pad observer alone.

A v0.3 candidate preselects PASS while host CS# is still high, giving the
original flash's CS# more setup before the first clock. Its 32-instruction
PIO passed 48 local tests and 50 replay cases across five actual key/TOS/driver
windows at modeled 200 MHz. The minimum modeled PASS CS# setup is 345 ns.
The physical v0.3 Pi bench passed 128 mixed reads at requested 20 MHz but
still failed on 14 PASS rows from index 75 onward at requested 33 MHz; both
GP6 samples stayed high and all PATCH replies matched. Preselection alone
did not cure the sustained failure. The Pi reported `throttled=0x0` at that
point. The physical v0.4 RAM-only diagnostic read the GP6 pad and PIO output
latch during host idle before every transfer. Eight reads at 100 kHz and 128
reads at requested 20 and 33 MHz passed. In a 1,024-read mixed run at
requested 33 MHz, **225 PASS rows** failed starting at index 127, every
fourth row. Before each failing transfer, PIO0 reported GP6 output low and
output-enable high, while the pad read high. Both first- and second-clock
pad samples were high too. PIO `fdebug` was zero in the idle peeks, all PATCH
replies matched, and both DMA streams completed. An eight-read 100 kHz run
then passed, followed by a full 1,024-read run at requested 20 MHz with zero
errors. The mismatch depends on speed and run length. It does not establish
whether an external connection, GPIO function/override change, or another
pad fault is responsible. The bench was powered off for a pin-9 visual and
unpowered resistance check. The script still has no command/address check.
GP6 must stay disconnected from the BC250 and any flash chip.

The user reports that nothing visibly touches GP6/pin 9. A v0.5 RAM-only
diagnostic was built to capture the GPIO6 function mux, final
output/output-enable-to-pad, raw input-from-pad and pad isolation registers.
A higher PIO clock would not explain why the pad read high while the PIO latch
was already low before SPI started.

The user then measured GP6/pin 9 with Pi, Pico USB and jumpers disconnected:
GP6→3V3/pin 36 appeared open and GP6→GND/pin 8 read **473 Ω on the 2 kΩ
range**. This excludes a direct low-ohm rail short, but is not enough to
characterize the pad or any external connection. The v0.5 image was loaded
and verified into Pico **SRAM only**. Its 8-read requested-100-kHz and 128-read
requested-20-MHz isolated controls passed. In a 1,024-read mixed run at
requested 33 MHz, **244 PASS rows** failed, beginning at index 51; every
PATCH reply still matched and both DMA streams completed. Before each bad
transfer, PIO0 output and `IO_BANK0.OUTTOPAD` both read low, `OETOPAD` read
high, and the raw `INFROMPAD` read high. GPIO function was PIO0; output and
enable overrides were normal; the pad had output enabled, input enabled,
no isolation and no pulls. Both first- and second-clock observers read high.
The report is `output/pico2/fast-select-v05-physical-20260927.json`.
That narrows the discrepancy to the final pad/physical environment rather
than a changed GPIO mux or PIO output register. It does not distinguish a
damaged pad, external contention, or power/silicon behavior at the experimental
200 MHz setting. A same-firmware **GP7/pin 10** comparison is prepared in
`output/pico2/candidates/select-bench-gp7-v05/` and staged on the Pi.
GP6 and GP7 remain disconnected from the BC250 and flash.

The GP7 variant was then loaded and verified into SRAM. It passed an 8-read
requested-100-kHz control, a 128-read requested-20-MHz control and the same
**1,024-read requested-33-MHz mixed test with zero route, idle-pad or PATCH
reply errors**; both DMA streams completed. The report is
`output/pico2/fast-select-gp7-v05-physical-20260927.json`. The contrast with
GP6's 244 bad PASS rows on the same Pico, wiring and PIO program points to
GP6 or its local physical environment, rather than a general 200 MHz PIO
selector failure. It does not prove GP6 is damaged or establish analogue
handover margin on the BC250. The eventual flash-CS output should move to
GP7/pin 10; the GP7 bench firmware has no address verifier or board-arm path.

An isolated v0.6 GP7 candidate now adds an input-only PIO1 command sniffer and
DMA stream to capture each 32-bit MOSI opcode/address while the proven selector
runs. The firmware compares the captured commands with the test script **after
the run**; this verifies the measurement path but is not a real-time fault
guard. It is built, locally checked and staged on the Pi under
`output/pico2/candidates/select-commands-gp7-v06/`. Its UF2 targets SRAM
only; no board-arm path or BIOS programming is present.

The v0.6 image was then verified in Pico SRAM and passed the 8-read
requested-100-kHz, 128-read requested-20-MHz and **1,024-read
requested-33-MHz** isolated tests. In the long run, command DMA, route-sample
DMA and reply DMA all completed; captured commands, GP7 route, idle pad and
PATCH replies had zero mismatches. The report is
`output/pico2/fast-select-gp7-v06-physical-20260927.json`. A separate
8-read negative control flipped one SPI address bit at index 3, and the
firmware identified exactly `0310000c` expected versus `0310000d` observed.
It still reports this only after the transaction sequence finishes, so a
real-time fault path and a measured BC250 boot profile remain prerequisites
for an active board trial.

After the lifted flash CS# leg was returned to J4004 CS# with a 10 kΩ pull-up,
the BC250 booted in STOCK mode and responded over SSH. The Pico remained on
the isolated Pi bench. A further 1,024-read test at requested 33 MHz flipped
the last address bit in row 511: command capture reported exactly one mismatch,
`031007fc` expected versus `031007fd` observed. All three DMA streams
completed; GP7 route samples and PATCH replies had zero errors. This confirms
the negative control at the faster requested Pi rate, but detection is still
**post-run** and therefore cannot protect a current transaction on the BC250.

## Guarded selector candidate (v0.7, isolated only)

The new `fast_select_guard.pio` fits in exactly 32 PIO instructions. It
preselects the flash CS# route, samples all 32 MOSI command bits on PATCH rows,
compares them with the preloaded expected READ03 command, and only then
enables Pico MISO. A mismatch latches PIO IRQ0 and keeps the flash deselected
and Pico MISO high-impedance until the state machine is reset. PASS rows and
short-command boundaries still need an active fault policy; this is **not** a
BC250 board image.

Against six recorded BC250 windows, the assembled-instruction digital model
passes ten input phase/synchronizer cases per window at a modeled 340 MHz,
both with correct PATCH commands and with one expected-address bit changed
(120/120 cases). The same guarded path misses the first reply bit at modeled
200 MHz; 300 MHz also fails some recorded phases. The model assumes ideal GPIO
outputs and does not measure analogue flash release or board signal quality.
A RAM-only 340 MHz/1.30 V isolated bench UF2 is built and hash-verified on the
Pi under `candidates/select-guard-gp7-v07/`. Its physical Pi bench passed an
eight-read requested-100-kHz control and 1,024 mixed PASS/PATCH reads at a
requested 33 MHz: all three DMA streams completed, with zero route,
command or PATCH reply mismatches. A 1,023-read negative control altered the
final PATCH address from `03100ff8` to `03100ff9`; PIO IRQ0 latched, the
post-run command capture reported that one mismatch, MISO PIO output-enable
was 0, and the GP7 flash-CS# pad was high. These are requested Pi SPI rates;
the wire clock and analogue margin remain unmeasured.

The Pi could not reset the earlier firmware remotely because its USB reset
interface was disabled. One manual BOOTSEL entry installed a persistent
input-only passive image with the Pico SDK vendor reset interface enabled.
Its full 393,248-byte USB CRC self-test passed. `picotool reboot -f -u`
then successfully entered BOOTSEL remotely; the guarded image was verified
and run from SRAM, without another Pico flash write. After the bench tests,
the Pico was rebooted into the passive image, reporting 150 MHz and outputs
off. The BC250 remained on its working STOCK flash path throughout.

`fast_reply.pio` is a separate experimental response engine for a **preselected**
transaction. Its assembled PIO outputs the first MISO bit during the command
phase, before the BC250 samples data. It passes all ten digital timing cases
(two synchronizer depths, five sample phases) on each of the two early boot
recordings at a modeled 480 MHz. That model assumes the stock flash was
already deselected and the response FIFO already filled. There is no matching
chip-select controller, full address verifier, fault path or physical
480 MHz bench result. The BC250-attached passive captures used 150 MHz.

## Evidence and reproduction

Raw files on the workstation are `output/pico2/boot-warm-0a.bcraw` and
`boot-warm-0b.bcraw`; the originals are also in the Pi kit's `captures/`
directory. The working ROM SHA256 is
`f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183`.
Reports are `boot-warm-repeat-qualification.json` and
`recorded-router-clock-replay.json` under `output/pico2/`.

```sh
python3 tools/pico2-interposer/replay_capture.py output/pico2/boot-warm-0a.bcraw \
  --rom output/pico2/private-20260926/CLEAN-working-backup.rom \
  --pioasm output/pico2/build/pioasm/pioasm \
  --clock-hz 150000000 300000000 480000000 \
  --output output/pico2/new-replay-report.json
```

Arming before an APC power cycle initially captured the power-down transition
instead of SPI: one buffer was entirely zero, another had one single-sample
glitch. Skipping one CS event was insufficient. Software reboot avoided this
trigger problem. For a cold capture, power the BC250 off first, then arm, then
power it on; do not assume a fixed skip count removes power-transition noise.
