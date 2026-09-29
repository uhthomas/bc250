/* RAM-only Pico-only repeated-burst timing bench. The real BC250 flash stays
 * on PIO0's GP7 pass-through CS# relay. All local traffic uses unwired
 * GP8..GP12, and the Pico onboard flash is read through uncached XIP only.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "pico/multicore.h"
#include "pico/sha256.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/flash.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "burst_xip_bench.pio.h"
#include "burst_xip_capture.pio.h"
#include "burst_host_loop.pio.h"
#include "local_gap_counter.pio.h"
#include "cs_open_drain.pio.h"
#include "pins.h"

enum {
    FLASH_CS = 7u, MISO = 8u, HOST_CS = 9u, HOST_SCK = 10u,
    HOST_MOSI = 11u, FAKE_FLASH_CS = 12u,
    RELAY_SM = 0u, GAP_SM = 1u, REPLY_SM = 0u,
    HOST_SM = 0u, CAPTURE_SM = 1u,
    SOURCE_OFFSET = 0x200000u, SOURCE_BYTES = 65536u,
    WORDS_PER_REPLY = 16u,
    WORDS_PER_FRAME = 19u, MAX_FRAMES = 1024u,
    FIRST_COMMAND = 0x03aede80u, SYS_HZ = 340000000u
};
/* SHA256 of the first 64 KiB of the independently generated candidate
 * payload. Without this oracle, both the source and capture can agree on
 * zeros when a no_flash image has not initialized QMI/XIP. */
static const uint8_t expected_source_sha256[32] = {
    0xf1, 0x47, 0xef, 0xaa, 0x35, 0xb7, 0x0b, 0x5b,
    0xf6, 0xae, 0x5d, 0x7d, 0x48, 0x97, 0x2e, 0x35,
    0x61, 0xc4, 0xae, 0x7f, 0xd7, 0x03, 0xc4, 0x82,
    0x93, 0x0e, 0x2e, 0x83, 0x49, 0xe8, 0xc5, 0x10,
};
static PIO const relay_pio = pio0;
static PIO const reply_pio = pio1;
static PIO const local_pio = pio2;
static uint relay_offset, gap_offset, reply_offset, host_offset, capture_offset;
static uint reply_dma, host_dma, capture_dma, gap_dma;
static uint32_t host_words[WORDS_PER_FRAME * MAX_FRAMES];
static uint32_t received[WORDS_PER_REPLY * MAX_FRAMES];
static uint32_t high_gaps[MAX_FRAMES];
static uint32_t expected_words[WORDS_PER_REPLY * MAX_FRAMES];
static _Atomic uint32_t run_frames, worker_done, worker_count, worker_late,
                        worker_fifo_fault, worker_dma_fault, worker_max_cycles;
static bool relay_armed;
static bool source_valid;
static uint8_t actual_source_sha256[32];

static bool verify_source(void) {
    pico_sha256_state_t state;
    sha256_result_t result;
    if (pico_sha256_start_blocking(&state, SHA256_BIG_ENDIAN, true) != PICO_OK)
        return false;
    pico_sha256_update_blocking(&state,
        (const uint8_t *)(uintptr_t)(XIP_NOCACHE_NOALLOC_BASE + SOURCE_OFFSET),
        SOURCE_BYTES);
    pico_sha256_finish(&state, &result);
    memcpy(actual_source_sha256, result.bytes, sizeof(actual_source_sha256));
    return memcmp(actual_source_sha256, expected_source_sha256,
                  sizeof(expected_source_sha256)) == 0;
}

static uint32_t __not_in_flash_func(cycles_now)(void) {
    uint32_t cycles;
    __asm__ volatile("rdcycle %0" : "=r"(cycles));
    return cycles;
}

static inline const volatile uint8_t *source(uint32_t frame) {
    return (const volatile uint8_t *)(uintptr_t)
        (XIP_NOCACHE_NOALLOC_BASE + SOURCE_OFFSET + frame * 64u);
}

