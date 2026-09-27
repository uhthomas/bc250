/* Read one word from the modeled type-51 RAM address, then resume stock TOS. */
.syntax unified
.cpu cortex-a5
.arm
.section .text,"ax",%progbits
.global tos_video_entry
tos_video_entry:
    ldr r1, =0x10784000
    ldr r1, [r1, #0x10]
    mov r1, #0x24
    b original_entry
    .ltorg
