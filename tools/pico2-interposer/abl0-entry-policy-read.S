/* Read-only ABL0-entry sample of VCN-adjacent policy word 0x1f820 bits 15:0.
 * Link first at 0x54070 and second at 0x540a4. The header's 0x540a0..a3
 * board marker remains untouched. The encoded SPI read is one of
 * 0x03c40000 + (sample_low16 << 2) at the first ABL0 execution boundary.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abl0_entry_policy_read
abl0_entry_policy_read:
    ldr sp, abl0_stack
    stmdb sp!, {r0-r3,r12,lr}
    ldr r0, abl0_selector
    ldr r1, abl0_policy_address
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
abl0_stack:           .word 0x00072000
abl0_selector:        .word 0x0322003c
abl0_policy_address:  .word 0x0001f820
abl0_aperture:        .word 0x02f00000
abl0_spi_lane:        .word 0x27c40000
abl0_resume:          .word 0x00054104
