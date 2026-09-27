/* RAM-only physical sparse PASS/PATCH candidate. GP7 sinks or releases
 * original-flash CS#. GP5 drives MISO only after the PIO verifies a complete
 * expected PATCH command. Core1 checks every observed READ03 command in the
 * verified boot profile. No firmware erase/program command is issued.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#ifdef BC250_BUS_SNAPSHOT
#include "hardware/dma.h"
#endif
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "hardware/watchdog.h"
#ifdef BC250_EARLY_MISO
#include "sparse_select_early.pio.h"
#define SPARSE_SELECTOR_PROGRAM sparse_select_early_program
#define SPARSE_SELECTOR_CONFIG sparse_select_early_program_get_default_config
#else
#include "sparse_select_od.pio.h"
#define SPARSE_SELECTOR_PROGRAM sparse_select_od_program
#define SPARSE_SELECTOR_CONFIG sparse_select_od_program_get_default_config
#endif
#include "address_hunt.pio.h"
#ifdef BC250_MISO_PROBE
#include "miso_probe.pio.h"
#endif
#ifdef BC250_BUS_SNAPSHOT
#ifdef BC250_RELEASE_SNAPSHOT
#include "bus_release_snapshot.pio.h"
#define BUS_SNAPSHOT_PROGRAM bus_release_snapshot_program
#define BUS_SNAPSHOT_CONFIG bus_release_snapshot_program_get_default_config
#else
#include "bus_snapshot.pio.h"
#define BUS_SNAPSHOT_PROGRAM bus_snapshot_program
#define BUS_SNAPSHOT_CONFIG bus_snapshot_program_get_default_config
#endif
#endif
#include "pins.h"

struct expected_run { uint32_t command, count; };
struct patch_word { uint32_t command, reply; };
#include "sparse_physical_profile.h"

enum { FLASH_CS = 7u, SELECT_SM = 0u, WATCH_SM = 0u,
       PROBE_SM = 1u, SNAPSHOT_SM = 2u };
enum { UNARMED, PASS_ONLY, ACTIVE };
enum { NO_FAULT, PROFILE_FAULT, PIO_COMMAND_FAULT, RX_STALL_FAULT,
       LATE_QUEUE_FAULT, TX_FIFO_FAULT };
static PIO const selector_pio = pio0;
static PIO const watch_pio = pio1;
static uint selector_offset, watch_offset;
#ifdef BC250_MISO_PROBE
static uint probe_offset;
static _Atomic uint32_t probe_armed, probe_late;
static uint32_t probe_reply, probe_ready;
#endif
#ifdef BC250_BUS_SNAPSHOT
enum { SNAPSHOT_WORDS = 192u };
static uint snapshot_offset, snapshot_dma;
static uint32_t snapshot_words[SNAPSHOT_WORDS];
static _Atomic uint32_t snapshot_armed, snapshot_late;
#endif
static _Atomic uint32_t mode, fault_reason;
static _Atomic uint32_t observed, matched, mismatches, completed,
                        would_patch, late_decisions, checksum, queued, verified,
                        flash_pad_high, flash_pad_low;

static void __not_in_flash_func(fail_closed)(uint32_t reason) {
    if (atomic_load_explicit(&fault_reason, memory_order_acquire)) return;
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    atomic_store_explicit(&fault_reason, reason, memory_order_release);
}

static bool patch_word_for(uint32_t command, uint32_t row, uint32_t *reply) {
    uint32_t address = command & 0xffffffu;
    if ((command >> 24) != 3u ||
        !((address >= 0x9dad00u && address < 0x9dbad0u) ||
          (address >= 0x8eac00u && address < 0x8fef50u) ||
          (address >= 0x984f00u && address < 0x99f670u)
#ifdef PROFILE_TYPE51_HASH_ROW
          || (address >= 0x9dbda0u && address < 0x9dbef0u)
#endif
          ) ||
        (address >= 0x9dad00u && address < 0x9dbad0u &&
         row >= PROFILE_SECOND_KEYDB_ROW)
#ifdef PROFILE_TYPE51_HASH_ROW
        || (address >= 0x9dbda0u && address < 0x9dbef0u &&
            row >= PROFILE_TYPE51_HASH_ROW)
#endif
        ) return false;
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
    uint32_t pending_command = 0u;
    bool tracking = false;
    bool pending = false;
    for (;;) {
        if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE &&
            !atomic_load_explicit(&fault_reason, memory_order_relaxed)) {
            if (pio_interrupt_get(selector_pio, 0))
                fail_closed(PIO_COMMAND_FAULT);
            if ((watch_pio->fdebug >> (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u)
                fail_closed(RX_STALL_FAULT);
        }
        if (pio_sm_is_rx_fifo_empty(watch_pio, WATCH_SM)) {
            tight_loop_contents();
            continue;
        }
        uint32_t command = watch_pio->rxf[WATCH_SM];
        atomic_fetch_add_explicit(&observed, 1u, memory_order_relaxed);
        if (pending) {
            if (command == pending_command) {
                atomic_fetch_add_explicit(&verified, 1u, memory_order_relaxed);
                if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE) {
                    if (gpio_get(FLASH_CS))
                        atomic_fetch_add_explicit(&flash_pad_high, 1u, memory_order_relaxed);
                    else
                        atomic_fetch_add_explicit(&flash_pad_low, 1u, memory_order_relaxed);
                }
            } else if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE)
                fail_closed(PROFILE_FAULT);
            pending = false;
        }
        if (atomic_load_explicit(&fault_reason, memory_order_acquire)) {
            previous2 = previous;
            previous = command;
            continue;
        }
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
                if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE)
                    fail_closed(PROFILE_FAULT);
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
                        if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE) {
                            if (gpio_get(BC250_CS)) {
                                fail_closed(LATE_QUEUE_FAULT);
                            } else if (pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM)) {
                                fail_closed(TX_FIFO_FAULT);
                            } else {
                                selector_pio->txf[SELECT_SM] = 1u;
                                selector_pio->txf[SELECT_SM] = next;
                                selector_pio->txf[SELECT_SM] = reply;
                                if (gpio_get(BC250_CS))
                                    fail_closed(LATE_QUEUE_FAULT);
                                else {
                                    pending = true;
                                    pending_command = next;
                                    atomic_fetch_add_explicit(&queued, 1u, memory_order_relaxed);
                                }
                            }
                        }
#ifdef BC250_MISO_PROBE
                        if (
#ifdef BC250_SNAPSHOT_COMMAND
                            next == BC250_SNAPSHOT_COMMAND &&
#endif
                            !atomic_load_explicit(&probe_armed, memory_order_relaxed)) {
                            pio_sm_clear_fifos(watch_pio, PROBE_SM);
                            pio_sm_restart(watch_pio, PROBE_SM);
                            pio_sm_exec(watch_pio, PROBE_SM, pio_encode_jmp(probe_offset));
                            pio_sm_set_enabled(watch_pio, PROBE_SM, true);
                            if (gpio_get(BC250_CS))
                                atomic_store_explicit(&probe_late, 1u, memory_order_relaxed);
                            atomic_store_explicit(&probe_armed, 1u, memory_order_release);
                        }
#endif
#ifdef BC250_BUS_SNAPSHOT
                        if (
#ifdef BC250_SNAPSHOT_COMMAND
                            next == BC250_SNAPSHOT_COMMAND &&
#endif
                            !atomic_load_explicit(&snapshot_armed, memory_order_relaxed)) {
                            pio_sm_clear_fifos(watch_pio, SNAPSHOT_SM);
                            pio_sm_restart(watch_pio, SNAPSHOT_SM);
                            pio_sm_exec(watch_pio, SNAPSHOT_SM, pio_encode_jmp(snapshot_offset));
                            dma_channel_set_write_addr(snapshot_dma, snapshot_words, false);
                            dma_channel_set_trans_count(snapshot_dma, SNAPSHOT_WORDS, false);
                            dma_channel_start(snapshot_dma);
                            pio_sm_set_enabled(watch_pio, SNAPSHOT_SM, true);
                            if (gpio_get(BC250_CS))
                                atomic_store_explicit(&snapshot_late, 1u, memory_order_relaxed);
                            atomic_store_explicit(&snapshot_armed, 1u, memory_order_release);
                        }
#endif
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
#ifdef BC250_MISO_PROBE
    if (!probe_ready && !pio_sm_is_rx_fifo_empty(watch_pio, PROBE_SM)) {
        probe_reply = watch_pio->rxf[PROBE_SM];
        probe_ready = 1u;
    }
    printf("probe_armed=%" PRIu32 " probe_late=%" PRIu32
           " probe_ready=%" PRIu32 " probe_reply=%08" PRIx32 " ",
           atomic_load_explicit(&probe_armed, memory_order_relaxed),
           atomic_load_explicit(&probe_late, memory_order_relaxed),
           probe_ready, probe_reply);
#endif
#ifdef BC250_BUS_SNAPSHOT
    printf("snapshot_armed=%" PRIu32 " snapshot_late=%" PRIu32
           " snapshot_remaining=%" PRIu32 " ",
           atomic_load_explicit(&snapshot_armed, memory_order_relaxed),
           atomic_load_explicit(&snapshot_late, memory_order_relaxed),
           (uint32_t)dma_channel_hw_addr(snapshot_dma)->transfer_count);
#endif
    printf("BC250-PICO2-SPARSE-ACTIVE v1 profile=%s clock_hz=%" PRIu32
#ifdef BC250_FAST_MISO_PAD
           " miso_pad=FAST_12MA"
#else
           " miso_pad=DEFAULT"
#endif
           " mode=%" PRIu32 " fault=%" PRIu32 " host_cs=%u pio_oe=%u miso_oe=%u"
           " observed=%" PRIu32 " matched=%" PRIu32 " mismatches=%" PRIu32
           " completed=%" PRIu32 " would_patch=%" PRIu32
           " queued=%" PRIu32 " verified=%" PRIu32
           " flash_pad_high=%" PRIu32 " flash_pad_low=%" PRIu32
           " late_decisions=%" PRIu32 " rxstall=%" PRIu32
           " checksum=%08" PRIx32 " bios_write=UNAVAILABLE\n",
           PROFILE_NAME, clock_get_hz(clk_sys),
           atomic_load_explicit(&mode, memory_order_relaxed),
           atomic_load_explicit(&fault_reason, memory_order_relaxed),
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((selector_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((selector_pio->dbg_padoe >> BC250_MISO) & 1u),
           atomic_load_explicit(&observed, memory_order_relaxed),
           atomic_load_explicit(&matched, memory_order_relaxed),
           atomic_load_explicit(&mismatches, memory_order_relaxed),
           atomic_load_explicit(&completed, memory_order_relaxed),
           atomic_load_explicit(&would_patch, memory_order_relaxed),
           atomic_load_explicit(&queued, memory_order_relaxed),
           atomic_load_explicit(&verified, memory_order_relaxed),
           atomic_load_explicit(&flash_pad_high, memory_order_relaxed),
           atomic_load_explicit(&flash_pad_low, memory_order_relaxed),
           atomic_load_explicit(&late_decisions, memory_order_relaxed),
           stall, atomic_load_explicit(&checksum, memory_order_relaxed));
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
#ifdef BC250_BUS_SNAPSHOT
    } else if (!strcmp(line, "snapshot")) {
        if (!atomic_load_explicit(&snapshot_armed, memory_order_acquire) ||
            dma_channel_is_busy(snapshot_dma)) {
            printf("ERROR snapshot not complete\n");
        } else {
            printf("SNAPSHOT words=%u samples=%u\n", SNAPSHOT_WORDS,
                   SNAPSHOT_WORDS * 5u);
            for (uint i = 0; i < SNAPSHOT_WORDS; ++i)
                printf("%08" PRIx32 "%c", snapshot_words[i],
                       (i % 8u == 7u) ? '\n' : ' ');
        }
#endif
    } else if (!strcmp(line, "arm-pass") || !strcmp(line, "arm-active")) {
        bool active = !strcmp(line, "arm-active");
        if (atomic_load_explicit(&mode, memory_order_acquire) != UNARMED ||
            atomic_load_explicit(&fault_reason, memory_order_acquire) ||
            !gpio_get(BC250_CS)) {
            printf("ERROR already armed, faulted, or motherboard CS# low\n");
        } else {
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
            gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
            pio_sm_set_enabled(selector_pio, SELECT_SM, false);
            pio_sm_clear_fifos(selector_pio, SELECT_SM);
            pio_sm_restart(selector_pio, SELECT_SM);
            pio_sm_exec(selector_pio, SELECT_SM, pio_encode_jmp(selector_offset));
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, FLASH_CS, 1, false);
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, BC250_MISO, 1, false);
            pio_sm_set_enabled(selector_pio, SELECT_SM, true);
            sleep_us(10);
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
            if (active) gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
            /* A RAM-only trial may be unrecoverable over USB if it fails to
             * enumerate. Once routing is armed, the watchdog must not reset
             * the Pico during a legitimate unattended board boot. */
            watchdog_disable();
            atomic_store_explicit(&mode, active ? ACTIVE : PASS_ONLY,
                                  memory_order_release);
            printf("ARMED SPARSE-%s MISO=%s profile=%s\n",
                   active ? "ACTIVE" : "PASS", active ? "PIO-GUARDED" : "DISABLED",
                   PROFILE_NAME);
        }
    } else if (!strcmp(line, "cancel")) {
        gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
        gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
        fail_closed(PROFILE_FAULT);
        printf("CANCELLED output=OFF\n");
    } else {
        printf("ERROR status; arm-pass; arm-active; cancel\n");
    }
    stdio_flush();
}

