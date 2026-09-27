/* Test a PC-relative literal read in the injected TOS area, then resume. */
.syntax unified
.cpu cortex-a5
.arm
.section .text,"ax",%progbits
.global tos_video_entry
tos_video_entry:
    ldr r1, =0x10784000
    mov r1, #0x24
    b original_entry
    .ltorg