static uint32_t word_at(const volatile uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | p[3];
}

static void __not_in_flash_func(prepare_reply)(uint32_t frame) {
    pio_sm_set_enabled(reply_pio, REPLY_SM, false);
    pio_sm_clear_fifos(reply_pio, REPLY_SM);
    pio_sm_restart(reply_pio, REPLY_SM);
    pio_sm_exec(reply_pio, REPLY_SM, pio_encode_jmp(reply_offset));
    pio_interrupt_clear(reply_pio, 0);
    pio_interrupt_clear(reply_pio, 1);
    reply_pio->txf[REPLY_SM] = (FIRST_COMMAND + frame * 0x40u) >> 1;
    pio_sm_set_enabled(reply_pio, REPLY_SM, true);
    reply_pio->txf[REPLY_SM] = expected_words[frame * WORDS_PER_REPLY];
    dma_channel_set_read_addr(reply_dma, (const void *)(source(frame) + 4), false);
    dma_channel_set_trans_count(reply_dma, WORDS_PER_REPLY - 1u, false);
    dma_channel_start(reply_dma);
}

static void __not_in_flash_func(rearm_worker)(void) {
    /* Hazard3 resets mcountinhibit.CY=1, so rdcycle would otherwise read 0. */
    uint32_t inhibit;
    __asm__ volatile("csrr %0, mcountinhibit" : "=r"(inhibit));
    inhibit &= ~1u;
    __asm__ volatile("csrw mcountinhibit, %0" : : "r"(inhibit));
    for (;;) {
        uint32_t count = atomic_load_explicit(&run_frames, memory_order_acquire);
        if (!count) continue;
        for (uint32_t i = 1; i < count; ++i) {
            while (!pio_interrupt_get(reply_pio, 1)) tight_loop_contents();
            uint32_t start = cycles_now();
            if (!gpio_get(HOST_CS))
                atomic_fetch_add_explicit(&worker_late, 1u, memory_order_relaxed);
            if (dma_channel_is_busy(reply_dma) ||
                dma_channel_hw_addr(reply_dma)->transfer_count)
                atomic_fetch_add_explicit(&worker_dma_fault, 1u, memory_order_relaxed);
            if (pio_sm_get_tx_fifo_level(reply_pio, REPLY_SM))
                atomic_fetch_add_explicit(&worker_fifo_fault, 1u, memory_order_relaxed);
            prepare_reply(i);
            uint32_t elapsed = cycles_now() - start;
            uint32_t max = atomic_load_explicit(&worker_max_cycles, memory_order_relaxed);
            if (elapsed > max)
                atomic_store_explicit(&worker_max_cycles, elapsed, memory_order_relaxed);
            if (!gpio_get(HOST_CS))
                atomic_fetch_add_explicit(&worker_late, 1u, memory_order_relaxed);
            atomic_store_explicit(&worker_count, i, memory_order_release);
        }
        atomic_store_explicit(&worker_done, 1u, memory_order_release);
        atomic_store_explicit(&run_frames, 0u, memory_order_release);
    }
}

