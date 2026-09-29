/* Read-only fabric sample for ABL1..ABL4 entry.
 * The later ABL entry stubs begin with push {r4,lr}. The hook preserves
 * incoming registers, replays that displaced push, then resumes at body+4
 * with a relative branch so ABL relocation preserves the return address.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abln_entry_fabric
abln_entry_fabric:
    stmdb sp!, {r0-r3,r12,lr}
    ldr r12, abl_selector
    ldr r3, [r12]
    ldr r1, abl_fabric_address
    mov r2, r1, lsr #4
    str r2, [r12]
    ldr r0, abl_aperture
    add r0, r0, r1
    ldr r2, [r0]
    str r3, [r12]
    uxth r2, r2
    b abl_second

.section .text.abl0_second, "ax", %progbits
abl_second:
    ldr r0, abl_spi_lane
    add r0, r0, r2, lsl #2
    ldr r3, [r0]
    ldmia sp!, {r0-r3,r12,lr}
    stmdb sp!, {r4,lr}
    /* Return to the body at the same relocated base as this header. */
    b .+0x4c
abl_selector:       .word 0x0322003c
abl_fabric_address: .word 0x00050d6c
abl_aperture:       .word 0x02f00000
abl_spi_lane:       .word 0x27c40000
    .word 0
