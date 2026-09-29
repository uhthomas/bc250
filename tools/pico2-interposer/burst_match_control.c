/* RAM-only exact-original 64-byte SPI control. No BIOS or Pico flash writes.
 * PIO0 leaves the original flash selected until target READ03's 31-bit
 * prefix matches, then releases its CS# before streaming the pinned original
 * reply through GP5. A mismatched command remains entirely on the flash.
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
#include "burst_match_late_od.pio.h"
#include "address_hunt.pio.h"
#include "burst_original_reply.h"
#include "pins.h"

enum { FLASH_CS = 7u, SELECT_SM = 0u, WATCH_SM = 0u };
enum { UNARMED = 0u, PASS_ONLY = 1u, ACTIVE = 2u };
enum { ADDRESS_FAULT = 1u, RX_STALL_FAULT = 2u,
       DMA_FAULT = 4u, TX_STALL_FAULT = 5u };
static const char PROFILE_NAME[] = "uefi-burst-late-match-v01";
static PIO const selector_pio = pio0;
static PIO const watch_pio = pio1;
static uint select_offset, watch_offset, data_dma;
static _Atomic uint32_t mode, fault, seen, trigger_seen, target_seen,
                        verified, target_diag, target_data_diag, fault_diag;

/* PC[5:0], TX level[9:6], SM enable[10], relay OE[11], MISO OE[12],
 * host CS#[13], TX stall[14], TX overflow[15]. */
static uint32_t __not_in_flash_func(selector_diag)(void) {
    return (pio_sm_get_pc(selector_pio, SELECT_SM) & 63u) |
           ((uint32_t)pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM) << 6) |
           (((selector_pio->ctrl >> SELECT_SM) & 1u) << 10) |
           (((selector_pio->dbg_padoe >> FLASH_CS) & 1u) << 11) |
           (((selector_pio->dbg_padoe >> BC250_MISO) & 1u) << 12) |
           ((uint32_t)gpio_get(BC250_CS) << 13) |
           (((selector_pio->fdebug >> (PIO_FDEBUG_TXSTALL_LSB + SELECT_SM)) & 1u) << 14) |
           (((selector_pio->fdebug >> (PIO_FDEBUG_TXOVER_LSB + SELECT_SM)) & 1u) << 15);
}

static void __not_in_flash_func(fail_closed)(uint32_t why) {
    if (atomic_load_explicit(&fault, memory_order_acquire)) return;
    atomic_store_explicit(&fault_diag, selector_diag(), memory_order_release);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    atomic_store_explicit(&fault, why, memory_order_release);
}

static void __not_in_flash_func(command_worker)(void) {
    for (;;) {
        if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE &&
            !atomic_load_explicit(&fault, memory_order_relaxed)) {
            if (pio_interrupt_get(selector_pio, 0)) fail_closed(ADDRESS_FAULT);
            if ((watch_pio->fdebug >> (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u)
                fail_closed(RX_STALL_FAULT);
            if (pio_interrupt_get(selector_pio, 1) &&
                !atomic_load_explicit(&verified, memory_order_relaxed)) {
                pio_interrupt_clear(selector_pio, 1);
                if ((selector_pio->fdebug >> (PIO_FDEBUG_TXSTALL_LSB + SELECT_SM)) & 1u)
                    fail_closed(TX_STALL_FAULT);
                else if (dma_channel_is_busy(data_dma) ||
                         dma_channel_hw_addr(data_dma)->transfer_count ||
                         pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM))
                    fail_closed(DMA_FAULT);
                else
                    atomic_store_explicit(&verified, 1u, memory_order_release);
            }
        }
        if (pio_sm_is_rx_fifo_empty(watch_pio, WATCH_SM)) {
            tight_loop_contents();
            continue;
        }
        uint32_t command = watch_pio->rxf[WATCH_SM];
        atomic_fetch_add_explicit(&seen, 1u, memory_order_relaxed);
        if (command == BURST_TRIGGER_COMMAND)
            atomic_fetch_add_explicit(&trigger_seen, 1u, memory_order_relaxed);
        else if (command == BURST_TARGET_COMMAND) {
            uint32_t previous = atomic_fetch_add_explicit(&target_seen, 1u, memory_order_relaxed);
            if (previous == 0u)
                atomic_store_explicit(&target_diag, selector_diag(), memory_order_relaxed);
            if (atomic_load_explicit(&mode, memory_order_relaxed) == ACTIVE &&
                !atomic_load_explicit(&verified, memory_order_relaxed) &&
                !atomic_load_explicit(&fault, memory_order_relaxed)) {
                busy_wait_us_32(1);
                atomic_store_explicit(&target_data_diag, selector_diag(), memory_order_relaxed);
            }
        }
    }
}

