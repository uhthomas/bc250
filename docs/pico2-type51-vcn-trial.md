# Pico 2 type-51 VCN-key trial (2026-09-27)

The six-wire Pico 2 interposer can supply the authentic Cezanne VCN2 usage-6
record to the BC250's first type-51 key-database read while leaving the later
integrity read on the original flash. The board boots Fedora under that swap.
A bounded live PSP test then reaches VCN firmware header bounds validation:
the VCN-key control changes from the original `0xffff0008` to `0xffff300f`,
while the graphics-key negative control remains `0x80000205`. This is direct
evidence that the PSP recognizes the substituted usage-6 record. It does not
establish a running VCN decoder.

The lossless [SPI trace](pico2-full-boot-trace.md) has 1,832,116 commands.
From the first type-50 anchor at command index 11,172, each identical boot
pass includes 873,480 commands through both type-51 reads. The first type-51
run starts at relative row 872,744 and reads 336 four-byte words from
`0x9dbb00` through `0x9dc03c`. The second starts at row 873,080 and reads
400 words from `0x9dbc00` through `0x9dc23c`. The changed usage-6 record is
inside both runs. [The generator](../tools/pico2-interposer/prepare_type51_profile.py)
pins the trace and clean/patched ROM hashes, checks both passes and all run
boundaries, then builds private RAM-only profiles. The `type51-vcn-copy` profile
has 69 changed four-byte replies per pass; it never queues them for the hash
read. The altered ROM is invalid as a standalone BIOS and was **never**
written to the board's EEPROM.

| Trial | Pico guarded replies | Fedora | PSP result |
| --- | ---: | --- | --- |
| Original-word control at `0x9dbda8` | 2/2 verified | Booted | No firmware request |
| VCN-key copy, normal kernel | 138/138 verified | Booted | Normal driver has no VCN block |
| VCN-key copy, negative authentication diagnostic | 276/276 cumulative | Booted | VCN-key malformed header `0xffff300f`; graphics-key control `0x80000205` |
| VCN-key copy, unmodified `navi10_vcn.bin` request | 414/414 cumulative | Booted | `LOAD_IP_FW` type 13 returned `0x80000029`; VCN MMIO still `0xffffffff` |
| VCN-key copy, one signed firmware byte changed | 138/138 on a fresh boot | Booted | `LOAD_IP_FW` type 13 again returned `0x80000029` |
| Tampered RLC then VCN, same PSP ring | 138/138 | Booted | RLC type 8: `0xffff3072`; VCN type 13: `0x80000029` |
| Tampered VCN payload as type 19 | 138/138 | Booted | Command timed out; no type-13 request followed |
| Tampered VCN type 13 before graphics firmware load | 138/138 per boot, three boots | Booted | `0x80000029` with completed transport; MMHUB write fault also seen with VRAM staging |

All guarded sessions reported zero profile mismatches, PIO faults, RX stalls
and late decisions. The type-51 original-word control and key-swap boots
completed two matching command passes each. The Pico output enable was off
outside each selected response. Each experimental UF2 ran from RP2350 SRAM;
neither Pico flash nor BC250 BIOS flash was programmed during these trials.
Private UF2s, headers and raw evidence are under ignored `output/pico2/`.

The PSP requests used separate one-time diagnostic boots. VCN startup remained
disabled. Each runner applied the known clock/power preconditions and restored
the controls afterward. The unmodified firmware request returned `-EIO` to
userspace because its raw PSP status was nonzero; its runner's final nonzero
exit also reflects the previously measured `0x53` to `0x51` status-bit
settling during restore. The later [signed-byte control](../tools/vcn-psp-diagnostics/README.md)
copied the pinned `navi10_vcn.bin` payload into kernel memory, changed only
byte `0x6147f` (inside the signed body), and submitted that invalid copy to
the PSP. Its unchanged `0x80000029` response means the response either occurs
before signature verification or masks a later verification result. The
offline native type-13 model predicts `0xffff3072` for this mutation, but its
hardware/OS services are modeled; it does not explain the live response.
No VCN register became accessible. The stock Fedora
7.2.5 amdgpu driver still registers eight IP blocks with no VCN block, and
`vainfo --display drm --device /dev/dri/renderD128` fails to initialize
radeonsi. No frame was decoded in hardware.

All one-time boot entries were consumed and removed. The board was returned
to the original flash with Pico `arm-pass`, MISO output disabled. The next
work is to localize `0x80000029` in the installed PSP's type-13 path or its
command-response layer, then determine the firmware/power requirements before
attempting driver startup.
Do not infer that a low byte of `0x29` is a bootloader POST code: this result
is a command-response status from a different interface.

A later RAM-only control changed a TOS hook's read address from the old
`0x10784000` fixture to `0x07784000`, the destination calculated by an earlier
native allocator audit. The Pico completed and verified both full SPI passes,
but Fedora did not boot. This shows the modeled allocator address alone does
not establish a safe dereference at the chosen TOS entry point. The full
key-append hook was not attempted. The Pico was reloaded into `arm-pass` and
the board power-cycled to recover the original-flash path.

## Update: early PSP and memory-boundary trials

In one guarded boot the same PSP command ring rejected a signed-byte-tampered
graphics RLC image with `0xffff3072`, while the tampered VCN image returned
`0x80000029`. A type-19 request using the tampered VCN payload timed out, so
it cannot serve as a signature control. An early type-13 probe, placed after
PSP TMR setup but before graphics firmware loading, returned `0x80000029` as
well. Later graphics firmware loading is therefore not required for this
response.

The early type-13 request coincided with an MMHUB VMID-0 write fault. Using
the kernel's `debug_mask=8` VRAM firmware-buffer option did not change the PSP
status or remove the fault. The address-logged VRAM trial put firmware staging
at `0xf41fd00000`, the command buffer at `0xf4007ed000`, the fence at
`0xf4007ee000`, and TMR at `0xf41f400000`. All are inside the reported VRAM
range `0xf400000000..0xf41fffffff`. The fault was at `0xf4cec2e000`, outside
that range and the reported GART range `0..0x1fffffff`. Its address matches
none of those logged buffers. The fault and PSP response are closely timed;
the logs do not establish which operation caused either result. A recovered
full kernel log from an earlier late VCN request contains the same
`0x80000029` result and **zero MMHUB page faults**. The early fault is not
necessary for this PSP status. Raw logs and runner journals are under ignored
`output/pico2/type51-live-20260927/`.

The early-probe boot ended with `amdgpu` loaded but the GPU unbound after the
deliberate abort. A later signer-only RAM profile, which changed the type-50
modulus and re-signed the otherwise identical TOS and driver bodies, booted
Fedora with two completed SPI passes and 416/416 replies verified. No BIOS or
Pico flash write was performed. This validates signer substitution needed for
a VCN-specific driver trial; it does not initialize VCN or decode a frame.
