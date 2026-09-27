/* RAM-only original-flash CS# pass-through plus address-context hunter.
 * GP2 observes motherboard CS#; GP7 sinks the lifted flash CS# leg.
 * GP3/GP4 observe SCLK/MOSI. GP5 MISO remains an input. No data substitution.
 * Captures selected READ03 commands and their two immediate predecessors.
 */
#include <stdatomic.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "cs_open_drain.pio.h"
#include "address_hunt.pio.h"
#include "pins.h"

enum { FLASH_CS = 7u, CS_SM = 0u, HUNT_SM = 0u, MAX_HITS = 16384u };
struct hit { uint32_t transaction, command, previous, previous2; };
static struct hit hits[MAX_HITS];
static PIO const pio = pio0;
static PIO const hunt_pio = pio1;
static uint pio_offset;
static uint hunt_offset;
static bool armed;
static bool gate;
static _Atomic bool hunt_running;
static volatile uint32_t hunt_seen, hunt_count, hunt_overflow;
static uint32_t previous_command, previous2_command;

static bool in_interest_range(uint32_t address) {
    return (address >= 0x8eabd0u && address < 0x8eb080u) ||
           (address >= 0x8f0800u && address < 0x8f0c00u) ||
           (address >= 0x8fed50u && address < 0x8ff050u) ||
           (address >= 0x99f470u && address < 0x99f770u) ||
           (address >= 0x9db040u && address < 0x9db340u);
}

static void __not_in_flash_func(hunt_worker)(void) {
    for (;;) {
        if (!atomic_load_explicit(&hunt_running, memory_order_acquire)) {
            tight_loop_contents();
            continue;
        }
        if (pio_sm_is_rx_fifo_empty(hunt_pio, HUNT_SM)) continue;
        uint32_t command = hunt_pio->rxf[HUNT_SM];
        uint32_t transaction = hunt_seen++;
        if ((command >> 24) == 3u && in_interest_range(command & 0xffffffu)) {
            uint32_t count = hunt_count;
            if (count < MAX_HITS) {
                hits[count] = (struct hit){transaction, command,
                                           previous_command, previous2_command};
                hunt_count = count + 1u;
            } else {
                hunt_overflow++;
            }
        }
        previous2_command = previous_command;
        previous_command = command;
    }
}

static void gate_off(void) {
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate = false;
}

static void status(void) {
    printf("BC250-PICO2-CS-PASS-HUNT v1 clock_hz=%" PRIu32
           " armed=%u gate=%u host_cs=%u flash_cs_input=DISABLED pio_oe=%u out_override=LOW"
           " miso=INPUT bios_write=UNAVAILABLE max_hits=%u\n",
           clock_get_hz(clk_sys), armed ? 1u : 0u, gate ? 1u : 0u,
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((pio->dbg_padoe >> FLASH_CS) & 1u), MAX_HITS);
}

