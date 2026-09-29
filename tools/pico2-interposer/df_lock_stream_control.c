/* RAM-only selector for an UNTESTED equal-length UEFI DF-lock control.
 * The 1.33 MiB reply payload must first be written once to reserved Pico
 * QSPI flash and SHA256-verified before ACTIVE can be armed. The existing
 * BIOS flash is never written. Core1 rearms each 64-byte address inside the
 * measured ~1.07 us gap; the same contiguous range is served on both UEFI
 * passes, then all later reads use the original flash. This is research code,
 * not a known VCN fix. The private first-word header stays under output/.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/address_mapped.h"
#include "hardware/dma.h"
#include "hardware/flash.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "hardware/watchdog.h"
#include "pico/sha256.h"
#ifdef DF_LOCK_EARLY_RELEASE
#include "burst_match_early_od.pio.h"
#define SELECT_PROGRAM burst_match_early_od_program
#define SELECT_PREFIX_SHIFT 6u
#else
#include "burst_match_late_od.pio.h"
#define SELECT_PROGRAM burst_match_late_od_program
#define SELECT_PREFIX_SHIFT 1u
#endif
#ifdef DF_LOCK_WIRE_CAPTURE
#include "burst_wire_capture.pio.h"
#endif
#ifndef DF_LOCK_PAYLOAD_HEADER
#define DF_LOCK_PAYLOAD_HEADER "df_lock_same_length_payload.h"
#endif
#include DF_LOCK_PAYLOAD_HEADER
#include "pins.h"

enum { FLASH_CS = 7u, SELECT_SM = 0u,
       UNARMED = 0u, PASS_ONLY = 1u, ACTIVE = 2u,
       ADDRESS_FAULT = 1u, DMA_FAULT = 2u,
       TX_STALL_FAULT = 3u, LATE_FAULT = 4u, PAYLOAD_FAULT = 5u,
       TOTAL_REPLIES = DF_LOCK_BLOCK_COUNT * 2u,
       PAYLOAD_BYTES = 1327104u };
#ifndef DF_LOCK_PROFILE_NAME
#define DF_LOCK_PROFILE_NAME "df-lock-same-length-two-pass-UNTESTED-v01"
#endif
static const char PROFILE_NAME[] = DF_LOCK_PROFILE_NAME;
#ifndef DF_LOCK_PAYLOAD_SHA256_BYTES
#define DF_LOCK_PAYLOAD_SHA256_BYTES \
    0x94, 0x69, 0x3a, 0xc4, 0x3e, 0x90, 0x23, 0x6b, \
    0x77, 0xe6, 0xfc, 0x2b, 0xe6, 0x4c, 0x4a, 0xb8, \
    0xe4, 0x8e, 0x18, 0xfd, 0x88, 0xb0, 0xec, 0x6c, \
    0x3b, 0x95, 0xae, 0x9a, 0xf1, 0xe5, 0x3e, 0xf9
#endif
static const uint8_t PAYLOAD_SHA256[32] = {
    DF_LOCK_PAYLOAD_SHA256_BYTES
};
static PIO const selector_pio = pio0;
static uint select_offset, data_dma;
#ifdef DF_LOCK_WIRE_CAPTURE
enum { CAPTURE_SM = 0u, CAPTURE_WORDS = 32u,
       CAPTURE_AFTER_REPLY = 0u, CAPTURE_SOURCE_BLOCK = 1u };
static PIO const capture_pio = pio2;
static uint capture_offset, capture_dma;
static uint32_t captured_pairs[CAPTURE_WORDS];
static bool capture_armed;

static uint16_t captured_miso_word(uint32_t pairs) {
    uint16_t result = 0u;
    for (uint bit = 0; bit < 16u; ++bit)
        result = (uint16_t)((result << 1) | ((pairs >> (31u - bit * 2u)) & 1u));
    return result;
}

static void arm_wire_capture(void) {
    pio_sm_set_enabled(capture_pio, CAPTURE_SM, false);
    pio_sm_clear_fifos(capture_pio, CAPTURE_SM);
    pio_sm_restart(capture_pio, CAPTURE_SM);
    pio_sm_exec(capture_pio, CAPTURE_SM, pio_encode_jmp(capture_offset));
    pio_interrupt_clear(capture_pio, 1);
    capture_pio->fdebug = 1u << (PIO_FDEBUG_RXSTALL_LSB + CAPTURE_SM);
    dma_channel_set_write_addr(capture_dma, captured_pairs, false);
    dma_channel_set_trans_count(capture_dma, CAPTURE_WORDS, false);
    dma_channel_start(capture_dma);
    capture_armed = true;
}
#endif
static _Atomic uint32_t mode, fault, completed, max_rearm_cycles,
                        fault_diag, first_diag, last_diag;
static bool payload_valid;
static bool payload_hash_ready;
static uint8_t payload_actual_sha256[32];

static const volatile uint8_t *payload_block(uint32_t block) {
    return (const volatile uint8_t *)(uintptr_t)
        (XIP_NOCACHE_NOALLOC_BASE + DF_LOCK_PICO_FLASH_OFFSET + block * 64u);
}

static bool verify_payload(void) {
    pico_sha256_state_t state;
    sha256_result_t result;
    if (pico_sha256_start_blocking(&state, SHA256_BIG_ENDIAN, true) != PICO_OK)
        return false;
    pico_sha256_update_blocking(&state,
        (const uint8_t *)(uintptr_t)(XIP_NOCACHE_NOALLOC_BASE + DF_LOCK_PICO_FLASH_OFFSET),
        PAYLOAD_BYTES);
    pico_sha256_finish(&state, &result);
    memcpy(payload_actual_sha256, result.bytes, sizeof(payload_actual_sha256));
    payload_hash_ready = true;
    return memcmp(result.bytes, PAYLOAD_SHA256, sizeof(PAYLOAD_SHA256)) == 0;
}

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
    uint32_t block = index % DF_LOCK_BLOCK_COUNT;
    pio_sm_set_enabled(selector_pio, SELECT_SM, false);
    pio_sm_clear_fifos(selector_pio, SELECT_SM);
    pio_sm_restart(selector_pio, SELECT_SM);
    pio_sm_exec(selector_pio, SELECT_SM, pio_encode_jmp(select_offset));
    pio_interrupt_clear(selector_pio, 0);
    pio_interrupt_clear(selector_pio, 1);
    selector_pio->txf[SELECT_SM] =
        (0x03000000u | (DF_LOCK_ROM_START + block * 0x40u)) >> SELECT_PREFIX_SHIFT;
    pio_sm_set_enabled(selector_pio, SELECT_SM, true);
    selector_pio->txf[SELECT_SM] = df_lock_first_words[block];
    dma_channel_set_read_addr(data_dma, (const void *)(payload_block(block) + 4u), false);
    dma_channel_set_trans_count(data_dma, 15u, false);
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
        if (index >= TOTAL_REPLIES) {
            fail_closed(DMA_FAULT);
            continue;
        }
        if (index == 0u)
            atomic_store_explicit(&first_diag, selector_diag(), memory_order_relaxed);
        atomic_store_explicit(&completed, index + 1u, memory_order_release);
        if (index + 1u == TOTAL_REPLIES) {
            atomic_store_explicit(&last_diag, selector_diag(), memory_order_relaxed);
            continue;
        }
        if (!gpio_get(BC250_CS)) {
            fail_closed(LATE_FAULT);
            continue;
        }
        prepare_reply(index + 1u);
#ifdef DF_LOCK_WIRE_CAPTURE
        if (index == CAPTURE_AFTER_REPLY && capture_armed)
            pio_sm_set_enabled(capture_pio, CAPTURE_SM, true);
#endif
        uint32_t elapsed = cycles_now() - begin;
        uint32_t max = atomic_load_explicit(&max_rearm_cycles, memory_order_relaxed);
        if (elapsed > max)
            atomic_store_explicit(&max_rearm_cycles, elapsed, memory_order_relaxed);
        if (!gpio_get(BC250_CS)) fail_closed(LATE_FAULT);
    }
}

static void status(void) {
    uint32_t known_flash_word = *(const volatile uint32_t *)(uintptr_t)
        (XIP_BASE + 0x7f000u);
    uint32_t payload_main_word = *(const volatile uint32_t *)(uintptr_t)
        (XIP_BASE + DF_LOCK_PICO_FLASH_OFFSET);
    uint32_t payload_nocache_word = *(const volatile uint32_t *)(uintptr_t)
        (XIP_NOCACHE_NOALLOC_BASE + DF_LOCK_PICO_FLASH_OFFSET);
    printf("BC250-PICO2-DF-LOCK-STREAM profile=%s clock_hz=%" PRIu32
           " mode=%" PRIu32 " fault=%" PRIu32 " payload_ok=%u host_cs=%u"
           " relay_oe=%u miso_oe=%u completed=%" PRIu32
           " total=%u prefix_shift=%u max_rearm_cycles=%" PRIu32
           " dma_remaining=%" PRIu32 " fifo=%u"
           " selector=%04" PRIx32 " first_diag=%04" PRIx32
           " last_diag=%04" PRIx32 " fault_diag=%04" PRIx32
           " bios_write=UNAVAILABLE pico_write=UNAVAILABLE"
           " flash_probe=%08" PRIx32 "/%08" PRIx32 "/%08" PRIx32
           " payload_sha256=",
           PROFILE_NAME, clock_get_hz(clk_sys),
           atomic_load_explicit(&mode, memory_order_relaxed),
           atomic_load_explicit(&fault, memory_order_relaxed),
           payload_valid ? 1u : 0u,
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((selector_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((selector_pio->dbg_padoe >> BC250_MISO) & 1u),
           atomic_load_explicit(&completed, memory_order_relaxed),
           TOTAL_REPLIES, SELECT_PREFIX_SHIFT,
           atomic_load_explicit(&max_rearm_cycles, memory_order_relaxed),
           (uint32_t)dma_channel_hw_addr(data_dma)->transfer_count,
           pio_sm_get_tx_fifo_level(selector_pio, SELECT_SM),
           selector_diag(),
           atomic_load_explicit(&first_diag, memory_order_relaxed),
           atomic_load_explicit(&last_diag, memory_order_relaxed),
           atomic_load_explicit(&fault_diag, memory_order_relaxed),
           known_flash_word, payload_main_word, payload_nocache_word);
    if (payload_hash_ready) {
        for (uint i = 0; i < sizeof(payload_actual_sha256); ++i)
            printf("%02x", payload_actual_sha256[i]);
    } else {
        printf("UNAVAILABLE");
    }
#ifdef DF_LOCK_WIRE_CAPTURE
    uint32_t remaining = dma_channel_hw_addr(capture_dma)->transfer_count;
    bool done = capture_armed && pio_interrupt_get(capture_pio, 1) && !remaining;
    uint32_t first_bad = CAPTURE_WORDS, expected = 0u, received = 0u;
    if (done) {
        const volatile uint8_t *reference = payload_block(CAPTURE_SOURCE_BLOCK);
        for (uint i = 0; i < CAPTURE_WORDS; ++i) {
            uint32_t want = ((uint32_t)reference[i * 2u] << 8) |
                            reference[i * 2u + 1u];
            uint32_t got = captured_miso_word(captured_pairs[i]);
            if (want != got) {
                first_bad = i;
                expected = want;
                received = got;
                break;
            }
        }
    }
    printf(" wire_capture=%u wire_target_block=%u wire_done=%u"
           " wire_remaining=%" PRIu32 " wire_pc=%u"
           " wire_rxstall=%u wire_first_bad_word=%" PRIu32
           " wire_expected=%04" PRIx32 " wire_received=%04" PRIx32,
           capture_armed ? 1u : 0u, CAPTURE_SOURCE_BLOCK,
           done ? 1u : 0u, remaining,
           pio_sm_get_pc(capture_pio, CAPTURE_SM),
           (unsigned)((capture_pio->fdebug >>
                       (PIO_FDEBUG_RXSTALL_LSB + CAPTURE_SM)) & 1u),
           first_bad, expected, received);
#endif
    printf("\n");
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-pass") || !strcmp(line, "arm-active")) {
        bool active = !strcmp(line, "arm-active");
        if (active && !payload_valid) {
            printf("ERROR verified Pico QSPI payload absent; ACTIVE refused\n");
        } else if (atomic_load_explicit(&mode, memory_order_acquire) != UNARMED ||
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
                ((0x03000000u | DF_LOCK_ROM_START) >> SELECT_PREFIX_SHIFT) : UINT32_MAX;
            pio_sm_set_enabled(selector_pio, SELECT_SM, true);
            sleep_us(10);
            if (!pio_sm_is_tx_fifo_empty(selector_pio, SELECT_SM) ||
                pio_sm_get_pc(selector_pio, SELECT_SM) == select_offset) {
                fail_closed(DMA_FAULT);
                printf("ERROR target prefix was not loaded\n");
            } else {
                if (active) {
                    selector_pio->txf[SELECT_SM] = df_lock_first_words[0];
                    dma_channel_set_read_addr(data_dma,
                        (const void *)(payload_block(0u) + 4u), false);
                    dma_channel_set_trans_count(data_dma, 15u, false);
                    dma_channel_start(data_dma);
                    sleep_us(10);
                }
                selector_pio->fdebug = (1u << (PIO_FDEBUG_TXSTALL_LSB + SELECT_SM)) |
                                       (1u << (PIO_FDEBUG_TXOVER_LSB + SELECT_SM));
#ifdef DF_LOCK_WIRE_CAPTURE
                if (active) arm_wire_capture();
#endif
                gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
                if (active) gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
                watchdog_disable();
                atomic_store_explicit(&mode, active ? ACTIVE : PASS_ONLY, memory_order_release);
                printf("ARMED DF-LOCK-%s MISO=%s profile=%s count=%u\n",
                       active ? "ACTIVE" : "PASS",
                       active ? "PIO-GUARDED" : "DISABLED", PROFILE_NAME,
                       TOTAL_REPLIES);
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
    /* picotool executes no_flash images from SRAM without setting up QMI XIP.
     * The ROM-backed Pico flash stays untouched; this only enables reads. */
    flash_start_xip();
    rom_flash_select_xip_read_mode(BOOTROM_XIP_MODE_0BH_SERIAL, 6u);
    payload_valid = verify_payload();

    pio_sm_claim(selector_pio, SELECT_SM);
    select_offset = pio_add_program(selector_pio, &SELECT_PROGRAM);
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
#ifdef DF_LOCK_EARLY_RELEASE
    pio_sm_config c = burst_match_early_od_program_get_default_config(select_offset);
#else
    pio_sm_config c = burst_match_late_od_program_get_default_config(select_offset);
#endif
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
    channel_config_set_bswap(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(selector_pio, SELECT_SM, true));
    dma_channel_configure(data_dma, &dc, &selector_pio->txf[SELECT_SM],
                          (const void *)(payload_block(0u) + 4u),
                          15u, false);
#ifdef DF_LOCK_WIRE_CAPTURE
    pio_sm_claim(capture_pio, CAPTURE_SM);
    capture_offset = pio_add_program(capture_pio, &burst_wire_capture_program);
    c = burst_wire_capture_program_get_default_config(capture_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_jmp_pin(&c, BC250_MOSI);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(capture_pio, CAPTURE_SM, capture_offset, &c);
    capture_dma = dma_claim_unused_channel(true);
    dc = dma_channel_get_default_config(capture_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(capture_pio, CAPTURE_SM, false));
    dma_channel_configure(capture_dma, &dc, captured_pairs,
                          &capture_pio->rxf[CAPTURE_SM], CAPTURE_WORDS, false);
#endif
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
