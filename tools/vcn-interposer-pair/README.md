# Direct VCN-key external-flash pair

These scripts prepare and independently check a **private, untested** 16 MiB
image pair for a future isolated SPI interposer. They do not access the BC250
or program flash. The patched image is **invalid as a standalone BIOS and must
never be written to the board's on-board EEPROM**.

The clean image is the exact working BC250 backup with SHA-256
`f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183`.
The patched image replaces the type-51 key record at flash
`0x9dbda0..0x9dbef0` (end exclusive): original usage 44 becomes the authentic
Cezanne VCN2 usage-6 record. Exactly 272 bytes differ. The database header,
stored body digest and signature remain original, so the patched image alone
fails its body integrity check. The proposed interposer would supply the
patched body for the loader's RAM copy and the clean body for its later hash
read. That timing and this board's read order have not been measured.

The pair prepared on 2026-09-25 is private under
`/tmp/bc250-vcn-direct-pair-x_pldzsl`. Its patched SHA-256 is
`cd41a46f7fa8d64e40d2a4250eb3baae24eaf17202d7a293d3f1fc2919895781`.
The directory is mode `0700`, and each file is mode `0600`; the ROM may contain
board-specific data. A verifier checked the full clean and patched bytes, the
donor record, exact difference range, unchanged header/signature and invalid
standalone body digest. Its optional readback interface was exercised against
the files themselves; **no external chip readback has occurred**.

The prepared type-51 object matches the pinned native loader model's input
byte for byte. With either tested RAM fill, the model accepts it only when the
later hash read sees the clean body; without a switch it rejects it. The
modeled type-13 VCN firmware authentication then returns success. That does
not prove the installed encrypted loader, full boot, usage-44 compatibility,
VCN power/rings or decoded frames. Replacing usage 44 may break a boot path
that the bounded firmware inventory did not reveal.

To regenerate from the exact backup and donor database:

```sh
python3 tools/vcn-interposer-pair/prepare.py \
  --clean-rom /path/to/known-working-before-1.rom \
  --donor-keydb /path/to/cezanne-PSP-TypeId0x51_KeyDbTos_CZN.sbin
python3 tools/vcn-interposer-pair/verify.py /tmp/bc250-vcn-direct-pair-.../MANIFEST.json
```

Both inputs are pinned by SHA-256, and the generator refuses different bytes.
`verify.py` can later compare two readbacks from **external** flash chips with
`--clean-readback` and `--patched-readback`. Such a match still would not prove
that an active interposer switches safely. The
[hardware-decode plan](../../docs/video-decode-next-step.md) keeps the normal
board EEPROM intact.

The [Pico 2/original-flash overlay concept](../../docs/pico2-original-flash-overlay.md)
could use this same pair as an **offline source** for a small SRAM image rather
than programming two extra flash chips. That concept is not implemented or
timing-validated. It still requires physically isolating the original flash's
CS# path; J4004 alone cannot prevent MISO contention. The scripts and manifest
above remain scoped to the two-external-flash experiment.
