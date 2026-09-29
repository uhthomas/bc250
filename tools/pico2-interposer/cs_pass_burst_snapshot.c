/* RAM-only, read-only 64-byte UEFI SPI-burst timing capture. The proven PIO
 * relay keeps original BIOS flash CS# on GP7. MISO is always input/high-Z.
 * PIO1 core1 watches READ03 commands; PIO1 DMA samples GP2..GP7 around the
 * transaction after 0x03ae00c0, expected to start at 0x03ae0100.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "hardware/watchdog.h"
#include "cs_open_drain.pio.h"
#include "address_hunt.pio.h"
#include "bus_snapshot.pio.h"
#include "pins.h"

enum { FLASH_CS = 7u, RELAY_SM = 0u, WATCH_SM = 0u, SAMPLE_SM = 1u,
       SAMPLE_WORDS = 1024u, TRIGGER_COMMAND = 0x03ae00c0u,
       EXPECTED_COMMAND = 0x03ae0100u };
static PIO const relay_pio = pio0;
static PIO const input_pio = pio1;
static uint relay_offset, watch_offset, sample_offset, sample_dma;
static uint32_t samples[SAMPLE_WORDS];
static _Atomic uint32_t seen, trigger_count, previous_command;
static _Atomic bool armed, capture_started;

static void __not_in_flash_func(command_worker)(void) {
    for (;;) {
        if (pio_sm_is_rx_fifo_empty(input_pio, WATCH_SM)) {
            tight_loop_contents();
            continue;
        }
        uint32_t command = input_pio->rxf[WATCH_SM];
        atomic_store_explicit(&previous_command, command, memory_order_relaxed);
        atomic_fetch_add_explicit(&seen, 1u, memory_order_relaxed);
        if (command != TRIGGER_COMMAND ||
            !atomic_load_explicit(&armed, memory_order_acquire) ||
            atomic_load_explicit(&capture_started, memory_order_relaxed))
            continue;
        atomic_fetch_add_explicit(&trigger_count, 1u, memory_order_relaxed);
        pio_sm_set_enabled(input_pio, SAMPLE_SM, false);
        pio_sm_clear_fifos(input_pio, SAMPLE_SM);
        pio_sm_restart(input_pio, SAMPLE_SM);
        pio_sm_exec(input_pio, SAMPLE_SM, pio_encode_jmp(sample_offset));
        dma_channel_set_write_addr(sample_dma, samples, false);
        dma_channel_set_trans_count(sample_dma, SAMPLE_WORDS, false);
        dma_channel_start(sample_dma);
        pio_sm_set_enabled(input_pio, SAMPLE_SM, true);
        atomic_store_explicit(&capture_started, true, memory_order_release);
    }
}

static void status(void) {
    printf("BC250-PICO2-CS-PASS-BURST v1 clock_hz=%" PRIu32
           " armed=%u host_cs=%u relay_oe=%u miso_oe=%u"
           " seen=%" PRIu32 " last=%08" PRIx32 " trigger=%" PRIu32
           " capture_started=%u remaining=%" PRIu32 " watch_rxstall=%u"
           " bios_write=UNAVAILABLE\n",
           clock_get_hz(clk_sys),
           atomic_load_explicit(&armed, memory_order_acquire) ? 1u : 0u,
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((relay_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((input_pio->dbg_padoe >> BC250_MISO) & 1u),
           atomic_load_explicit(&seen, memory_order_relaxed),
           atomic_load_explicit(&previous_command, memory_order_relaxed),
           atomic_load_explicit(&trigger_count, memory_order_relaxed),
           atomic_load_explicit(&capture_started, memory_order_acquire) ? 1u : 0u,
           (uint32_t)dma_channel_hw_addr(sample_dma)->transfer_count,
           (unsigned)((input_pio->fdebug >> (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u));
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-pass") || !strcmp(line, "arm-pass-recovery")) {
        bool recovery = !strcmp(line, "arm-pass-recovery");
        if (atomic_load_explicit(&armed, memory_order_acquire) ||
            (!recovery && !gpio_get(BC250_CS))) {
            printf("ERROR already armed or motherboard CS# low\n");
        } else {
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
            pio_sm_set_enabled(relay_pio, RELAY_SM, false);
            pio_sm_clear_fifos(relay_pio, RELAY_SM);
            pio_sm_restart(relay_pio, RELAY_SM);
            pio_sm_exec(relay_pio, RELAY_SM, pio_encode_jmp(relay_offset));
            pio_sm_set_consecutive_pindirs(relay_pio, RELAY_SM, FLASH_CS, 1, false);
            pio_sm_set_enabled(relay_pio, RELAY_SM, true);
            sleep_us(10);
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
            watchdog_disable();
            atomic_store_explicit(&armed, true, memory_order_release);
            printf("ARMED CS-PASS-BURST MISO=INPUT target=%08x recovery=%u\n",
                   EXPECTED_COMMAND, recovery ? 1u : 0u);
        }
    } else if (!strcmp(line, "dump")) {
        if (!atomic_load_explicit(&capture_started, memory_order_acquire) ||
            dma_channel_is_busy(sample_dma)) {
            printf("ERROR capture incomplete\n");
        } else {
            printf("BURST-SNAPSHOT words=%u samples=%u trigger=%08x expected=%08x\n",
                   SAMPLE_WORDS, SAMPLE_WORDS * 5u, TRIGGER_COMMAND, EXPECTED_COMMAND);
            for (uint i = 0; i < SAMPLE_WORDS; ++i)
                printf("%08" PRIx32 "%c", samples[i], i % 8u == 7u ? '\n' : ' ');
            printf("BURST-END\n");
        }
    } else if (!strcmp(line, "cancel")) {
        gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
        atomic_store_explicit(&armed, false, memory_order_release);
        printf("CANCELLED relay=OFF\n");
    } else {
        printf("ERROR status; arm-pass; arm-pass-recovery; dump; cancel\n");
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

    pio_sm_claim(relay_pio, RELAY_SM);
    relay_offset = pio_add_program(relay_pio, &cs_open_drain_program);
    pio_gpio_init(relay_pio, BC250_CS);
    pio_gpio_init(relay_pio, FLASH_CS);
    pio_sm_config c = cs_open_drain_program_get_default_config(relay_offset);
    sm_config_set_set_pins(&c, FLASH_CS, 1);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(relay_pio, RELAY_SM, relay_offset, &c);
    pio_sm_set_pins_with_mask(relay_pio, RELAY_SM, 0, 1u << FLASH_CS);
    pio_sm_set_consecutive_pindirs(relay_pio, RELAY_SM, FLASH_CS, 1, false);
    pio_sm_set_enabled(relay_pio, RELAY_SM, true);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);

    pio_sm_claim(input_pio, WATCH_SM);
    watch_offset = pio_add_program(input_pio, &address_hunt_program);
    c = address_hunt_program_get_default_config(watch_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(input_pio, WATCH_SM, watch_offset, &c);
    pio_sm_set_consecutive_pindirs(input_pio, WATCH_SM, BC250_CS, 3, false);

    pio_sm_claim(input_pio, SAMPLE_SM);
    sample_offset = pio_add_program(input_pio, &bus_snapshot_program);
    c = bus_snapshot_program_get_default_config(sample_offset);
    sm_config_set_in_pins(&c, BC250_CS);
    sm_config_set_in_shift(&c, false, true, 30);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(input_pio, SAMPLE_SM, sample_offset, &c);
    pio_sm_set_consecutive_pindirs(input_pio, SAMPLE_SM, BC250_CS, 6, false);
    sample_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(sample_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(input_pio, SAMPLE_SM, false));
    dma_channel_configure(sample_dma, &dc, samples, &input_pio->rxf[SAMPLE_SM],
                          SAMPLE_WORDS, false);
    input_pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM);
    multicore_launch_core1(command_worker);
    pio_sm_set_enabled(input_pio, WATCH_SM, true);

    char line[80];
    for (;;) {
        if (fgets(line, sizeof(line), stdin)) {
            line[strcspn(line, "\r\n")] = '\0';
            command(line);
        } else {
            tight_loop_contents();
        }
    }
}
