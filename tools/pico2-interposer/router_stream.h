#ifndef BC250_ROUTER_STREAM_H
#define BC250_ROUTER_STREAM_H
#include <stdbool.h>
#include <stdint.h>

struct router_run { uint32_t command, count, payload; };
struct router_stream { uint32_t run, offset, lane; };
#define ROUTER_NO_PAYLOAD UINT32_MAX
_Static_assert(sizeof(struct router_run)==12,"run layout");

/* Expand exactly one PIO FIFO word. All metadata and replacement words live in
 * SRAM. The caller fills available FIFO slots ahead of the address comparison;
 * no lookup is requested by the PIO at the instant a reply must start. */
static inline __attribute__((always_inline)) bool router_stream_next(
        struct router_stream *s, const struct router_run *runs, uint32_t n,
        const uint32_t *payload, uint32_t pass, uint32_t patch, uint32_t *out) {
    if (s->run==n) return false;
    const struct router_run *r=&runs[s->run];
    if (s->lane==0) {
        *out=r->command+4*s->offset;
        s->lane=1;
    } else if (s->lane==1) {
        *out=r->payload==ROUTER_NO_PAYLOAD ? pass : patch;
        s->lane=2;
    } else {
        *out=r->payload==ROUTER_NO_PAYLOAD ? 0 : payload[r->payload+s->offset];
        s->lane=0;
        if (++s->offset==r->count) {
            ++s->run;
            s->offset=0;
        }
    }
    return true;
}
#endif
