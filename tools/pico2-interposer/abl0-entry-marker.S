/* RAM-only ABL0 entry diagnostic. The linker places this at PSP 0x54070,
 * a checked unused region of the signed ABL0 header. The first instruction
 * of its decompressed body branches here; after a single SPI marker read we
 * reproduce the displaced SP setup and resume at body + 4 (0x54104).
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global abl0_entry_marker
abl0_entry_marker:
    ldr sp, =0x00072000
    stmdb sp!, {r12}
    ldr r12, =0x27c3fffc
    ldr r12, [r12]
    ldmia sp!, {r12}
    ldr pc, =0x00054104
    .ltorg
