/* BC250 passive SPI capture. Bus output enables are forced off throughout.
 * Captures raw CS/SCLK/MOSI/MISO, including short/aborted transactions.
 * Never drives SPI, selects the flash, or writes board/Pico flash at runtime.
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
#include "hardware/regs/dma.h"
#include "hardware/regs/pio.h"
#include "capture.pio.h"
#include "address_hunt.pio.h"
#include "pins.h"

#define MAX_WORDS 98304u
#define MAX_HITS 4096u
static uint32_t samples[MAX_WORDS];
struct hunt_hit { uint32_t transaction, command; };
static struct hunt_hit hunt_hits[MAX_HITS];
static volatile uint32_t discard;
static PIO const capture_pio = pio0;
static uint sm, offset;
static int dma_capture, dma_guard;
static uint hunt_sm, hunt_offset;
static bool hunt_core_started;
static _Atomic bool hunt_running;
static uint32_t hunt_first, hunt_last;
static volatile uint32_t hunt_seen, hunt_count, hunt_overflow;

struct capture_header {
    char magic[8];
    uint32_t words, clock_hz, divider, skipped, flags, crc32;
};
_Static_assert(sizeof(struct capture_header) == 32, "wire header layout");
_Static_assert(BC250_CS == 2 && BC250_SCLK == 3 && BC250_MOSI == 4 &&
               BC250_MISO == 5, "raw_capture PIO uses this fixed pin layout");

static uint32_t crc32_bytes(const void *ptr, size_t len) {
    const uint8_t *p = ptr;
    uint32_t crc = UINT32_MAX;
    while (len--) {
        crc ^= *p++;
        for (uint i = 0; i < 8; ++i)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

static void bus_inputs(void) {
    /* gpio_set_function clears OE overrides: select the function first while
     * PIO is disabled and its directions are all inputs, THEN force OE low. */
    for (uint pin = BC250_CS; pin <= BC250_FLASH_CS; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_input_enabled(pin, true);
        pio_sm_set_consecutive_pindirs(capture_pio, sm, pin, 1, false);
        pio_gpio_init(capture_pio, pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
}

static void stop_capture(void) {
    pio_sm_set_enabled(capture_pio, sm, false);
    /* Abort the source first; after it is stopped it cannot chain to the sink.
     * The sink guard only writes one RAM word. */
    dma_channel_abort(dma_capture);
    dma_channel_abort(dma_guard);
    pio_sm_clear_fifos(capture_pio, sm);
    pio_sm_restart(capture_pio, sm);
}

static void send_capture(uint words, uint divider, uint skip, uint32_t flags) {
    struct capture_header header = {
        .magic = {'B','C','2','5','R','A','W','1'}, .words = words,
        .clock_hz = clock_get_hz(clk_sys), .divider = divider, .skipped = skip,
        .flags = flags, .crc32 = crc32_bytes(samples, words * sizeof(*samples)),
    };
    printf("DATA %u\n", (uint)(sizeof(header) + words * sizeof(*samples)));
    /* SDK printf bypasses libc's FILE buffering. Mixing it with fwrite left
     * a final partial FILE buffer unsent and put DONE before the binary tail.
     * Use the same SDK transport for every byte, with CR/LF conversion off. */
    stdio_put_string((const char *)&header, sizeof(header), false, false);
    stdio_put_string((const char *)samples, words * sizeof(*samples), false, false);
    printf("\nDONE\n");
    stdio_flush();
}

static void usb_test(uint words) {
    /* Exercise the full transport with every byte value, without touching PIO
     * or GPIO. Mark the packet synthetic so no decoder can qualify it as SPI. */
    uint8_t *bytes = (uint8_t *)samples;
    for (uint i = 0; i < words * sizeof(*samples); ++i) bytes[i] = (uint8_t)i;
    printf("ARMED USB-TEST words=%u no_bus_capture=1\n", words);
    send_capture(words, 1, 0, 0x80000000u);
}

static void __not_in_flash_func(hunt_worker)(void) {
    for (;;) {
        if (!atomic_load_explicit(&hunt_running, memory_order_acquire)) {
            sleep_ms(1);
            continue;
        }
        if (pio_sm_is_rx_fifo_empty(capture_pio, hunt_sm)) continue;
        uint32_t command = capture_pio->rxf[hunt_sm];
        uint32_t transaction = hunt_seen++;
        uint32_t address = command & 0xffffffu;
        if ((command >> 24) != 3u || address < hunt_first || address >= hunt_last)
            continue;
        uint32_t count = hunt_count;
        if (count < MAX_HITS) {
            hunt_hits[count] = (struct hunt_hit){transaction, command};
            hunt_count = count + 1u;
        } else {
            hunt_overflow++;
        }
    }
}

static void hunt(uint32_t first, uint32_t last, uint32_t timeout_ms) {
    if (!hunt_core_started) {
        hunt_sm = pio_claim_unused_sm(capture_pio, true);
        hunt_offset = pio_add_program(capture_pio, &address_hunt_program);
        multicore_launch_core1(hunt_worker);
        hunt_core_started = true;
    }
    pio_sm_config c = address_hunt_program_get_default_config(hunt_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(capture_pio, hunt_sm, hunt_offset, &c);
    for (uint pin = BC250_CS; pin <= BC250_FLASH_CS; ++pin)
        pio_sm_set_consecutive_pindirs(capture_pio, hunt_sm, pin, 1, false);
    hunt_seen = hunt_count = hunt_overflow = 0;
    hunt_first = first;
    hunt_last = last;
    uint32_t stall_mask = 1u << (PIO_FDEBUG_RXSTALL_LSB + hunt_sm);
    capture_pio->fdebug = stall_mask;
    atomic_store_explicit(&hunt_running, true, memory_order_release);
    printf("ARMED HUNT first=%06" PRIx32 " last=%06" PRIx32
           " timeout_ms=%" PRIu32 " outputs=OFF\n", first, last, timeout_ms);
    stdio_flush();
    pio_sm_set_enabled(capture_pio, hunt_sm, true);
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    bool cancelled = false;
    while (!time_reached(deadline)) {
        int ch = getchar_timeout_us(0);
        if (ch == 'x' || ch == 'X') { cancelled = true; break; }
        tight_loop_contents();
    }
    pio_sm_set_enabled(capture_pio, hunt_sm, false);
    absolute_time_t drain = make_timeout_time_ms(100);
    while (!pio_sm_is_rx_fifo_empty(capture_pio, hunt_sm) &&
           !time_reached(drain)) tight_loop_contents();
    atomic_store_explicit(&hunt_running, false, memory_order_release);
    sleep_ms(2);
    uint32_t flags = (capture_pio->fdebug & stall_mask) ? 1u : 0u;
    printf("HITS seen=%" PRIu32 " kept=%" PRIu32 " overflow=%" PRIu32
           " stall=%" PRIu32 " cancelled=%u\n", hunt_seen, hunt_count,
           hunt_overflow, flags, cancelled ? 1u : 0u);
    for (uint32_t i = 0; i < hunt_count; ++i)
        printf("%" PRIu32 " %08" PRIx32 "\n",
               hunt_hits[i].transaction, hunt_hits[i].command);
    printf("DONEH\n");
    stdio_flush();
}

static void capture(uint skip, uint words, uint divider, uint timeout_ms) {
    pio_sm_config c = raw_capture_program_get_default_config(offset);
    sm_config_set_in_pins(&c, BC250_CS);
    sm_config_set_in_shift(&c, true, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_NONE);
    sm_config_set_clkdiv_int_frac(&c, divider, 0);
    pio_sm_init(capture_pio, sm, offset, &c);
    bus_inputs();
    pio_sm_put(capture_pio, sm, skip);

    dma_channel_config sink = dma_channel_get_default_config(dma_guard);
    channel_config_set_transfer_data_size(&sink, DMA_SIZE_32);
    channel_config_set_read_increment(&sink, false);
    channel_config_set_write_increment(&sink, false);
    channel_config_set_dreq(&sink, pio_get_dreq(capture_pio, sm, false));
    dma_channel_configure(dma_guard, &sink, &discard, &capture_pio->rxf[sm],
                          dma_encode_endless_transfer_count(), false);
    dma_channel_config dc = dma_channel_get_default_config(dma_capture);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(capture_pio, sm, false));
    channel_config_set_chain_to(&dc, dma_guard);
    dma_channel_configure(dma_capture, &dc, samples, &capture_pio->rxf[sm], words, false);
    uint32_t stall_mask = 1u << (PIO_FDEBUG_RXSTALL_LSB + sm);
    capture_pio->fdebug = stall_mask;
    printf("ARMED skip=%u words=%u clock_hz=%" PRIu32 " divider=%u timeout_ms=%u\n",
           skip, words, clock_get_hz(clk_sys), divider, timeout_ms);
    stdio_flush();
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    dma_start_channel_mask(1u << dma_capture);
    pio_sm_set_enabled(capture_pio, sm, true);
    bool cancelled = false, timeout = false;
    while (dma_channel_is_busy(dma_capture)) {
        int ch = getchar_timeout_us(0);
        if (ch == 'x' || ch == 'X') { cancelled = true; break; }
        if (time_reached(deadline)) { timeout = true; break; }
        tight_loop_contents();
    }
    uint32_t flags = (capture_pio->fdebug & stall_mask) ? 1u : 0u;
    if (dma_hw->ch[dma_capture].ctrl_trig & DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS)
        flags |= 2u;
    stop_capture();
    if (cancelled || timeout) {
        printf("ERROR %s; no capture exported\n", cancelled ? "cancelled" : "timeout");
        return;
    }
    send_capture(words, divider, skip, flags);
}

static void command(char *line) {
    uint skip, words, divider, timeout_ms;
    uint32_t hunt_start, hunt_end;
    char extra;
    if (!strcmp(line, "status") || !strcmp(line, "help")) {
        printf("BC250-PICO2-PASSIVE v1 clock_hz=%" PRIu32
               " max_words=%u pins=CS:2,SCLK:3,MOSI:4,MISO:5 reserved:6 outputs=OFF transport=direct usb_test=1 hunt=1\n",
               clock_get_hz(clk_sys), MAX_WORDS);
        printf("capture SKIP WORDS DIVIDER TIMEOUT_MS; hunt FIRST_HEX LAST_HEX TIMEOUT_MS; usb-test WORDS; x cancels; status; help\n");
    } else if (sscanf(line, "usb-test %u %c", &words, &extra) == 1 && words > 0 && words <= MAX_WORDS) {
        usb_test(words);
    } else if (sscanf(line, "capture %u %u %u %u %c", &skip, &words,
                      &divider, &timeout_ms, &extra) == 4 &&
               skip <= 10000000u && words > 0 && words <= MAX_WORDS &&
               divider > 0 && divider <= 65535 && timeout_ms >= 100 && timeout_ms <= 120000) {
        capture(skip, words, divider, timeout_ms);
    } else if (sscanf(line, "hunt %" SCNx32 " %" SCNx32 " %u %c",
                      &hunt_start, &hunt_end, &timeout_ms, &extra) == 3 &&
               hunt_start < hunt_end && hunt_end <= 0x1000000u &&
               timeout_ms >= 100 && timeout_ms <= 120000) {
        hunt(hunt_start, hunt_end, timeout_ms);
    } else {
        printf("ERROR invalid command or limits\n");
    }
}

int main(void) {
    /* First operation: leave all five bus-related GPIOs as undriven inputs. */
    for (uint pin = BC250_CS; pin <= BC250_FLASH_CS; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    stdio_init_all();
    sm = pio_claim_unused_sm(capture_pio, true);
    offset = pio_add_program(capture_pio, &raw_capture_program);
    dma_capture = dma_claim_unused_channel(true);
    dma_guard = dma_claim_unused_channel(true);
    bus_inputs();
    char line[96];
    size_t n = 0;
    bool overflow = false;
    for (;;) {
        int ch = getchar_timeout_us(10000);
        if (ch < 0) continue;
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[n] = 0;
            if (overflow) printf("ERROR line too long\n");
            else if (n) command(line);
            n = 0; overflow = false;
        } else if (n < sizeof(line) - 1) line[n++] = (char)ch;
        else overflow = true;
    }
}
