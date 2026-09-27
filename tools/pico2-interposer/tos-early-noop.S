/* Exercise the TOS hook before MMU disable, then restore the displaced MRC. */
.syntax unified
.cpu cortex-a5
.arm
.section .text,"ax",%progbits
.global tos_video_entry
tos_video_entry:
    mrc p15, #0, r1, c1, c0, #0
    b original_entry
