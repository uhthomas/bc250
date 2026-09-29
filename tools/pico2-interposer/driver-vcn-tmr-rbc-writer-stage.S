/* RAM-only PSP diagnostic with a stage marker. During the marked reload,
 * use the signed driver's SVC 0x89 TMR mapping route to put one scratch-write
 * packet and seven NOP packets in the final 4 KiB of the 1 MiB video region.
 * The firmware occupies only the first 0x64000 bytes of that region.
 * Continue the original cache-map code after unmapping; never flash this ROM.
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
    /* The original hook has saved r4-r7 and has an eight-byte frame.
     * UVD_POWER_STATUS=0x800 was checked before reaching this branch. */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f854
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cmp r0, #0
    bne.w original_map
    ldr r0, [sp]
    ldr r1, =0x5a13c0df
    cmp r0, r1
    bne.w original_map

    /* A live timeout with this value visible reached this hook but did not
     * finish the TMR mapping. The previous trial left the request marker
     * unchanged, so its timeout location was ambiguous. */
    ldr r0, =0x1f854
    ldr r1, =0x7a000001
    movs r2, #4
    svc #0x7c
    cmp r0, #0
    bne.w original_map

    sub sp, #8               /* mapped pointer and diagnostic status */
    movs r0, #0
    str r0, [sp]
    str r0, [sp, #4]
    ldr r0, =tmr_descriptor
    mov r1, sp
    ldr r2, =0xfffffff7      /* signed loader's TMR mapping attributes */
    movs r3, #0
    svc #0x89
    cbnz r0, map_failed
    ldr r4, [sp]
    cbz r4, null_map

    mov r5, r4
    ldr r6, =ring_words
    movs r7, #16
write_word:
    ldr r0, [r6], #4
    str r0, [r5], #4
    subs r7, #1
    bne write_word
    dsb sy

    mov r5, r4
    ldr r6, =ring_words
    movs r7, #16
verify_word:
    ldr r0, [r5], #4
    ldr r1, [r6], #4
    cmp r0, r1
    bne verify_failed
    subs r7, #1
    bne verify_word
    ldr r5, =0x7a000010   /* all 16 words read back in the PSP alias */
    b release_map
verify_failed:
    ldr r5, =0x7e000002
release_map:
    ldr r0, [sp]
    mov.w r1, #0x1000
    movs r2, #0
    movs r3, #0
    svc #0x8a
    cbz r0, report
    ldr r5, =0x7e000003
    b report
null_map:
    ldr r5, =0x7e000004
    b report
map_failed:
    ubfx r5, r0, #0, #16
    ldr r1, =0x7e010000
    orrs r5, r5, r1
report:
    ldr r0, =0x1f854
    mov r1, r5
    movs r2, #4
    svc #0x7c
    add sp, #8
original_map:
    /* Reproduce the two literal loads replaced at 0xe17c8e. */
    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    b.w bc250_postcache_map_loop_setup

    .balign 4, 0
tmr_descriptor:
    /* Video TMR: base 0xf41fa00000, final page 0xf41faff000. */
    .word 0x000000f4, 0x1faff000, 0x00001000, 0, 0, 0x0000ffff
ring_words:
    /* PACKET0(internal.scratch9, 0); marker; seven PACKET0(NOP, 0). */
    .word 0x0000c01d, 0x7b250001
    .rept 7
    .word 0x0000053f, 0
    .endr
    .ltorg
