/* Experimental strict-script router. Default/generated profiles are ISOLATED
 * Pi tests, not a captured BC250 boot. Actual board arming is intentionally
 * absent until clock, ordering and the core1 fault latency have been measured.
 * No erase/program command or EEPROM write is issued by this firmware.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "hardware/sync.h"
#include "hardware/structs/io_bank0.h"
#include "router.pio.h"
#include "router_count.pio.h"
#include "pins.h"
#include "router_stream.h"
#include "router_profile.h"
#include "router_policy.h"

enum { ENGINE=0, GUARD=3 };
enum { IDLE, RUNNING, COMPLETE, ADDRESS_FAULT, BOUNDARY_FAULT, CANCELLED, LENGTH_FAULT, SEEKING };
static _Atomic uint state = IDLE;
static _Atomic bool monitor_ready;
static _Atomic bool cancel_requested;
static uint guard_offset;
static uint count_offset;
static struct router_stream stream;
static PIO const pio = pio0;
static _Atomic uint boundaries, fault_pc, skipped;
_Static_assert(sizeof(router_runs) == ROUTER_PROFILE_RUNS * 12u, "run table size");
_Static_assert(sizeof(router_runs)+sizeof(router_payload) <= 384u*1024u, "profile exceeds SRAM allocation");

static inline __attribute__((always_inline)) void feed(void) {
    uint32_t word;
    if (!pio_sm_is_tx_fifo_full(pio,ENGINE) &&
        router_stream_next(&stream,router_runs,ROUTER_PROFILE_RUNS,router_payload,
                           router_offset_pass<<16,router_offset_patch<<16,&word))
        pio->txf[ENGINE]=word;
}

static inline __attribute__((always_inline)) void miso_off(void) {
    /* gpio_set_oeover() is a flash-resident SDK function. Keep the entire fault
     * path in SRAM, including this peripheral register write. */
    hw_write_masked(&io_bank0_hw->io[BC250_MISO].ctrl,
                   GPIO_OVERRIDE_LOW << IO_BANK0_GPIO0_CTRL_OEOVER_LSB,
                   IO_BANK0_GPIO0_CTRL_OEOVER_BITS);
}

static inline __attribute__((always_inline)) void miso_on(void) {
    hw_clear_bits(&io_bank0_hw->io[BC250_MISO].ctrl,IO_BANK0_GPIO0_CTRL_OEOVER_BITS);
}

static inline __attribute__((always_inline)) void rewind_anchor(void) {
    /* No FIFO entries were consumed after the unmatched first command. Preserve
     * Y (expected anchor) and OSR (PASS directive); reset just receive progress.
     * SM_RESTART preserves those registers, see the RP2350 register description.
     * The original flash CS mirror runs independently throughout this reset. */
    pio_sm_set_enabled(pio,ENGINE,false);
    pio_sm_restart(pio,ENGINE);
    pio_sm_exec(pio,ENGINE,pio_encode_jmp(router_offset_wait_start));
    pio->irq=1u;
    pio_sm_set_enabled(pio,ENGINE,true);
}

static void __not_in_flash_func(fault)(uint reason, uint pc) {
    /* Keep the independent CS mirror running; never select the original chip
     * halfway through a substituted read. Guard's next CS edge restores it. */
    miso_off();
    pio_sm_set_enabled(pio, ENGINE, false);
    atomic_store_explicit(&fault_pc, pc, memory_order_relaxed);
    atomic_store_explicit(&state, reason, memory_order_release);
}