static void hunt(uint32_t timeout_ms) {
    if (!armed) {
        printf("ERROR arm-pass before hunt-pass\n");
        return;
    }
    if (atomic_load_explicit(&hunt_running, memory_order_acquire)) {
        printf("ERROR hunt already running\n");
        return;
    }
    pio_sm_config c = address_hunt_program_get_default_config(hunt_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(hunt_pio, HUNT_SM, hunt_offset, &c);
    pio_sm_set_consecutive_pindirs(hunt_pio, HUNT_SM, BC250_CS, 3, false);
    hunt_seen = hunt_count = hunt_overflow = 0;
    previous_command = previous2_command = 0;
    uint32_t stall_mask = 1u << (PIO_FDEBUG_RXSTALL_LSB + HUNT_SM);
    hunt_pio->fdebug = stall_mask;
    atomic_store_explicit(&hunt_running, true, memory_order_release);
    pio_sm_set_enabled(hunt_pio, HUNT_SM, true);
    printf("ARMED HUNT-PASS ranges=5 max_hits=%u timeout_ms=%" PRIu32
           " flash_cs=OPEN_DRAIN outputs=CS_ONLY\n", MAX_HITS, timeout_ms);
    stdio_flush();
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    bool cancelled = false;
    while (!time_reached(deadline)) {
        int ch = getchar_timeout_us(0);
        if (ch == 'x' || ch == 'X') { cancelled = true; break; }
        tight_loop_contents();
    }
    pio_sm_set_enabled(hunt_pio, HUNT_SM, false);
    sleep_ms(10); /* allow core1 to drain the last command FIFO */
    atomic_store_explicit(&hunt_running, false, memory_order_release);
    sleep_ms(2);
    uint32_t flags = (hunt_pio->fdebug & stall_mask) ? 1u : 0u;
    printf("HITS seen=%" PRIu32 " kept=%" PRIu32 " overflow=%" PRIu32
           " stall=%" PRIu32 " cancelled=%u\n", hunt_seen, hunt_count,
           hunt_overflow, flags, cancelled ? 1u : 0u);
    for (uint32_t i = 0; i < hunt_count; ++i)
        printf("%" PRIu32 " %08" PRIx32 " %08" PRIx32 " %08" PRIx32 "\n",
               hits[i].transaction, hits[i].command,
               hits[i].previous, hits[i].previous2);
    printf("DONEH\n");
    stdio_flush();
}

static void command(const char *line) {
    uint32_t timeout_ms;
    char extra;
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-pass")) {
        if (armed) {
            printf("ERROR already armed\n");
        } else {
            /* Restart at release/wait-for-high so a previous cancelled read
             * cannot leave PIO OE asserted when the override is removed. */
            gate_off();
            pio_sm_set_enabled(pio, CS_SM, false);
            pio_sm_restart(pio, CS_SM);
            pio_sm_exec(pio, CS_SM, pio_encode_jmp(pio_offset));
            pio_sm_set_consecutive_pindirs(pio, CS_SM, FLASH_CS, 1, false);
            pio_sm_set_enabled(pio, CS_SM, true);
            sleep_us(10);
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
            armed = true;
            gate = true;
            printf("ARMED CS-PASS GP7=open-drain-sink wait-for-host-CS-high\n");
        }
    } else if (!strcmp(line, "cancel")) {
        gate_off();
        armed = false;
        printf("CANCELLED CS-PASS output=OFF\n");
    } else if (sscanf(line, "hunt-pass %" SCNu32 " %c", &timeout_ms, &extra) == 1 &&
               timeout_ms >= 1000u && timeout_ms <= 120000u) {
        hunt(timeout_ms);
    } else {
        printf("ERROR commands: status; arm-pass; hunt-pass TIMEOUT_MS; cancel\n");
    }
    stdio_flush();
}

int main(void) {
    /* Set the fail-safe pad overrides before any PIO setup or USB wait. */
    gpio_init(FLASH_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_input_enabled(FLASH_CS, false);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate_off();
    gpio_init(BC250_CS);
    gpio_disable_pulls(BC250_CS);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_oeover(BC250_CS, GPIO_OVERRIDE_LOW);
    gpio_init(BC250_MISO);
    gpio_disable_pulls(BC250_MISO);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    for (uint pin = BC250_SCLK; pin <= BC250_MOSI; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }

    /* The pass-through uses 200 MHz/1.20 V for the measured 40 ns setup.
     * This is an experimental overclock above RP2350's rated 150 MHz. */
    vreg_set_voltage(VREG_VOLTAGE_1_20);
    sleep_ms(10);
    bool clock_ok = set_sys_clock_khz(200000, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != 200000000u) {
        for (;;) { printf("ERROR clock setup failed; output off\n"); sleep_ms(1000); }
    }

    pio_sm_claim(pio, CS_SM);
    pio_offset = pio_add_program(pio, &cs_open_drain_program);
    pio_gpio_init(pio, BC250_CS);
    pio_gpio_init(pio, FLASH_CS);
    gpio_disable_pulls(BC250_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_input_enabled(FLASH_CS, false);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate_off();
    pio_sm_config config = cs_open_drain_program_get_default_config(pio_offset);
    sm_config_set_set_pins(&config, FLASH_CS, 1);
    sm_config_set_clkdiv_int_frac(&config, 1, 0);
    pio_sm_init(pio, CS_SM, pio_offset, &config);
    pio_sm_set_pins_with_mask(pio, CS_SM, 0, 1u << FLASH_CS);
    pio_sm_set_consecutive_pindirs(pio, CS_SM, FLASH_CS, 1, false);
    pio_sm_set_enabled(pio, CS_SM, true);
    gate_off();

    pio_sm_claim(hunt_pio, HUNT_SM);
    hunt_offset = pio_add_program(hunt_pio, &address_hunt_program);
    for (uint pin = BC250_CS; pin <= BC250_MOSI; ++pin) {
        /* PIO1 reads raw pad inputs regardless of function mux. Do not move
         * GP2 away from PIO0, which is maintaining the live CS# relay. */
        gpio_disable_pulls(pin);
        gpio_set_input_enabled(pin, true);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    multicore_launch_core1(hunt_worker);

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