static void status(void) {
    printf("BC250-PICO2-REARM-BENCH relay=%u host_cs=%u relay_oe=%u"
           " real_miso_oe=%u clock_hz=%" PRIu32
           " source_valid=%u worker=%" PRIu32 " late=%" PRIu32
           " max_cycles=%" PRIu32 " bios_write=UNAVAILABLE"
           " pico_write=UNAVAILABLE source_sha256=",
           relay_armed ? 1u : 0u, gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((relay_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((reply_pio->dbg_padoe >> BC250_MISO) & 1u),
           clock_get_hz(clk_sys),
           source_valid ? 1u : 0u,
           atomic_load_explicit(&worker_count, memory_order_relaxed),
           atomic_load_explicit(&worker_late, memory_order_relaxed),
           atomic_load_explicit(&worker_max_cycles, memory_order_relaxed));
    for (uint i = 0; i < sizeof(actual_source_sha256); ++i)
        printf("%02x", actual_source_sha256[i]);
    printf("\n");
}

static void run_bench(uint32_t frames, uint32_t gap_loops) {
    if (!source_valid || !relay_armed || !gpio_get(BC250_CS) ||
        atomic_load_explicit(&run_frames, memory_order_acquire)) {
        printf("ERROR source invalid, real-board relay unavailable, or previous run active\n");
        return;
    }
    for (uint32_t i = 0; i < frames; ++i) {
        uint32_t *dst = host_words + i * WORDS_PER_FRAME;
        dst[0] = gap_loops;
        dst[1] = 543u; /* 32 command bits + 512 reply clocks - 1 */
        dst[2] = FIRST_COMMAND + i * 0x40u;
        memset(dst + 3, 0, WORDS_PER_REPLY * sizeof(uint32_t));
        const volatile uint8_t *data = source(i);
        for (uint32_t j = 0; j < WORDS_PER_REPLY; ++j)
            expected_words[i * WORDS_PER_REPLY + j] = word_at(data + j * 4u);
    }
    memset(received, 0xa5, frames * WORDS_PER_REPLY * sizeof(uint32_t));
    memset(high_gaps, 0xa5, frames * sizeof(uint32_t));
    atomic_store_explicit(&worker_done, 0u, memory_order_relaxed);
    atomic_store_explicit(&worker_count, 0u, memory_order_relaxed);
    atomic_store_explicit(&worker_late, 0u, memory_order_relaxed);
    atomic_store_explicit(&worker_fifo_fault, 0u, memory_order_relaxed);
    atomic_store_explicit(&worker_dma_fault, 0u, memory_order_relaxed);
    atomic_store_explicit(&worker_max_cycles, 0u, memory_order_relaxed);

    pio_sm_set_enabled(local_pio, HOST_SM, false);
    pio_sm_clear_fifos(local_pio, HOST_SM);
    pio_sm_restart(local_pio, HOST_SM);
    pio_sm_exec(local_pio, HOST_SM, pio_encode_jmp(host_offset));
    pio_sm_set_pins_with_mask(local_pio, HOST_SM, 1u << HOST_CS,
                              (1u << HOST_CS) | (1u << HOST_SCK));
    pio_sm_set_enabled(local_pio, CAPTURE_SM, false);
    pio_sm_clear_fifos(local_pio, CAPTURE_SM);
    pio_sm_restart(local_pio, CAPTURE_SM);
    pio_sm_exec(local_pio, CAPTURE_SM, pio_encode_jmp(capture_offset));
    pio_interrupt_clear(local_pio, 1);
    dma_channel_abort(host_dma);
    dma_channel_abort(capture_dma);
    dma_channel_set_read_addr(host_dma, host_words, false);
    dma_channel_set_trans_count(host_dma, frames * WORDS_PER_FRAME, false);
    dma_channel_set_write_addr(capture_dma, received, false);
    dma_channel_set_trans_count(capture_dma, frames * WORDS_PER_REPLY, false);
    pio_sm_set_enabled(relay_pio, GAP_SM, false);
    pio_sm_clear_fifos(relay_pio, GAP_SM);
    pio_sm_restart(relay_pio, GAP_SM);
    pio_sm_exec(relay_pio, GAP_SM, pio_encode_jmp(gap_offset));
    dma_channel_abort(gap_dma);
    dma_channel_set_write_addr(gap_dma, high_gaps, false);
    dma_channel_set_trans_count(gap_dma, frames, false);
    dma_channel_start(host_dma);
    dma_channel_start(capture_dma);
    dma_channel_start(gap_dma);
    pio_sm_set_enabled(local_pio, CAPTURE_SM, true);
    pio_sm_set_enabled(relay_pio, GAP_SM, true);

    prepare_reply(0u);
    reply_pio->fdebug = (1u << (PIO_FDEBUG_TXSTALL_LSB + REPLY_SM)) |
                        (1u << (PIO_FDEBUG_TXOVER_LSB + REPLY_SM));
    atomic_store_explicit(&run_frames, frames, memory_order_release);
    pio_sm_set_enabled(local_pio, HOST_SM, true);

    absolute_time_t deadline = make_timeout_time_ms(1000u);
    while ((!atomic_load_explicit(&worker_done, memory_order_acquire) ||
            dma_channel_hw_addr(capture_dma)->transfer_count) &&
           !time_reached(deadline)) tight_loop_contents();
    sleep_us(10);
    uint32_t capture_remaining = dma_channel_hw_addr(capture_dma)->transfer_count;
    uint32_t host_remaining = dma_channel_hw_addr(host_dma)->transfer_count;
    uint32_t data_remaining = dma_channel_hw_addr(reply_dma)->transfer_count;
    uint32_t gap_remaining = dma_channel_hw_addr(gap_dma)->transfer_count;
    uint32_t min_gap = UINT32_MAX, max_gap = 0u;
    for (uint32_t i = frames > 1u ? 1u : 0u;
         i < frames - gap_remaining; ++i) {
        uint32_t iterations = UINT32_MAX - high_gaps[i];
        if (iterations < min_gap) min_gap = iterations;
        if (iterations > max_gap) max_gap = iterations;
    }
    uint32_t min_gap_ns = (uint32_t)(((uint64_t)min_gap * 2000000000ull) / SYS_HZ);
    uint32_t max_gap_ns = (uint32_t)(((uint64_t)max_gap * 2000000000ull) / SYS_HZ);
    uint32_t first_bad = frames * WORDS_PER_REPLY;
    uint32_t expected = 0u, actual = 0u;
    for (uint32_t i = 0; i < frames * WORDS_PER_REPLY; ++i) {
        uint32_t want = expected_words[i];
        if (received[i] != want && first_bad == frames * WORDS_PER_REPLY) {
            first_bad = i;
            expected = want;
            actual = received[i];
        }
    }
    uint32_t late = atomic_load_explicit(&worker_late, memory_order_relaxed);
    uint32_t fifo_fault = atomic_load_explicit(&worker_fifo_fault, memory_order_relaxed);
    uint32_t dma_fault = atomic_load_explicit(&worker_dma_fault, memory_order_relaxed);
    uint32_t prepared = atomic_load_explicit(&worker_count, memory_order_relaxed);
    bool pass = !capture_remaining && !host_remaining && !data_remaining &&
                !gap_remaining &&
                first_bad == frames * WORDS_PER_REPLY &&
                !late && !fifo_fault && !dma_fault &&
                prepared == frames - 1u &&
                atomic_load_explicit(&worker_done, memory_order_acquire) &&
                pio_interrupt_get(reply_pio, 1) &&
                !pio_interrupt_get(reply_pio, 0) &&
                !((reply_pio->fdebug >> (PIO_FDEBUG_TXSTALL_LSB + REPLY_SM)) & 1u);
    printf("REARM-RESULT pass=%u frames=%" PRIu32
           " spi_hz=34000000 high_gap_ns_est=%" PRIu32
           " steady_gap_min_ns=%" PRIu32 " steady_gap_max_ns=%" PRIu32
           " prepared=%" PRIu32 " max_rearm_cycles=%" PRIu32
           " late=%" PRIu32 " fifo_fault=%" PRIu32
           " dma_fault=%" PRIu32 " host_remaining=%" PRIu32
           " capture_remaining=%" PRIu32 " data_remaining=%" PRIu32
           " gap_remaining=%" PRIu32
           " first_bad=%" PRIu32 " expected=%08" PRIx32
           " received=%08" PRIx32
           " selector_done=%u capture_done=%u board_miso=OFF"
           " source=sequential_uncached_xip"
           " pico_write=UNAVAILABLE bios_write=UNAVAILABLE\n",
           pass ? 1u : 0u, frames,
           (uint32_t)(((uint64_t)(gap_loops + 7u) * 1000000000ull) / SYS_HZ),
           min_gap_ns, max_gap_ns,
           prepared,
           atomic_load_explicit(&worker_max_cycles, memory_order_relaxed),
           late, fifo_fault, dma_fault,
           host_remaining, capture_remaining, data_remaining, gap_remaining,
           first_bad, expected, actual,
           pio_interrupt_get(reply_pio, 1) ? 1u : 0u,
           pio_interrupt_get(local_pio, 1) ? 1u : 0u);
}

int main(void) {
    gpio_init(FLASH_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_init(BC250_CS);
    gpio_disable_pulls(BC250_CS);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_init(BC250_MISO);
    gpio_disable_pulls(BC250_MISO);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    vreg_set_voltage(VREG_VOLTAGE_1_30);
    sleep_ms(10);
    bool clock_ok = set_sys_clock_khz(SYS_HZ / 1000u, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != SYS_HZ) {
        for (;;) { printf("ERROR clock setup; relay off\n"); sleep_ms(1000); }
    }
    flash_start_xip();
    rom_flash_select_xip_read_mode(BOOTROM_XIP_MODE_0BH_SERIAL, 6u);
    source_valid = verify_source();

    pio_sm_claim(relay_pio, RELAY_SM);
    relay_offset = pio_add_program(relay_pio, &cs_open_drain_program);
    pio_gpio_init(relay_pio, BC250_CS);
    pio_gpio_init(relay_pio, FLASH_CS);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_config c = cs_open_drain_program_get_default_config(relay_offset);
    sm_config_set_set_pins(&c, FLASH_CS, 1);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(relay_pio, RELAY_SM, relay_offset, &c);
    pio_sm_set_pins_with_mask(relay_pio, RELAY_SM, 0, 1u << FLASH_CS);
    pio_sm_set_consecutive_pindirs(relay_pio, RELAY_SM, FLASH_CS, 1, false);
    pio_sm_set_enabled(relay_pio, RELAY_SM, true);
    if (gpio_get(BC250_CS)) {
        sleep_us(10);
        gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
        relay_armed = true;
    }

    pio_sm_claim(relay_pio, GAP_SM);
    gap_offset = pio_add_program(relay_pio, &local_gap_counter_program);
    c = local_gap_counter_program_get_default_config(gap_offset);
    sm_config_set_jmp_pin(&c, HOST_CS);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(relay_pio, GAP_SM, gap_offset, &c);
    gap_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(gap_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(relay_pio, GAP_SM, false));
    dma_channel_configure(gap_dma, &dc, high_gaps,
                          &relay_pio->rxf[GAP_SM], 1u, false);

    gpio_init(MISO);
    gpio_disable_pulls(MISO);
    gpio_set_input_enabled(MISO, true);
    gpio_set_oeover(MISO, GPIO_OVERRIDE_LOW);
    gpio_init(FAKE_FLASH_CS);
    gpio_disable_pulls(FAKE_FLASH_CS);
    gpio_set_outover(FAKE_FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(FAKE_FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_claim(reply_pio, REPLY_SM);
    reply_offset = pio_add_program(reply_pio, &burst_xip_bench_program);
    pio_gpio_init(reply_pio, MISO);
    pio_gpio_init(reply_pio, FAKE_FLASH_CS);
    gpio_set_input_enabled(MISO, true);
    gpio_set_outover(FAKE_FLASH_CS, GPIO_OVERRIDE_LOW);
    c = burst_xip_bench_program_get_default_config(reply_offset);
    sm_config_set_in_pins(&c, HOST_MOSI);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_out_pins(&c, MISO, 1);
    sm_config_set_out_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_set_pins(&c, FAKE_FLASH_CS, 1);
    sm_config_set_sideset_pins(&c, MISO);
    sm_config_set_jmp_pin(&c, HOST_MOSI);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(reply_pio, REPLY_SM, reply_offset, &c);
    pio_sm_set_pins_with_mask(reply_pio, REPLY_SM, 0, 1u << FAKE_FLASH_CS);
    pio_sm_set_consecutive_pindirs(reply_pio, REPLY_SM, MISO, 1, false);
    pio_sm_set_consecutive_pindirs(reply_pio, REPLY_SM, FAKE_FLASH_CS, 1, false);
    gpio_set_oeover(MISO, GPIO_OVERRIDE_NORMAL);
    gpio_set_oeover(FAKE_FLASH_CS, GPIO_OVERRIDE_NORMAL);
    reply_dma = dma_claim_unused_channel(true);
    dc = dma_channel_get_default_config(reply_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_bswap(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(reply_pio, REPLY_SM, true));
    dma_channel_configure(reply_dma, &dc, &reply_pio->txf[REPLY_SM],
                          (const void *)(source(0u) + 4), WORDS_PER_REPLY - 1u, false);

    for (uint pin = HOST_CS; pin <= HOST_MOSI; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_input_enabled(pin, true);
    }
    pio_sm_claim(local_pio, HOST_SM);
    host_offset = pio_add_program(local_pio, &burst_host_loop_program);
    for (uint pin = HOST_CS; pin <= HOST_MOSI; ++pin) {
        pio_gpio_init(local_pio, pin);
        gpio_set_input_enabled(pin, true);
    }
    c = burst_host_loop_program_get_default_config(host_offset);
    sm_config_set_out_pins(&c, HOST_MOSI, 1);
    sm_config_set_out_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_set_pins(&c, HOST_CS, 1);
    sm_config_set_sideset_pins(&c, HOST_SCK);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(local_pio, HOST_SM, host_offset, &c);
    pio_sm_set_pins_with_mask(local_pio, HOST_SM, 1u << HOST_CS,
                              (1u << HOST_CS) | (1u << HOST_SCK));
    pio_sm_set_consecutive_pindirs(local_pio, HOST_SM, HOST_CS, 3, true);
    host_dma = dma_claim_unused_channel(true);
    dc = dma_channel_get_default_config(host_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_dreq(&dc, pio_get_dreq(local_pio, HOST_SM, true));
    dma_channel_configure(host_dma, &dc, &local_pio->txf[HOST_SM],
                          host_words, WORDS_PER_FRAME, false);

    pio_sm_claim(local_pio, CAPTURE_SM);
    capture_offset = pio_add_program(local_pio, &burst_xip_capture_program);
    c = burst_xip_capture_program_get_default_config(capture_offset);
    sm_config_set_in_pins(&c, MISO);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(local_pio, CAPTURE_SM, capture_offset, &c);
    pio_sm_set_consecutive_pindirs(local_pio, CAPTURE_SM, MISO, 1, false);
    capture_dma = dma_claim_unused_channel(true);
    dc = dma_channel_get_default_config(capture_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(local_pio, CAPTURE_SM, false));
    dma_channel_configure(capture_dma, &dc, received,
                          &local_pio->rxf[CAPTURE_SM], WORDS_PER_REPLY, false);

    multicore_launch_core1(rearm_worker);
    printf("BC250-PICO2-REARM-BENCH ready relay=%u source_valid=%u"
           " source_offset=%06x pins=GP8..12_only"
           " pico_write=UNAVAILABLE bios_write=UNAVAILABLE\n",
           relay_armed ? 1u : 0u, source_valid ? 1u : 0u,
           SOURCE_OFFSET);
    char line[80];
    unsigned used = 0;
    for (;;) {
        int ch = getchar_timeout_us(0);
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[used] = 0;
            unsigned frames, gap;
            char extra;
            if (!strcmp(line, "status")) status();
            else if (sscanf(line, "bench %u %u %c", &frames, &gap, &extra) == 2 &&
                     frames >= 1u && frames <= MAX_FRAMES &&
                     gap >= 200u && gap <= 2000u)
                run_bench(frames, gap);
            else printf("ERROR commands: status; bench FRAMES GAP_LOOPS"
                        " (1..1024; 200..2000)\n");
            used = 0;
            stdio_flush();
        } else if (ch >= 0 && used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        }
        tight_loop_contents();
    }
}
