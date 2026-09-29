/* First instruction of TOS: return to the original reset entry at 0x98. */
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    b original_entry
