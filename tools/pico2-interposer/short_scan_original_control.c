/* RAM-only three-word exact-original control for the early four-byte UEFI
 * header scan. The selector advances in PIO within the measured 176 ns
 * minimum CS# gap, then holds a permanent PASS sentinel. Only the first
 * boot pass is substituted; the original BIOS flash remains untouched.
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
#include "hardware/watchdog.h"
#include "short_scan_sequence_od.pio.h"
#include "address_hunt.pio.h"
#include "pins.h"

enum { FLASH_CS = 7u, SELECT_SM = 0u, WATCH_SM = 0u,
       UNARMED = 0u, PASS_ONLY = 1u, ACTIVE = 2u,
       ADDRESS_FAULT = 1u, ARM_FAULT = 2u };
static const char PROFILE_NAME[] = "short-scan-3-original-v01";
static const uint32_t commands[3] = {0x03ae0088u, 0x03ae008cu, 0x03ae0090u};
static const uint32_t replies[3] = {0xeeaa0b00u, 0xa41b15f8u, 0x8c1b1502u};
static PIO const selector_pio = pio0;
static PIO const watcher_pio = pio1;
static uint select_offset, watcher_offset;
static _Atomic uint32_t mode, fault, seen, hits[3];

static void __not_in_flash_func(fail_closed)(uint32_t why) {
    if (atomic_load_explicit(&fault, memory_order_acquire)) return;
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    atomic_store_explicit(&fault, why, memory_order_release);
}

static void __not_in_flash_func(watch_worker)(void) {
    for (;;) {
        if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE &&
            pio_interrupt_get(selector_pio, 0))
            fail_closed(ADDRESS_FAULT);
        if (pio_sm_is_rx_fifo_empty(watcher_pio, WATCH_SM)) continue;
        uint32_t command = watcher_pio->rxf[WATCH_SM];
        atomic_fetch_add_explicit(&seen, 1u, memory_order_relaxed);
        for (uint i = 0; i < 3u; ++i)
            if (command == commands[i])
                atomic_fetch_add_explicit(&hits[i], 1u, memory_order_relaxed);
    }
}

static void status(void) {
    uint32_t current = atomic_load_explicit(&mode, memory_order_relaxed);
    uint32_t level = pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM);
    uint32_t first_pass = pio_interrupt_get(selector_pio, 1) && level == 0u &&
        atomic_load_explicit(&hits[0], memory_order_relaxed) >= 1u &&
        atomic_load_explicit(&hits[1], memory_order_relaxed) >= 1u &&
        atomic_load_explicit(&hits[2], memory_order_relaxed) >= 1u;
    printf("BC250-PICO2-SHORT-SCAN profile=%s clock_hz=%" PRIu32
           " mode=%" PRIu32 " fault=%" PRIu32 " host_cs=%u"
           " relay_oe=%u miso_oe=%u selector_pc=%u fifo=%" PRIu32
           " reply_irq=%u first_pass_complete=%" PRIu32
           " seen=%" PRIu32 " hits=%" PRIu32 "/%" PRIu32 "/%" PRIu32
           " rxstall=%u bios_write=UNAVAILABLE pico_write=UNAVAILABLE\n",
           PROFILE_NAME, clock_get_hz(clk_sys), current,
           atomic_load_explicit(&fault, memory_order_relaxed),
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((selector_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((selector_pio->dbg_padoe >> BC250_MISO) & 1u),
           pio_sm_get_pc(selector_pio, SELECT_SM), level,
           pio_interrupt_get(selector_pio, 1) ? 1u : 0u, first_pass,
           atomic_load_explicit(&seen, memory_order_relaxed),
           atomic_load_explicit(&hits[0], memory_order_relaxed),
           atomic_load_explicit(&hits[1], memory_order_relaxed),
           atomic_load_explicit(&hits[2], memory_order_relaxed),
           (unsigned)((watcher_pio->fdebug >>
               (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u));
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-active") || !strcmp(line, "arm-pass")) {
        bool active = !strcmp(line, "arm-active");
        if (atomic_load_explicit(&mode, memory_order_acquire) != UNARMED ||
            atomic_load_explicit(&fault, memory_order_acquire) || !gpio_get(BC250_CS)) {
            printf("ERROR already armed, faulted or host CS# low\n");
        } else {
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
            gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
            pio_sm_set_enabled(selector_pio, SELECT_SM, false);
            pio_sm_clear_fifos(selector_pio, SELECT_SM);
            pio_sm_restart(selector_pio, SELECT_SM);
            pio_sm_exec(selector_pio, SELECT_SM, pio_encode_jmp(select_offset));
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, FLASH_CS, 1, false);
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, BC250_MISO, 1, false);
            pio_interrupt_clear(selector_pio, 0);
            pio_interrupt_clear(selector_pio, 1);
            if (active) {
                for (uint i = 0; i < 3u; ++i) {
                    pio_sm_put_blocking(selector_pio, SELECT_SM, commands[i] >> 1);
                    pio_sm_put_blocking(selector_pio, SELECT_SM, replies[i]);
                }
                pio_sm_put_blocking(selector_pio, SELECT_SM, UINT32_MAX);
            } else {
                pio_sm_put_blocking(selector_pio, SELECT_SM, UINT32_MAX);
            }
            pio_sm_set_enabled(selector_pio, SELECT_SM, true);
            sleep_us(10);
            uint expected_fifo = active ? 5u : 0u;
            if (pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM) != expected_fifo ||
                pio_interrupt_get(selector_pio, 0)) {
                fail_closed(ARM_FAULT);
                printf("ERROR selector pre-arm FIFO or address fault\n");
            } else {
                selector_pio->fdebug = 1u << (PIO_FDEBUG_TXOVER_LSB + SELECT_SM);
                gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
                if (active) gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
                watchdog_disable();
                atomic_store_explicit(&mode, active ? ACTIVE : PASS_ONLY, memory_order_release);
                printf("ARMED SHORT-SCAN-%s MISO=%s profile=%s queued=%u\n",
                       active ? "ACTIVE" : "PASS",
                       active ? "PIO-GUARDED" : "DISABLED", PROFILE_NAME,
                       active ? 3u : 0u);
            }
        }
    } else if (!strcmp(line, "cancel")) {
        fail_closed(ADDRESS_FAULT);
        printf("CANCELLED output=OFF\n");
    } else {
        printf("ERROR status; arm-pass; arm-active; cancel\n");
    }
    stdio_flush();
}

int main(void) {
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
        for (;;) { printf("ERROR clock setup; output off\n"); sleep_ms(1000); }
    }

    pio_sm_claim(selector_pio, SELECT_SM);
    select_offset = pio_add_program(selector_pio, &short_scan_sequence_od_program);
    pio_gpio_init(selector_pio, BC250_CS);
    pio_gpio_init(selector_pio, FLASH_CS);
    pio_gpio_init(selector_pio, BC250_MISO);
    gpio_disable_pulls(BC250_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_disable_pulls(BC250_MISO);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_input_enabled(FLASH_CS, true);
    gpio_set_oeover(BC250_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_config c = short_scan_sequence_od_program_get_default_config(select_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_out_pins(&c, BC250_MISO, 1);
    sm_config_set_out_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_set_pins(&c, FLASH_CS, 1);
    sm_config_set_sideset_pins(&c, BC250_MISO);
    sm_config_set_jmp_pin(&c, BC250_MOSI);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(selector_pio, SELECT_SM, select_offset, &c);
    pio_sm_set_pins_with_mask(selector_pio, SELECT_SM, 0, 1u << FLASH_CS);
    pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, FLASH_CS, 1, false);
    pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, BC250_MISO, 1, false);

    pio_sm_claim(watcher_pio, WATCH_SM);
    watcher_offset = pio_add_program(watcher_pio, &address_hunt_program);
    c = address_hunt_program_get_default_config(watcher_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(watcher_pio, WATCH_SM, watcher_offset, &c);
    pio_sm_set_consecutive_pindirs(watcher_pio, WATCH_SM, BC250_CS, 3, false);
    watcher_pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM);
    multicore_launch_core1(watch_worker);
    pio_sm_set_enabled(watcher_pio, WATCH_SM, true);

    printf("BC250-PICO2-SHORT-SCAN ready profile=%s outputs=OFF"
           " bios_write=UNAVAILABLE pico_write=UNAVAILABLE\n", PROFILE_NAME);
    char line[32];
    unsigned used = 0;
    for (;;) {
        int ch = getchar_timeout_us(0);
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[used] = 0;
            command(line);
            used = 0;
        } else if (ch >= 0 && used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        }
        tight_loop_contents();
    }
}
