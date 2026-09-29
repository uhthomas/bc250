/* Read the data-fabric gate after the ABL3 Thumb worker returns.
 * The ABL3 ARM entry stub's final pop {r4,pc} branches here instead;
 * this hook restores its scratch registers and replays that pop.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abln_exit_fabric
abln_exit_fabric:
    stmdb sp!, {r0-r3,r12,lr}
    ldr r12, exit_selector
    ldr r3, [r12]
    ldr r1, exit_fabric_address
    mov r2, r1, lsr #4
    str r2, [r12]
    ldr r0, exit_aperture
    add r0, r0, r1
    ldr r2, [r0]
    str r3, [r12]
    uxth r2, r2
    b exit_second

.section .text.abl0_second, "ax", %progbits
exit_second:
    ldr r0, exit_spi_lane
    add r0, r0, r2, lsl #2
    ldr r3, [r0]
    ldmia sp!, {r0-r3,r12,lr}
    ldmia sp!, {r4,pc}
exit_selector:       .word 0x0322003c
exit_fabric_address: .word 0x00050d6c
exit_aperture:       .word 0x02f00000
exit_spi_lane:       .word 0x27c40000
    .space 8
