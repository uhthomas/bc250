/* RAM-only, input-only CS# gap timing capture over a selected boot region.
 * PIO0 continues the original-flash GP7 CS# relay. PIO1 sees commands, and
 * PIO2 + DMA sample host-CS# high durations. No MISO/Pico-flash/BIOS writes.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "cs_open_drain.pio.h"
#include "address_hunt.pio.h"
#include "cs_gap_counter.pio.h"
#include "pins.h"

#ifdef BC250_SHORT_SCAN_GAP
enum { FLASH_CS = 7u, RELAY_SM = 0u, WATCH_SM = 0u, GAP_SM = 0u,
       GAP_CAPACITY = 256u, SYS_HZ = 340000000u,
       TRIGGER_OCCURRENCE = 1u, REGION_BEGIN = 0x03ae0004u,
       REGION_END = 0x03ae00bcu };
#define REGION_LABEL "SHORT-SCAN-GAPS"
#else
enum { FLASH_CS = 7u, RELAY_SM = 0u, WATCH_SM = 0u, GAP_SM = 0u,
       GAP_CAPACITY = 22000u, SYS_HZ = 340000000u,
       TRIGGER_OCCURRENCE = 2u, REGION_BEGIN = 0x03ae0140u,
       REGION_END = 0x03c31c00u };
#define REGION_LABEL "UEFI-GAPS"
#endif
static PIO const relay_pio = pio0;
static PIO const watch_pio = pio1;
static PIO const gap_pio = pio2;
static uint relay_offset, watch_offset, gap_offset, gap_dma;
static uint32_t gaps[GAP_CAPACITY], ordered[GAP_CAPACITY];
static _Atomic uint32_t seen, trigger_count, capture_started, begin_index,
                        end_index, first_region, last_region;
static bool relay_armed;

static uint32_t __not_in_flash_func(gap_progress)(void) {
    if (!atomic_load_explicit(&capture_started, memory_order_acquire)) return 0u;
    return GAP_CAPACITY - dma_channel_hw_addr(gap_dma)->transfer_count;
}

static void __not_in_flash_func(watch_worker)(void) {
    for (;;) {
        if (pio_sm_is_rx_fifo_empty(watch_pio, WATCH_SM)) continue;
        uint32_t command = watch_pio->rxf[WATCH_SM];
        atomic_fetch_add_explicit(&seen, 1u, memory_order_relaxed);
        /* The first 0xae0000 starts the 4-byte scan. The second starts the
         * UEFI prelude, leaving room for the 21,612 long reads. */
        if (command == 0x03ae0000u &&
            atomic_fetch_add_explicit(&trigger_count, 1u, memory_order_relaxed)
                == TRIGGER_OCCURRENCE - 1u) {
            atomic_store_explicit(&capture_started, 1u, memory_order_release);
            dma_channel_set_trans_count(gap_dma, GAP_CAPACITY, false);
            dma_channel_start(gap_dma);
            pio_sm_set_enabled(gap_pio, GAP_SM, true);
        }
        if (atomic_load_explicit(&capture_started, memory_order_relaxed) &&
            command == REGION_BEGIN &&
            !atomic_load_explicit(&first_region, memory_order_relaxed)) {
            atomic_store_explicit(&begin_index, gap_progress(), memory_order_relaxed);
            atomic_store_explicit(&first_region, command, memory_order_release);
        }
        if (atomic_load_explicit(&first_region, memory_order_acquire) &&
            command == REGION_END &&
            !atomic_load_explicit(&last_region, memory_order_relaxed)) {
            atomic_store_explicit(&end_index, gap_progress(), memory_order_relaxed);
            atomic_store_explicit(&last_region, command, memory_order_release);
        }
    }
}

static int cmp_uint32(const void *a, const void *b) {
    uint32_t lhs = *(const uint32_t *)a, rhs = *(const uint32_t *)b;
    return (lhs > rhs) - (lhs < rhs);
}

static uint32_t to_ns(uint32_t iterations) {
    return (uint32_t)(((uint64_t)iterations * 2000000000ull + SYS_HZ / 2u) /
                      SYS_HZ);
}

