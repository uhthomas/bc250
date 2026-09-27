/* Original BIOS flash CS# pass-through diagnostic. RAM-only Pico image.
 * GP2 observes motherboard CS#; GP7 sinks the lifted flash CS# leg.
 * The existing board-powered resistor releases flash CS# to its own VCC.
 * MISO is always an input; no firmware bytes are substituted here.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "cs_open_drain.pio.h"
#include "pins.h"

enum { FLASH_CS = 7u, CS_SM = 0u };
static PIO const pio = pio0;
static uint pio_offset;
static bool armed;
static bool gate;

static void gate_off(void) {
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate = false;
}

static void status(void) {
    printf("BC250-PICO2-CS-PASS v2 clock_hz=%" PRIu32
           " armed=%u gate=%u host_cs=%u flash_cs_input=DISABLED pio_oe=%u out_override=LOW"
           " miso=INPUT bios_write=UNAVAILABLE\n",
           clock_get_hz(clk_sys), armed ? 1u : 0u, gate ? 1u : 0u,
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((pio->dbg_padoe >> FLASH_CS) & 1u));
}

static void command(const char *line) {
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
    } else {
        printf("ERROR commands: status; arm-pass; cancel\n");
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