static void __not_in_flash_func(monitor)(void) {
    save_and_disable_interrupts();
    atomic_store_explicit(&monitor_ready, true, memory_order_release);
    for (;;) {
        uint mode=atomic_load_explicit(&state,memory_order_acquire);
        /* Core1 owns all running-engine transitions. Serial cancellation must
         * not race an anchor rewind/enable performed by this same loop. */
        if (atomic_load_explicit(&cancel_requested,memory_order_acquire)) {
            if (mode!=CANCELLED) fault(CANCELLED,pio_sm_get_pc(pio,ENGINE));
            continue;
        }
        if (mode!=RUNNING && mode!=SEEKING) continue;
        uint flags = pio->irq;
        if (mode==RUNNING && (flags & 1u)) {
            fault(ADDRESS_FAULT, pio_sm_get_pc(pio, ENGINE));
        } else if (!pio_sm_is_rx_fifo_empty(pio1,0)) {
            uint clocks=pio1->rxf[0];
            pio->irq = 2u;
            /* Read PC after the counter has published the end, not before it:
             * a pre-boundary snapshot could falsely reject a completed reply. */
            uint pc=pio_sm_get_pc(pio,ENGINE);
            /* A trace must provide >=1 us CS-high gaps. This bound remains a
             * bench qualification target: it has NOT been measured on a Pico.
             * At a legal end, the engine is DONE or preparing the next record.
             * If the gap was missed, fail even if the next command is valid. */
            enum router_action action=router_boundary(mode==SEEKING,clocks,
                pio->irq&1u,gpio_get(BC250_CS),pc,router_offset_wait_start,router_offset_done);
            if (action==ROUTER_REWIND) {
                rewind_anchor();
                uint n=atomic_load_explicit(&skipped,memory_order_relaxed)+1;
                atomic_store_explicit(&skipped,n,memory_order_relaxed);
            } else if (action!=ROUTER_ADVANCE) {
                fault(action==ROUTER_BAD_LENGTH ? LENGTH_FAULT :
                      action==ROUTER_BAD_ADDRESS ? ADDRESS_FAULT : BOUNDARY_FAULT,pc);
            } else {
                uint n = atomic_load_explicit(&boundaries, memory_order_relaxed) + 1;
                atomic_store_explicit(&boundaries, n, memory_order_relaxed);
                if (mode==SEEKING) {
                    miso_on();
                    atomic_store_explicit(&state,RUNNING,memory_order_release);
                } else if (n == ROUTER_PROFILE_ROWS) {
                    /* MISO is disabled at DONE; CS mirror must continue after
                     * the finite script, including non-READ03 flash commands. */
                    miso_off();
                    pio_sm_set_enabled(pio, ENGINE, false);
                    atomic_store_explicit(&state, COMPLETE, memory_order_release);
                }
            }
        }
        if (atomic_load_explicit(&state,memory_order_relaxed)==RUNNING ||
            atomic_load_explicit(&state,memory_order_relaxed)==SEEKING) feed();
    }
}

static void status(void) {
    printf("BC250-PICO2-ROUTER v2 profile=%s rows=%u state=%u boundaries=%u skipped=%u fault_pc=%u board_arm=UNAVAILABLE clock_hz=%" PRIu32 "\n",
           ROUTER_PROFILE_NAME, ROUTER_PROFILE_ROWS, atomic_load(&state),
           atomic_load(&boundaries),atomic_load(&skipped),atomic_load(&fault_pc),clock_get_hz(clk_sys));
}

