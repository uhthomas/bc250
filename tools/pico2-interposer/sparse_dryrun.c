/* RAM-only, read-only physical profile rehearsal. PIO0 always passes original
 * BIOS flash data via GP7. GP5 MISO is disabled regardless of PIO state.
 * Core1 checks observed READ03 commands against the verified full trace and
 * counts predicted PATCH decisions without queueing a PATCH directive.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "sparse_select_od.pio.h"
#include "address_hunt.pio.h"
#include "pins.h"

struct expected_run { uint32_t command, count; };
struct patch_word { uint32_t command, reply; };
#include "sparse_physical_profile.h"

enum { FLASH_CS = 7u, SELECT_SM = 0u, WATCH_SM = 0u };
static PIO const selector_pio = pio0;
static PIO const watch_pio = pio1;
static uint selector_offset, watch_offset;
static bool armed;
static _Atomic uint32_t observed, matched, mismatches, completed,
                        would_patch, late_decisions, checksum;

static bool patch_word_for(uint32_t command, uint32_t row, uint32_t *reply) {
    uint32_t address = command & 0xffffffu;
    if ((command >> 24) != 3u ||
        !((address >= 0x9dad00u && address < 0x9dbad0u) ||
          (address >= 0x8eac00u && address < 0x8fef50u) ||
          (address >= 0x984f00u && address < 0x99f670u)) ||
        (address >= 0x9dad00u && address < 0x9dbad0u &&
         row >= PROFILE_SECOND_KEYDB_ROW)) return false;
    uint lo = 0u, hi = PROFILE_CHANGED_WORDS;
    while (lo < hi) {
        uint mid = lo + (hi - lo) / 2u;
        if (patch_words[mid].command < command) lo = mid + 1u;
        else hi = mid;
    }
    if (lo == PROFILE_CHANGED_WORDS || patch_words[lo].command != command) return false;
    *reply = patch_words[lo].reply;
    return true;
}

static void __not_in_flash_func(profile_worker)(void) {
    uint32_t previous = 0u, previous2 = 0u;
    uint32_t run = 0u, offset = 0u, row = 0u;
    bool tracking = false;
    for (;;) {
        if (pio_sm_is_rx_fifo_empty(watch_pio, WATCH_SM)) {
            tight_loop_contents();
            continue;
        }
        uint32_t command = watch_pio->rxf[WATCH_SM];
        atomic_fetch_add_explicit(&observed, 1u, memory_order_relaxed);
        if (!tracking && previous2 == 0x039db038u &&
            previous == 0x039db03cu && command == 0x039db040u) {
            tracking = true;
            run = offset = row = 0u;
        }
        if (tracking) {
            uint32_t expected = expected_runs[run].command + 4u * offset;
            if (command != expected) {
                atomic_fetch_add_explicit(&mismatches, 1u, memory_order_relaxed);
                tracking = false;
            } else {
                atomic_fetch_add_explicit(&matched, 1u, memory_order_relaxed);
                ++row;
                if (++offset == expected_runs[run].count) {
                    ++run;
                    offset = 0u;
                }
                if (row == PROFILE_ROWS) {
                    atomic_fetch_add_explicit(&completed, 1u, memory_order_relaxed);
                    tracking = false;
                } else {
                    uint32_t next = expected_runs[run].command + 4u * offset;
                    uint32_t reply;
                    if (patch_word_for(next, row, &reply)) {
                        atomic_fetch_add_explicit(&would_patch, 1u, memory_order_relaxed);
                        atomic_fetch_xor_explicit(&checksum, reply, memory_order_relaxed);
                        if (gpio_get(BC250_CS))
                            atomic_fetch_add_explicit(&late_decisions, 1u, memory_order_relaxed);
                    }
                }
            }
        }
        previous2 = previous;
        previous = command;
    }
}

static void status(void) {
    uint32_t stall = (watch_pio->fdebug >> (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u;
    printf("BC250-PICO2-SPARSE-DRYRUN v1 profile=%s clock_hz=%" PRIu32
           " armed=%u host_cs=%u pio_oe=%u miso=DISABLED board_patch=UNAVAILABLE"
           " observed=%" PRIu32 " matched=%" PRIu32 " mismatches=%" PRIu32
           " completed=%" PRIu32 " would_patch=%" PRIu32
           " late_decisions=%" PRIu32 " rxstall=%" PRIu32
           " checksum=%08" PRIx32 " bios_write=UNAVAILABLE\n",
           PROFILE_NAME, clock_get_hz(clk_sys), armed ? 1u : 0u,
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((selector_pio->dbg_padoe >> FLASH_CS) & 1u),
           atomic_load_explicit(&observed, memory_order_relaxed),
           atomic_load_explicit(&matched, memory_order_relaxed),
           atomic_load_explicit(&mismatches, memory_order_relaxed),
           atomic_load_explicit(&completed, memory_order_relaxed),
           atomic_load_explicit(&would_patch, memory_order_relaxed),
           atomic_load_explicit(&late_decisions, memory_order_relaxed),
           stall, atomic_load_explicit(&checksum, memory_order_relaxed));
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-pass")) {
        if (armed || !gpio_get(BC250_CS)) {
            printf("ERROR already armed or motherboard CS# low\n");
        } else {
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
            pio_sm_set_enabled(selector_pio, SELECT_SM, false);
            pio_sm_clear_fifos(selector_pio, SELECT_SM);
            pio_sm_restart(selector_pio, SELECT_SM);
            pio_sm_exec(selector_pio, SELECT_SM, pio_encode_jmp(selector_offset));
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, FLASH_CS, 1, false);
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, BC250_MISO, 1, false);
            pio_sm_set_enabled(selector_pio, SELECT_SM, true);
            sleep_us(10);
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
            armed = true;
            printf("ARMED SPARSE-DRYRUN output=CS_ONLY MISO=DISABLED no-PATCH-queue\n");
        }
    } else if (!strcmp(line, "cancel")) {
        gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
        armed = false;
        printf("CANCELLED output=OFF\n");
    } else {
        printf("ERROR status; arm-pass; cancel\n");
    }
    stdio_flush();
}

int main(void) {
    gpio_init(FLASH_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_input_enabled(FLASH_CS, false);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    for (uint pin = BC250_CS; pin <= BC250_MISO; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_input_enabled(pin, true);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    vreg_set_voltage(VREG_VOLTAGE_1_30);
    sleep_ms(10);
    bool clock_ok = set_sys_clock_khz(340000, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != 340000000u) {
        for (;;) { printf("ERROR clock setup failed; output off\n"); sleep_ms(1000); }
    }

    pio_sm_claim(selector_pio, SELECT_SM);
    selector_offset = pio_add_program(selector_pio, &sparse_select_od_program);
    pio_gpio_init(selector_pio, BC250_CS);
    pio_gpio_init(selector_pio, FLASH_CS);
    pio_gpio_init(selector_pio, BC250_MISO);
    gpio_disable_pulls(BC250_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_disable_pulls(BC250_MISO);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_input_enabled(FLASH_CS, false);
    gpio_set_oeover(BC250_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_config c = sparse_select_od_program_get_default_config(selector_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_out_pins(&c, BC250_MISO, 1);
    sm_config_set_out_shift(&c, false, false, 32);
    sm_config_set_set_pins(&c, FLASH_CS, 1);
    sm_config_set_sideset_pins(&c, BC250_MISO);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(selector_pio, SELECT_SM, selector_offset, &c);
    pio_sm_set_pins_with_mask(selector_pio, SELECT_SM, 0, 1u << FLASH_CS);
    pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, FLASH_CS, 1, false);
    pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, BC250_MISO, 1, false);

    pio_sm_claim(watch_pio, WATCH_SM);
    watch_offset = pio_add_program(watch_pio, &address_hunt_program);
    c = address_hunt_program_get_default_config(watch_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(watch_pio, WATCH_SM, watch_offset, &c);
    pio_sm_set_consecutive_pindirs(watch_pio, WATCH_SM, BC250_CS, 3, false);
    watch_pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM);
    multicore_launch_core1(profile_worker);
    pio_sm_set_enabled(watch_pio, WATCH_SM, true);

    char line[48];
    uint used = 0;
    bool overflow = false;
    for (;;) {
        int ch = getchar_timeout_us(0);
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[used] = 0;
            if (overflow) printf("ERROR line too long\n");
            else if (used) command(line);
            used = 0;
            overflow = false;
        } else if (ch >= 0 && used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        } else if (ch >= 0) {
            overflow = true;
        }
        sleep_us(50);
    }
}
