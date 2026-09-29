/* ABL0-entry guarded volatile test of CC_UVD_HARVESTING.
 * At the first ABL0 instruction, write zero through the PSP SMN aperture
 * only if the initial 32-bit value is exactly 3. Encode immediate readback
 * in one SPI read: 0x03c40000 + ((readback & 0xffff) << 2).
 * Nothing in this hook writes the BIOS SPI flash or Pico QSPI payload.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abl0_entry_harvest_clear
abl0_entry_harvest_clear:
    ldr sp, abl0_stack
    stmdb sp!, {r0-r3}
    ldr r0, abl0_selector
    ldr r1, abl0_selector_value
    str r1, [r0]
    ldr r0, abl0_aperture
    ldr r2, [r0]
    cmp r2, #3
    moveq r3, #0
    streq r3, [r0]
    ldr r2, [r0]
    b abl0_second

.section .text.abl0_second, "ax", %progbits
abl0_second:
    uxth r2, r2
    ldr r0, abl0_spi_lane
    add r0, r0, r2, lsl #2
    ldr r3, [r0]
    ldmia sp!, {r0-r3}
    b . + 0x4c  /* 0x540b8 -> original ABL0 second instruction 0x54104 */
abl0_stack:           .word 0x00072000
abl0_selector:        .word 0x0322003c
abl0_selector_value:  .word 0x00001f81
abl0_aperture:        .word 0x02f1f81c
abl0_spi_lane:        .word 0x27c40000
