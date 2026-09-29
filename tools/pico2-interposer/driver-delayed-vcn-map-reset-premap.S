/* RAM-only PSP diagnostic. On a marked second load, compare all sixteen
 * pinned VCPU cache words before any replay, then read UVD_SOFT_RESET
 * through PSP SVC 7b without writing that reset word. The unmarked path
 * preserves the proven signed load. Never flash this view to BIOS EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

.section .premap_branch, "ax", %progbits
.global bc250_premap_branch
bc250_premap_branch:
    b.w bc250_premap_dispatch

.section .dispatch_cave, "ax", %progbits
.global bc250_premap_dispatch
bc250_premap_dispatch:
    /* Original hook has pushed r4-r7, allocated eight bytes and checked
     * powered UVD_POWER_STATUS=0x800. */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f854
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cmp r0, #0
    bne.w unmarked
    ldr r3, [sp]
    ldr r1, =0x5a13c0df
    cmp r3, r1
    bne.w unmarked

    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    movs r5, #16
    movs r6, #0
next_window:
    movs r0, #0
    str r0, [sp]
    ldr r0, [r4], #4
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cmp r0, #0
    bne.w finish
    ldr r3, [sp]
    ldr r0, [r7], #4
    cmp r3, r0
    bne.w mismatch
    adds r6, #1
    subs r5, #1
    bne next_window

    /* All cache words matched. Report low 24 bits of the reset word;
     * 0x73 marks this as the PSP reset read rather than a cache result.
     * Bits 24:27 are occupied by the tag and cannot be inferred.
     */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x20180
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cmp r0, #0
    bne.w finish
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x73000000
    b.w finish
mismatch:
    ubfx r0, r3, #0, #20
    lsls r6, r6, #20
    orrs r0, r0, r6
    orr.w r0, r0, #0x71000000
finish:
    b.w bc250_postcache_map_failure

unmarked:
    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    b.w bc250_postcache_map_loop_setup
    .balign 4, 0
