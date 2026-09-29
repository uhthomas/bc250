/* RAM-only BC250 diagnostic. After the host programs the powered VCN memory
 * controller, replay its exact window values through the signed PSP driver's
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
    push {r4,r5}
    /* Preserve the original first reset-service failure for PF context. */
    ldr r1, [sp, #0x1c]
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
    ldr r1, [sp, #0x1c]
    movw r2, #0xffff
    cmp r1, r2
    bne 7f

    sub sp, #8
    movs r0, #0
    str r0, [sp]
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
    ldr r4, =bc250_vcn_window_map
    movs r5, #BC250_MAP_COUNT
2:
    ldr r0, [r4], #4
    ldr r1, [r4], #4
    movs r2, #4
    svc #0x7c
    cbnz r0, 3f
    subs r5, #1
    bne 2b
#endif

    /* The register already proved PSP-readable after power-up. */
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
9:
    add sp, #8
8:
    pop {r4,r5}
    b.w bc250_postload_readback_failure
6:
    add sp, #8
7:
    pop {r4,r5}
    movs r0, #0
    b.w bc250_postload_readback_success
    .balign 4, 0

.section .program_table, "a", %progbits
.global bc250_vcn_window_map
bc250_vcn_window_map:
    /* Firmware window: PSP TMR image at 0x000000f41fa00000. */
    .word 0x2107c, 0x1fa00000
    .word 0x21078, 0x000000f4
    .word 0x20108, 0x00000000
    .word 0x2010c, 0x00064000
    /* Stack and context BO: 0x000000f41fd00000, contiguous regions. */
    .word 0x20eb0, 0x1fd00000
    .word 0x20eb4, 0x000000f4
    .word 0x20110, 0x00000000
    .word 0x20114, 0x00020000
    .word 0x20ec0, 0x1fd20000
    .word 0x20ec4, 0x000000f4
    .word 0x20118, 0x00000000
    .word 0x2011c, 0x00080000
    /* Shared non-cache window: 0x000000f41fda0000. */
    .word 0x2108c, 0x1fda0000
    .word 0x21088, 0x000000f4
    .word 0x20150, 0x00000000
    .word 0x20154, 0x00001000
    .word 0x1f928, 0x00100044