int main(void) {
    /* If startup never reaches an open USB serial port, reboot back into the
     * Pico's already-installed flash image so picotool can be used again. */
    watchdog_enable(15000, true);
    gpio_init(FLASH_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_input_enabled(FLASH_CS, true);
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
    selector_offset = pio_add_program(selector_pio, &SPARSE_SELECTOR_PROGRAM);
    pio_gpio_init(selector_pio, BC250_CS);
    pio_gpio_init(selector_pio, FLASH_CS);
    pio_gpio_init(selector_pio, BC250_MISO);
#ifdef BC250_FAST_MISO_PAD
    gpio_set_drive_strength(BC250_MISO, GPIO_DRIVE_STRENGTH_12MA);
    gpio_set_slew_rate(BC250_MISO, GPIO_SLEW_RATE_FAST);
#endif
    gpio_disable_pulls(BC250_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_disable_pulls(BC250_MISO);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_input_enabled(FLASH_CS, true);
    gpio_set_oeover(BC250_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_config c = SPARSE_SELECTOR_CONFIG(selector_offset);
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
#ifdef BC250_MISO_PROBE
    pio_sm_claim(watch_pio, PROBE_SM);
    probe_offset = pio_add_program(watch_pio, &miso_probe_program);
    c = miso_probe_program_get_default_config(probe_offset);
    sm_config_set_in_pins(&c, BC250_MISO);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(watch_pio, PROBE_SM, probe_offset, &c);
    pio_sm_set_consecutive_pindirs(watch_pio, PROBE_SM, BC250_MISO, 1, false);
#endif
#ifdef BC250_BUS_SNAPSHOT
    pio_sm_claim(watch_pio, SNAPSHOT_SM);
    snapshot_offset = pio_add_program(watch_pio, &BUS_SNAPSHOT_PROGRAM);
    c = BUS_SNAPSHOT_CONFIG(snapshot_offset);
    sm_config_set_in_pins(&c, BC250_CS);
    sm_config_set_in_shift(&c, false, true, 30);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(watch_pio, SNAPSHOT_SM, snapshot_offset, &c);
    pio_sm_set_consecutive_pindirs(watch_pio, SNAPSHOT_SM, BC250_CS, 6, false);
    snapshot_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(snapshot_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(watch_pio, SNAPSHOT_SM, false));
    dma_channel_configure(snapshot_dma, &dc, snapshot_words,
                          &watch_pio->rxf[SNAPSHOT_SM], SNAPSHOT_WORDS, false);
#endif
    watch_pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM);
    multicore_launch_core1(profile_worker);
    pio_sm_set_enabled(watch_pio, WATCH_SM, true);

    char line[48];
    uint used = 0;
    bool overflow = false;
    for (;;) {
        if (stdio_usb_connected()) watchdog_update();
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
