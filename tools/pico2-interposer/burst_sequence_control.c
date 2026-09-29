/* RAM-only exact-original 16 x 64-byte board control. The first matching
 * READ03 is 0xae0140; core1 prepares the next sequential address within
 * the measured ~1.07 us CS# high gap. After 16 replies the original flash
 * serves all subsequent reads. No BIOS or Pico flash writes exist here.
 * The private sequence header is generated from the pinned working ROM.
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
#include "burst_sequence_original.h"
#include "pins.h"

enum { FLASH_CS = 7u, SELECT_SM = 0u,
       UNARMED = 0u, PASS_ONLY = 1u, ACTIVE = 2u,
       ADDRESS_FAULT = 1u, DMA_FAULT = 2u,
       TX_STALL_FAULT = 3u, LATE_FAULT = 4u };
static const char PROFILE_NAME[] = "uefi-burst-16-original-v01";
static PIO const selector_pio = pio0;
static uint select_offset, data_dma;
static _Atomic uint32_t mode, fault, completed, max_rearm_cycles,
                        fault_diag, first_diag, last_diag;

static uint32_t __not_in_flash_func(cycles_now)(void) {
    uint32_t cycles;
    __asm__ volatile("rdcycle %0" : "=r"(cycles));
    return cycles;
}

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
    atomic_store_explicit(&fault_diag, selector_diag(), memory_order_relaxed);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    atomic_store_explicit(&fault, why, memory_order_release);
}

static void __not_in_flash_func(prepare_reply)(uint32_t index) {
    pio_sm_set_enabled(selector_pio, SELECT_SM, false);
    pio_sm_clear_fifos(selector_pio, SELECT_SM);
    pio_sm_restart(selector_pio, SELECT_SM);
    pio_sm_exec(selector_pio, SELECT_SM, pio_encode_jmp(select_offset));
    pio_interrupt_clear(selector_pio, 0);
    pio_interrupt_clear(selector_pio, 1);
    selector_pio->txf[SELECT_SM] =
        (0x03000000u | (ORIGINAL_SEQUENCE_START + index * 0x40u)) >> 1;
    pio_sm_set_enabled(selector_pio, SELECT_SM, true);
    selector_pio->txf[SELECT_SM] = original_sequence_words[index][0];
    dma_channel_set_read_addr(data_dma, original_sequence_words[index] + 1, false);
    dma_channel_set_trans_count(data_dma, ORIGINAL_SEQUENCE_WORDS - 1u, false);
    dma_channel_start(data_dma);
}

static void __not_in_flash_func(completion_worker)(void) {
    uint32_t inhibit;
    __asm__ volatile("csrr %0, mcountinhibit" : "=r"(inhibit));
    inhibit &= ~1u;
    __asm__ volatile("csrw mcountinhibit, %0" : : "r"(inhibit));
    for (;;) {
        if (atomic_load_explicit(&mode, memory_order_relaxed) != ACTIVE ||
            atomic_load_explicit(&fault, memory_order_relaxed)) continue;
        if (pio_interrupt_get(selector_pio, 0)) {
            fail_closed(ADDRESS_FAULT);
            continue;
        }
        if (!pio_interrupt_get(selector_pio, 1)) continue;
        uint32_t begin = cycles_now();
        pio_interrupt_clear(selector_pio, 1);
        if ((selector_pio->fdebug >> (PIO_FDEBUG_TXSTALL_LSB + SELECT_SM)) & 1u) {
            fail_closed(TX_STALL_FAULT);
            continue;
        }
        if (dma_channel_is_busy(data_dma) ||
            dma_channel_hw_addr(data_dma)->transfer_count ||
            pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM)) {
            fail_closed(DMA_FAULT);
            continue;
        }
        uint32_t index = atomic_load_explicit(&completed, memory_order_relaxed);
        if (index >= ORIGINAL_SEQUENCE_COUNT) {
            fail_closed(DMA_FAULT);
            continue;
        }
        if (index == 0u)
            atomic_store_explicit(&first_diag, selector_diag(), memory_order_relaxed);
        atomic_store_explicit(&completed, index + 1u, memory_order_release);
        if (index + 1u == ORIGINAL_SEQUENCE_COUNT) {
            atomic_store_explicit(&last_diag, selector_diag(), memory_order_relaxed);
            continue;
        }
        if (!gpio_get(BC250_CS)) {
            fail_closed(LATE_FAULT);
            continue;
        }
        prepare_reply(index + 1u);
        uint32_t elapsed = cycles_now() - begin;
        uint32_t max = atomic_load_explicit(&max_rearm_cycles, memory_order_relaxed);
        if (elapsed > max)
            atomic_store_explicit(&max_rearm_cycles, elapsed, memory_order_relaxed);
        if (!gpio_get(BC250_CS)) fail_closed(LATE_FAULT);
    }
}

static void status(void) {
    printf("BC250-PICO2-BURST-SEQUENCE profile=%s clock_hz=%" PRIu32
           " mode=%" PRIu32 " fault=%" PRIu32 " host_cs=%u"
           " relay_oe=%u miso_oe=%u completed=%" PRIu32
           " total=%u max_rearm_cycles=%" PRIu32
           " dma_remaining=%" PRIu32 " fifo=%u"
           " selector=%04" PRIx32 " first_diag=%04" PRIx32
           " last_diag=%04" PRIx32 " fault_diag=%04" PRIx32
           " bios_write=UNAVAILABLE pico_write=UNAVAILABLE\n",
           PROFILE_NAME, clock_get_hz(clk_sys),
           atomic_load_explicit(&mode, memory_order_relaxed),
           atomic_load_explicit(&fault, memory_order_relaxed),
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((selector_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((selector_pio->dbg_padoe >> BC250_MISO) & 1u),
           atomic_load_explicit(&completed, memory_order_relaxed),
           ORIGINAL_SEQUENCE_COUNT,
           atomic_load_explicit(&max_rearm_cycles, memory_order_relaxed),
           (uint32_t)dma_channel_hw_addr(data_dma)->transfer_count,
           pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM),
           selector_diag(),
           atomic_load_explicit(&first_diag, memory_order_relaxed),
           atomic_load_explicit(&last_diag, memory_order_relaxed),
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
            selector_pio->txf[SELECT_SM] = active ?
                ((0x03000000u | ORIGINAL_SEQUENCE_START) >> 1) : UINT32_MAX;
            pio_sm_set_enabled(selector_pio, SELECT_SM, true);
            sleep_us(10);
            if (!pio_sm_is_tx_fifo_empty(selector_pio, SELECT_SM) ||
                pio_sm_get_pc(selector_pio, SELECT_SM) == select_offset) {
                fail_closed(DMA_FAULT);
                printf("ERROR target prefix was not loaded\n");
            } else {
                if (active) {
                    selector_pio->txf[SELECT_SM] = original_sequence_words[0][0];
                    dma_channel_set_read_addr(data_dma, original_sequence_words[0] + 1, false);
                    dma_channel_set_trans_count(data_dma, ORIGINAL_SEQUENCE_WORDS - 1u, false);
                    dma_channel_start(data_dma);
                    sleep_us(10);
                }
                selector_pio->fdebug = (1u << (PIO_FDEBUG_TXSTALL_LSB + SELECT_SM)) |
                                       (1u << (PIO_FDEBUG_TXOVER_LSB + SELECT_SM));
                gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
                if (active) gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
                watchdog_disable();
                atomic_store_explicit(&mode, active ? ACTIVE : PASS_ONLY, memory_order_release);
                printf("ARMED BURST-%s MISO=%s profile=%s count=%u\n",
                       active ? "ACTIVE" : "PASS",
                       active ? "PIO-GUARDED" : "DISABLED", PROFILE_NAME,
                       ORIGINAL_SEQUENCE_COUNT);
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
                          original_sequence_words[0] + 1,
                          ORIGINAL_SEQUENCE_WORDS - 1u, false);
    multicore_launch_core1(completion_worker);

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
