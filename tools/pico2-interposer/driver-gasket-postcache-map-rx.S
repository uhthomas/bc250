/* RAM-only BC250 diagnostic. After the host programs the powered VCN memory
 * controller, replay its exact window values from two read-only code pages
 * through the signed PSP driver's
 * SVC 0x7c path. Verify the firmware BAR low word before VCPU reset release.
 * The kernel module must first check that its live GPU allocations equal the
 * pinned values in this table. This ROM view must NEVER be flashed.
 * Allocation journal SHA-256: e86abe7b832444122978d02d6f8f8a888a16786a2799cf4a9ca81ca13735ff85
 */
.syntax unified
.thumb
.arch armv7-a
#ifndef BC250_MAP_COUNT
#define BC250_MAP_COUNT 17
#endif

.section .readback_hook, "ax", %progbits
.global bc250_postcache_map_hook
.type bc250_postcache_map_hook, %function
bc250_postcache_map_hook:
    b.w bc250_postcache_map

.section .map_cave, "ax", %progbits
.global bc250_postcache_map
.type bc250_postcache_map, %function
bc250_postcache_map:
    push {r4-r7}
    /* Preserve the original first reset-service failure for PF context. */
    ldr r1, [sp, #0x24]
    movw r2, #0xffff
    cmp r1, r2
    bne 1f
    cbnz r0, 8f
1:
    ldr r0, =0x1f8a4
    movs r1, #1
    movs r2, #4
    svc #0x7c
    cbnz r0, 8f
    ldr r1, [sp, #0x24]
    movw r2, #0xffff
    cmp r1, r2
    bne 7f

    sub sp, #8
#ifndef BC250_REPORT_UVD_RESET_STABILITY
    movs r0, #0
    str r0, [sp]
#endif
    ldr r0, =0x1f810
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 6f
    ldr r0, [sp]
    cmp.w r0, #0x800
    bne 6f

#ifdef BC250_MAP_INLINE_FIRST
    movs r5, #1
    ldr r0, =0x2107c
    ldr r1, =0x1fa00000
    movs r2, #4
    svc #0x7c
    cbnz r0, 3f
    movs r5, #0
#else
    ldr r4, =bc250_vcn_window_addrs
    ldr r7, =bc250_vcn_window_values
    movs r5, #BC250_MAP_COUNT
2:
    ldr r0, [r4], #4
    ldr r1, [r7], #4
    movs r2, #4
    svc #0x7c
    cbnz r0, 3f
    subs r5, #1
    bne 2b
#endif

    /* Read the programmed windows through the same powered PSP path. The
     * write loop leaves r4/r7 one past the end, so check in reverse order. */
#if defined(BC250_VERIFY_ALL_MAP) || defined(BC250_VERIFY_CACHE_WINDOWS)
#ifdef BC250_VERIFY_CACHE_WINDOWS
    sub r4, #4
    sub r7, #4
    movs r5, #16
#else
    movs r5, #BC250_MAP_COUNT
#endif
5:
    ldr r0, [r4, #-4]!
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 9f
    ldr r0, [sp]
    ldr r1, [r7, #-4]!
    cmp r0, r1
    bne 4f
    subs r5, #1
    bne 5b
#elif defined(BC250_READBACK_GFX_CONFIG)
    /* Report the observed low 28 bits as a diagnostic PSP status. */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f928
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 9f
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
    b 9f
#elif defined(BC250_RELEASE_SOFT_RESET) || defined(BC250_RELEASE_UVD_SOFT_RESET) || defined(BC250_REPORT_UVD_RESET_AFTER_RELEASE) || defined(BC250_REPORT_AFTER_UVD_RELEASE) || defined(BC250_REPORT_UVD_RESET_BEFORE_WRITE) || defined(BC250_REPORT_UVD_RESET2_BEFORE_WRITE) || defined(BC250_REPORT_UVD_RESET_STABILITY)
    /* 0x1f8a4 is the signed driver's separate control word. Linux's
     * UVD_SOFT_RESET is at 0x20180 (VCN 2.0 segment 1, word 0x260).
     * The older diagnostic preserves 0x1f8a4 for reproducibility.
     */
#if defined(BC250_REPORT_UVD_RESET2_BEFORE_WRITE)
    /* VCN 2.0 segment 1: (0x7e00 + mmUVD_SOFT_RESET2 0x1e6) * 4. */
    ldr r0, =0x1ff98
#elif defined(BC250_RELEASE_UVD_SOFT_RESET) || defined(BC250_REPORT_UVD_RESET_AFTER_RELEASE) || defined(BC250_REPORT_AFTER_UVD_RELEASE) || defined(BC250_REPORT_UVD_RESET_BEFORE_WRITE) || defined(BC250_REPORT_UVD_RESET_STABILITY)
    ldr r0, =0x20180
#else
    ldr r0, =0x1f8a4
#endif
#if !defined(BC250_REPORT_UVD_RESET_BEFORE_WRITE) && !defined(BC250_REPORT_UVD_RESET2_BEFORE_WRITE)
    movs r1, #0
    movs r2, #4
    svc #0x7c
    cbnz r0, 9f
#endif
#ifdef BC250_REPORT_AFTER_UVD_RELEASE
#ifndef BC250_REPORT_TARGET
#error BC250_REPORT_TARGET is required for post-release reporting
#endif
    ldr r0, =BC250_REPORT_TARGET
#elif defined(BC250_REPORT_UVD_RESET_BEFORE_WRITE) || defined(BC250_REPORT_UVD_RESET2_BEFORE_WRITE)
    /* The reset address is still in r0; no write has touched it. */
#elif defined(BC250_RELEASE_UVD_SOFT_RESET) || defined(BC250_REPORT_UVD_RESET_AFTER_RELEASE)
    ldr r0, =0x20180
#elif defined(BC250_REPORT_UVD_RESET_STABILITY)
    /* Reload the address on each read: SVC returns its status in r0. */
#else
    ldr r0, =0x1f8a4
#endif
#ifdef BC250_REPORT_UVD_RESET_STABILITY
    /* Observe whether reset reasserts across 128 PSP-side reads after the
     * one bounded release write. Do not write the register again. */
    movs r5, #128
10:
    ldr r0, =0x20180
#endif
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 9f
#ifdef BC250_REPORT_UVD_RESET_STABILITY
    subs r5, #1
    bne 10b
#endif
    ldr r0, [sp]
#if defined(BC250_REPORT_UVD_RESET_AFTER_RELEASE) || defined(BC250_REPORT_AFTER_UVD_RELEASE) || defined(BC250_REPORT_UVD_RESET_BEFORE_WRITE) || defined(BC250_REPORT_UVD_RESET2_BEFORE_WRITE) || defined(BC250_REPORT_UVD_RESET_STABILITY)
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
    b 9f
#else
    ldr r1, =0x200d
    tst r0, r1
    bne 4f
#endif
#else
    /* The first cache BAR already proved PSP-readable after power-up. */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x2107c
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 9f
    ldr r0, [sp]
    ldr r1, =0x1fa00000
    cmp r0, r1
    bne 4f
#endif
#ifdef BC250_MAP_PREFIX_DIAGNOSTIC
    ldr r0, =(0x6d000000 | BC250_MAP_COUNT)
    b 9f
#else
    b 6f
#endif
3:
    ldr r0, =0x6a000000
    orr r0, r0, r5
    b 9f
4:
    ldr r0, =0x6b000000
#if defined(BC250_VERIFY_ALL_MAP) || defined(BC250_VERIFY_CACHE_WINDOWS)
    orr r0, r0, r5
#endif
9:
    add sp, #8
8:
    pop {r4-r7}
    b.w bc250_postload_readback_failure
6:
    add sp, #8
7:
    pop {r4-r7}
    movs r0, #0
    b.w bc250_postload_readback_success
    .balign 4, 0

.section .map_addr_table, "a", %progbits
.global bc250_vcn_window_addrs
bc250_vcn_window_addrs:
    /* Firmware window: PSP TMR image at 0x000000f41fa00000. */
    .word 0x2107c, 0x21078, 0x20108, 0x2010c
    /* Stack and context BO: 0x000000f41fd00000, contiguous regions. */
    .word 0x20eb0, 0x20eb4, 0x20110, 0x20114
    .word 0x20ec0, 0x20ec4, 0x20118, 0x2011c
    /* Shared non-cache window: 0x000000f41fda0000. */
    .word 0x2108c, 0x21088, 0x20150, 0x20154, 0x1f928

.section .map_value_table, "a", %progbits
.global bc250_vcn_window_values
bc250_vcn_window_values:
    .word 0x1fa00000, 0x000000f4, 0x00000000, 0x00064000
    .word 0x1fd00000, 0x000000f4, 0x00000000, 0x00020000
    .word 0x1fd20000, 0x000000f4, 0x00000000, 0x00080000
    .word 0x1fda0000, 0x000000f4, 0x00000000, 0x00001000
    .word 0x00100044