static void status(void) {
    uint32_t done = gap_progress();
    uint32_t begin = atomic_load_explicit(&begin_index, memory_order_acquire);
    uint32_t end = atomic_load_explicit(&end_index, memory_order_acquire);
    uint32_t total = atomic_load_explicit(&seen, memory_order_relaxed);
    printf("BC250-PICO2-GAP-TIMING relay=%u host_cs=%u relay_oe=%u"
           " real_miso_oe=%u seen=%" PRIu32 " triggers=%" PRIu32
           " capture=%" PRIu32 " dma=%" PRIu32
           " begin=%" PRIu32 " end=%" PRIu32 " region=%u/%u"
           " rxstall=%u bios_write=UNAVAILABLE pico_write=UNAVAILABLE\n",
           relay_armed ? 1u : 0u, gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((relay_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((watch_pio->dbg_padoe >> BC250_MISO) & 1u),
           total,
           atomic_load_explicit(&trigger_count, memory_order_relaxed),
           atomic_load_explicit(&capture_started, memory_order_relaxed),
           done, begin, end,
           atomic_load_explicit(&first_region, memory_order_relaxed) ? 1u : 0u,
           atomic_load_explicit(&last_region, memory_order_relaxed) ? 1u : 0u,
           (unsigned)((watch_pio->fdebug >>
                (PIO_FDEBUG_RXSTALL_LSB + WATCH_SM)) & 1u));
    if (!end || end <= begin + 2u || end > done || end > GAP_CAPACITY) return;
    /* Omit the first potentially partial gap at PIO enable and the gap
     * preceding the region's first read. Keep only internal gaps. */
    uint32_t count = 0, min = UINT32_MAX, max = 0;
    uint64_t sum = 0;
    for (uint32_t i = begin + 1u; i < end; ++i) {
        uint32_t iterations = UINT32_MAX - gaps[i];
        if (iterations < min) min = iterations;
        if (iterations > max) max = iterations;
        ordered[count++] = iterations;
        sum += iterations;
    }
    qsort(ordered, count, sizeof(ordered[0]), cmp_uint32);
    printf(REGION_LABEL " count=%" PRIu32 " min_ns=%" PRIu32
           " p01_ns=%" PRIu32 " median_ns=%" PRIu32
           " p99_ns=%" PRIu32 " max_ns=%" PRIu32
           " mean_ns=%" PRIu32 " resolution_ns=6"
           " includes_only_first_boot_pass=1\n",
           count, to_ns(min), to_ns(ordered[count / 100u]),
           to_ns(ordered[count / 2u]),
           to_ns(ordered[(count * 99u) / 100u]), to_ns(max),
           to_ns((uint32_t)(sum / count)));
}

int main(void) {
    gpio_init(FLASH_CS);
    gpio_disable_pulls(FLASH_CS);
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
    bool clock_ok = set_sys_clock_khz(SYS_HZ / 1000u, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != SYS_HZ) {
        for (;;) { printf("ERROR clock setup; relay off\n"); sleep_ms(1000); }
    }

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

    pio_sm_claim(gap_pio, GAP_SM);
    gap_offset = pio_add_program(gap_pio, &cs_gap_counter_program);
    c = cs_gap_counter_program_get_default_config(gap_offset);
    sm_config_set_jmp_pin(&c, BC250_CS);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(gap_pio, GAP_SM, gap_offset, &c);
    pio_sm_set_consecutive_pindirs(gap_pio, GAP_SM, BC250_CS, 1, false);
    gap_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(gap_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(gap_pio, GAP_SM, false));
    dma_channel_configure(gap_dma, &dc, gaps, &gap_pio->rxf[GAP_SM],
                          GAP_CAPACITY, false);

    multicore_launch_core1(watch_worker);
    pio_sm_set_enabled(watch_pio, WATCH_SM, true);
    printf("BC250-PICO2-GAP-TIMING ready relay=%u"
           " outputs=CS_ONLY pico_write=UNAVAILABLE bios_write=UNAVAILABLE\n",
           relay_armed ? 1u : 0u);
    char line[32];
    unsigned used = 0;
    for (;;) {
        int ch = getchar_timeout_us(0);
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[used] = 0;
            if (!strcmp(line, "status")) status();
            else printf("ERROR command: status\n");
            used = 0;
            stdio_flush();
        } else if (ch >= 0 && used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        }
        tight_loop_contents();
    }
}
