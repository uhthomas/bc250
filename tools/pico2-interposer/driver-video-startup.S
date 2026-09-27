/* BC250 PSP driver startup trial. Link as Thumb code at the pinned VMAs.
 * The wrapper first preserves the original initializer. The metadata variant
 * then initializes only the 56-byte video cache used by the VCN path.
 * This is for a RAM-only SPI interposer image, never an EEPROM image.
 */
.syntax unified
.thumb
.arch armv7-a

.section .hook, "ax", %progbits
.global bc250_driver_hook
.type bc250_driver_hook, %function
bc250_driver_hook:
    bl bc250_video_wrapper

.section .cave, "ax", %progbits
.global bc250_video_wrapper
.type bc250_video_wrapper, %function
bc250_video_wrapper:
    push {r4, lr}
    bl bc250_original_initializer
#ifdef BC250_INIT_VIDEO_METADATA
    ldr r4, =0xe35cc0
    mov r0, r4
    movs r1, #0x38
    bl bc250_zero_helper
    ldr r0, =0x1f90c
    str r0, [r4, #0x10]
    ldr r0, =0x1f848
    str r0, [r4, #0x14]
    ldr r0, =0x1f844
    str r0, [r4, #0x18]
#endif
    pop {r4, pc}

#ifdef BC250_INIT_VIDEO_TMR
/* BC250's existing TMR setup allocates 2 MiB for graphics at offset zero.
 * Preserve that call, then allocate an independent 1-MiB type-13 region at
 * offset 2 MiB. Only publish the video offset after the allocator succeeds.
 */
.section .tmr_hook, "ax", %progbits
.global bc250_tmr_hook
.type bc250_tmr_hook, %function
bc250_tmr_hook:
    bl bc250_tmr_wrapper

.section .tmr_cave, "ax", %progbits
.global bc250_tmr_wrapper
.type bc250_tmr_wrapper, %function
bc250_tmr_wrapper:
    push {r4, lr}
    bl bc250_original_region_alloc
    cbnz r0, 1f
    movs r0, #13
    mov.w r1, #0x200000
    mov.w r2, #0x100000
    bl bc250_original_region_alloc
    cbnz r0, 1f
    ldr r4, =0xe35cc0
    mov.w r1, #0x200000
    str r1, [r4, #4]
#ifdef BC250_INIT_VIDEO_RSMU12
    /* The signed BC250 RSMU startup skips client 12. Run its own bounded
     * four-store helper only after type-13 video TMR allocation succeeds.
     * The host must enable VCN clocks before SETUP_TMR for this experiment.
     */
    movs r0, #12
    bl bc250_original_rsmu_client_init
    movs r0, #0
#endif
#ifdef BC250_INIT_VIDEO_GASKET12
    /* Reproduce the pinned reference policy's client-12 writes only after
     * both allocations and native RSMU initialization succeeded. A rejected
     * service result is returned through the original SETUP_TMR error path.
     */
    bl bc250_gasket12_init
#endif
1:
    pop {r4, pc}
#endif

#ifdef BC250_INIT_VIDEO_GASKET12
.section .gasket_cave, "ax", %progbits
.global bc250_gasket12_init
.type bc250_gasket12_init, %function
bc250_gasket12_init:
    push {r4-r6, lr}
    ldr r4, =bc250_gasket12_table
    movs r5, #51
1:
    ldr r0, [r4], #4
    ldr r1, [r4], #4
    movs r2, #4
    svc #0x7c
    cbnz r0, 2f
    subs r5, r5, #1
    bne 1b
    movs r0, #0
2:
    pop {r4-r6, pc}
#include "gasket12-reference.inc"
#endif