static void arm(void) {
    if (atomic_load(&state) != IDLE) {
        printf("ERROR one run per reset; keep target disconnected when resetting\n"); return;
    }
    if (!gpio_get(BC250_CS) || gpio_get(BC250_SCLK)) {
        printf("ERROR isolated master must idle with CS=1 SCLK=0 (mode 0)\n"); return;
    }
    if (ROUTER_PROFILE_ROWS<3 || router_runs[0].payload!=ROUTER_NO_PAYLOAD ||
        (router_runs[0].count<2 && (ROUTER_PROFILE_RUNS<2 ||
                                  router_runs[1].payload!=ROUTER_NO_PAYLOAD))) {
        printf("ERROR profile must start with two PASS guard reads\n"); return;
    }
    pio_sm_config c=router_program_get_default_config(0);
    sm_config_set_in_pins(&c,BC250_MOSI);
    sm_config_set_in_shift(&c,false,false,32);
    sm_config_set_out_pins(&c,BC250_MISO,1);
    sm_config_set_out_shift(&c,false,false,32);
    sm_config_set_set_pins(&c,BC250_FLASH_CS,1);
    sm_config_set_sideset_pins(&c,BC250_MISO);
    pio_sm_init(pio,ENGINE,0,&c);
    c=router_guard_program_get_default_config(guard_offset);
    sm_config_set_jmp_pin(&c,BC250_CS);
    sm_config_set_set_pins(&c,BC250_FLASH_CS,1);
    sm_config_set_sideset_pins(&c,BC250_MISO);
    pio_sm_init(pio,GUARD,guard_offset,&c);
    c=router_count_program_get_default_config(count_offset);
    sm_config_set_in_pins(&c,BC250_CS);
    sm_config_set_in_pin_count(&c,1);
    sm_config_set_jmp_pin(&c,BC250_SCLK);
    pio_sm_init(pio1,0,count_offset,&c);
    for (uint pin=BC250_CS; pin<=BC250_FLASH_CS; ++pin) {
        pio_gpio_init(pio,pin); gpio_disable_pulls(pin);
        gpio_set_oeover(pin,GPIO_OVERRIDE_LOW);
    }
    pio_sm_set_pins_with_mask(pio,GUARD,1u<<BC250_FLASH_CS,1u<<BC250_FLASH_CS);
    pio_sm_set_consecutive_pindirs(pio,GUARD,BC250_FLASH_CS,1,true);
    pio_sm_set_consecutive_pindirs(pio,GUARD,BC250_MISO,1,false);
    pio->irq=3u;
    while (pio_sm_get_tx_fifo_level(pio,ENGINE)<4) feed();
    /* Keep MISO physically disabled until the first PASS anchor completes. */
    gpio_set_oeover(BC250_FLASH_CS,GPIO_OVERRIDE_NORMAL);
    atomic_store_explicit(&state,SEEKING,memory_order_release);
    pio_sm_set_enabled(pio1,0,true);
    pio_enable_sm_mask_in_sync(pio,(1u<<ENGINE)|(1u<<GUARD));
    while (pio_sm_get_pc(pio,ENGINE)!=router_offset_wait_start) tight_loop_contents();
    printf("ARMED ISOLATED-ROUTER mode=0 rows=%u modeled_max_hz=5000000\n",ROUTER_PROFILE_ROWS);
}

int main(void) {
    for (uint pin=BC250_CS; pin<=BC250_FLASH_CS; ++pin) {
        gpio_init(pin); gpio_disable_pulls(pin); gpio_set_oeover(pin,GPIO_OVERRIDE_LOW);
    }
    stdio_init_all();
    pio_sm_claim(pio,ENGINE); pio_sm_claim(pio,GUARD);
    pio_add_program_at_offset(pio,&router_program,0);
    guard_offset=pio_add_program(pio,&router_guard_program);
    pio_sm_claim(pio1,0);
    count_offset=pio_add_program(pio1,&router_count_program);
    multicore_launch_core1(monitor);
    while (!atomic_load_explicit(&monitor_ready,memory_order_acquire)) tight_loop_contents();
    char line[96]; uint used=0; bool overflow=false;
    for (;;) {
        int ch=getchar_timeout_us(10000);
        if (ch<0 || ch=='\r') continue;
        if (ch=='\n') {
            line[used]=0;
            if (overflow) printf("ERROR line too long\n");
            else if (!strcmp(line,"status")) status();
            else if (!strcmp(line,"arm-isolated")) arm();
            else if (!strcmp(line,"cancel")) {
                atomic_store_explicit(&cancel_requested,true,memory_order_release);
                while (atomic_load_explicit(&state,memory_order_acquire)!=CANCELLED)
                    tight_loop_contents();
                printf("CANCELLED MISO disabled; GP6 mirror remains active until Pico reset\n");
            } else if (used) printf("ERROR status; arm-isolated; cancel. No board trial profile installed.\n");
            used=0; overflow=false;
        } else if (used<sizeof(line)-1) line[used++]=(char)ch;
        else overflow=true;
    }
}
