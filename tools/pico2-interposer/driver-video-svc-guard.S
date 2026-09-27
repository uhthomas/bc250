/* Preserve the type-13 video-control SVC result in the BC250 allocator.
 * The original instructions at e0e9c4 overwrite r0 immediately after SVC 7c.
 * A nonzero result now follows the allocator's existing error cleanup path.
 * Only for RAM-only interposition; never write this image to the BIOS chip.
 */
.syntax unified
.thumb
.arch armv7-a

.section .svc_hook, "ax", %progbits
.global bc250_video_svc_hook
.type bc250_video_svc_hook, %function
bc250_video_svc_hook:
    b.w bc250_video_svc_guard
    nop.w

.section .svc_cave, "ax", %progbits
.global bc250_video_svc_guard
.type bc250_video_svc_guard, %function
bc250_video_svc_guard:
    cbz r0, 1f
    mov r7, r0
    b.w bc250_video_svc_failure
1:
    movs r0, #0x32
    movw r5, #0xc22
    b.w bc250_video_svc_success
    .balign 4, 0
