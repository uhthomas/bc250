/* After the original PSP driver initializer, read CC_UVD_HARVESTING with
 * SVC 0x7b and encode status + sample as four read-only BIOS SPI addresses.
 * The hook replaces the original initializer BL and retains its return r0.
 */
.syntax unified
.thumb
.arch armv7-a

.section .hook, "ax", %progbits
.global bc250_driver_hook
.type bc250_driver_hook, %function
bc250_driver_hook:
    bl bc250_driver_probe

.section .cave, "ax", %progbits
.global bc250_driver_probe
.type bc250_driver_probe, %function
bc250_driver_probe:
    push {r4-r7, lr}
    bl bc250_original_initializer
    mov r4, r0
    adr r1, sample
    movs r0, #0
    str r0, [r1]
    ldr r0, =0x1f81c
    movs r2, #4
    svc #0x7b
    mov r5, r0
    ldr r6, sample

    ldr r0, =0x27c3fffc
    ldr r0, [r0]
    ldr r7, =0x27c00000
    uxth r0, r5
    add.w r0, r7, r0, lsl #2
    ldr r0, [r0]
    add.w r7, r7, #0x40000
    lsrs r0, r5, #16
    add.w r0, r7, r0, lsl #2
    ldr r0, [r0]
    add.w r7, r7, #0x40000
    uxth r0, r6
    add.w r0, r7, r0, lsl #2
    ldr r0, [r0]
    add.w r7, r7, #0x40000
    lsrs r0, r6, #16
    add.w r0, r7, r0, lsl #2
    ldr r0, [r0]

    mov r0, r4
    pop {r4-r7, pc}
    .balign 4, 0
sample:
    .word 0
    .ltorg
