/* Reversible ABL3-exit probe of PSP-aperture word 0x50d6c.
 * Only if the full original word is exactly 0xf0, request 0x8f0, read it
 * back, and restore 0xf0 before the original pop {r4,pc}. An unexpected
 * initial value emits 0xffff instead and is never written.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abln_exit_fabric_toggle
abln_exit_fabric_toggle:
    stmdb sp!, {r0-r3,r12,lr}
    ldr r12, toggle_selector
    ldr r3, [r12]
    ldr r1, toggle_target
    mov r0, r1, lsr #4
    str r0, [r12]
    ldr r0, toggle_aperture
    add r0, r0, r1
    ldr r2, [r0]
    cmp r2, #0xf0
    orreq r1, r2, #0x800
    streq r1, [r0]

.section .text.abl0_second, "ax", %progbits
    ldreq r1, [r0]
    streq r2, [r0]
    mvnne r1, #0
    str r3, [r12]
    uxth r1, r1
    ldr r0, toggle_spi_lane
    add r0, r0, r1, lsl #2
    ldr r2, [r0]
    ldmia sp!, {r0-r3,r12,lr}
    ldmia sp!, {r4,pc}
    .space 4

.section .text.abl0_third, "ax", %progbits
toggle_selector: .word 0x0322003c
toggle_target:   .word 0x00050d6c
toggle_aperture: .word 0x02f00000
toggle_spi_lane: .word 0x27c40000