static void status(void) {
    printf("BC250-PICO2-BURST-MATCH profile=%s clock_hz=%" PRIu32
           " mode=%" PRIu32 " fault=%" PRIu32 " host_cs=%u"
           " relay_oe=%u miso_oe=%u seen=%" PRIu32
           " trigger=%" PRIu32 " target=%" PRIu32 " verified=%" PRIu32
           " dma_remaining=%" PRIu32 " fifo=%u rxstall=%u"
           " selector=%04" PRIx32 " target_diag=%04" PRIx32
           " target_data_diag=%04" PRIx32 " fault_diag=%04" PRIx32
           " bios_write=UNAVAILABLE\n",
           PROFILE_NAME, clock_get_hz(clk_sys),
           atomic_load_explicit(&mode, memory_order_relaxed),
           atomic_load_explicit(&fault, memory_order_relaxed),
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((selector_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((selector_pio->dbg_padoe >> BC250_MISO) & 1u),
           atomic_load_explicit(&seen, memory_order_relaxed),
           atomic_load_explicit(&trigger_seen, memory_order_relaxed),
           atomic_load_explicit(&target_seen, memory_order_relaxed),
           atomic_load_explicit(&verified, memory_order_relaxed),
           (uint32_t)dma_channel_hw_addr(data_dma)->transfer_count,
           pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM),
           (unsigned)((watch_pio->fdebug >> (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u),
           selector_diag(),
           atomic_load_explicit(&target_diag, memory_order_relaxed),
           atomic_load_explicit(&target_data_diag, memory_order_relaxed),
           atomic_load_explicit(&fault_diag, memory_order_relaxed));
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-pass") || !strcmp(line, "arm-active")) {
        bool active = !strcmp(line, "arm-active");
        if (atomic_load_explicit(&mode, memory_order_acquire) != UNARMED ||
            atomic_load_explicit(&fault, memory_order_acquire) || !gpio_get(BC250_CS)) {
            printf("ERROR already armed, faulted or host CS# low\n");
        } else {
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
            gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
            pio_interrupt_clear(selector_pio, 0);
            pio_interrupt_clear(selector_pio, 1);
            pio_sm_set_enabled(selector_pio, SELECT_SM, false);
            pio_sm_clear_fifos(selector_pio, SELECT_SM);
            pio_sm_restart(selector_pio, SELECT_SM);
            pio_sm_exec(selector_pio, SELECT_SM, pio_encode_jmp(select_offset));
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, FLASH_CS, 1, false);
            pio_sm_set_consecutive_pindirs(selector_pio, SELECT_SM, BC250_MISO, 1, false);
            selector_pio->txf[SELECT_SM] = active ? (BURST_TARGET_COMMAND >> 1) : UINT32_MAX;
            pio_sm_set_enabled(selector_pio, SELECT_SM, true);
            sleep_us(10);
            if (!pio_sm_is_tx_fifo_empty(selector_pio, SELECT_SM) ||
                pio_sm_get_pc(selector_pio, SELECT_SM) == select_offset) {
                fail_closed(DMA_FAULT);
                printf("ERROR target prefix was not loaded\n");
            } else {
                if (active) {
                    selector_pio->txf[SELECT_SM] = burst_original_words[0];
                    dma_channel_set_read_addr(data_dma, burst_original_words + 1, false);
                    dma_channel_set_trans_count(data_dma, BURST_WORD_COUNT - 1u, false);
                    dma_channel_start(data_dma);
                    sleep_us(10);
                }
                selector_pio->fdebug = (1u << (PIO_FDEBUG_TXSTALL_LSB + SELECT_SM)) |
                                       (1u << (PIO_FDEBUG_TXOVER_LSB + SELECT_SM));
                watch_pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM);
                gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
                if (active) gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
                watchdog_disable();
                atomic_store_explicit(&mode, active ? ACTIVE : PASS_ONLY, memory_order_release);
                printf("ARMED BURST-%s MISO=%s profile=%s\n",
                       active ? "ACTIVE" : "PASS",
                       active ? "PIO-GUARDED" : "DISABLED", PROFILE_NAME);
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
    select_offset = pio_add_program(selector_pio, &burst_match_late_od_program);
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
    pio_sm_config c = burst_match_late_od_program_get_default_config(select_offset);
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

    data_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(data_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_dreq(&dc, pio_get_dreq(selector_pio, SELECT_SM, true));
    dma_channel_configure(data_dma, &dc, &selector_pio->txf[SELECT_SM],
                          burst_original_words + 1, BURST_WORD_COUNT - 1u, false);

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
    multicore_launch_core1(command_worker);
    pio_sm_set_enabled(watch_pio, WATCH_SM, true);

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
