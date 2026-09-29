/* Read-only ABL0-entry sample of fabric word 0x50d6c, low 16 bits.
 * Link across 0x54070..0x5409f and 0x540a4..0x540cf, preserving the
 * 0x540a0 board marker. One encoded SPI read reports the value.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abl0_entry_fabric
abl0_entry_fabric:
    ldr sp, abl0_stack
    stmdb sp!, {r0-r3,r12,lr}
    ldr r0, abl0_selector
    ldr r1, abl0_fabric_address
    mov r2, r1, lsr #4
    str r2, [r0]
    ldr r0, abl0_aperture
    add r0, r0, r1
    ldr r2, [r0]
    uxth r2, r2
    b abl0_second

.section .text.abl0_second, "ax", %progbits
abl0_second:
    ldr r0, abl0_spi_lane
    add r0, r0, r2, lsl #2
    ldr r3, [r0]
    ldmia sp!, {r0-r3,r12,lr}
    ldr pc, abl0_resume
abl0_stack:          .word 0x00072000
abl0_selector:       .word 0x0322003c
abl0_fabric_address: .word 0x00050d6c
abl0_aperture:       .word 0x02f00000
abl0_spi_lane:       .word 0x27c40000
abl0_resume:         .word 0x00054104
