/* RAM-only first-instruction TOS probe. Resume stock reset only for the
 * expected early CC_UVD_HARVESTING value; otherwise stop in this cave.
 * This uses PSP SVC 0x7b, not a host VCN aperture read.
 */
.syntax unified
.cpu cortex-a5
.arm
.ifndef EXPECT_HARVEST
.error "EXPECT_HARVEST must be set to 0 or 3"
.endif
.if EXPECT_HARVEST != 0 && EXPECT_HARVEST != 3
.error "EXPECT_HARVEST must be set to 0 or 3"
.endif
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    mov r4, r0
    mov r5, lr
    adr r1, sample
    mov r3, #0
    str r3, [r1]
    ldr r0, =0x1f81c
    mov r2, #4
    svc #0x7b
    cmp r0, #0
    bne failed
    adr r1, sample
    ldr r3, [r1]
    cmp r3, #EXPECT_HARVEST
    bne failed
    mov r0, r4
    mov lr, r5
    b original_entry
failed:
    b failed
    .balign 4, 0
sample:
    .word 0
    .ltorg
