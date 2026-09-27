#ifndef BC250_ROUTER_POLICY_H
#define BC250_ROUTER_POLICY_H
#include <stdbool.h>
#include <stdint.h>

enum router_action { ROUTER_REWIND, ROUTER_ADVANCE, ROUTER_BAD_LENGTH,
                     ROUTER_BAD_BOUNDARY, ROUTER_BAD_ADDRESS };

/* Pure decision shared by the firmware and host-compiled validation. A seeking
 * engine may ignore unrelated/short requests, but its first full address match
 * must finish as an ordinary four-byte read before substitutions are enabled.
 * Reset/enable actions still require measured CPU/peripheral timing on hardware.
 */
static inline __attribute__((always_inline)) enum router_action router_boundary(
        bool seeking, uint32_t clocks, bool mismatch, bool cs_high,
        uint32_t pc, uint32_t wait_start, uint32_t done) {
    if (!cs_high) return ROUTER_BAD_BOUNDARY;
    if (seeking && (clocks < 32 || mismatch)) return ROUTER_REWIND;
    if (mismatch) return ROUTER_BAD_ADDRESS;
    if (clocks != 64) return ROUTER_BAD_LENGTH;
    if (!(pc <= wait_start || pc == done || pc == done + 1))
        return ROUTER_BAD_BOUNDARY;
    return ROUTER_ADVANCE;
}
#endif
