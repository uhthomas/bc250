/* Read modeled type-51 RAM before TOS disables MMU, then resume stock code. */
.syntax unified
.cpu cortex-a5
.arm
.section .text,"ax",%progbits
.global tos_video_entry
tos_video_entry:
    ldr r1, =0x10784000
    ldr r1, [r1, #0x10]
    mrc p15, #0, r1, c1, c0, #0
    b original_entry
    .ltorg
