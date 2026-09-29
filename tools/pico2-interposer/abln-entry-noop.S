/* ABL1..ABL4 entry detour control: replay the displaced push and resume.
 * No MMIO or SPI access. This separates the detour from the fabric probe.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text.abl0_first, "ax", %progbits
.global abln_entry_noop
abln_entry_noop:
    stmdb sp!, {r4,lr}
    /* ABL1 can be relocated; the body is always 0x94 bytes above here. */
    b .+0x90
    .space 28
