/* Isolated Pi SPI0 -> Pico 2 reply timing experiment only.
 * No BC250, BIOS flash, or CS-routing hardware may be connected. GP6 stays
 * undriven. The host must explicitly load replies and start each run.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "fast_reply.pio.h"
#include "pins.h"

#define MAX_REPLIES 1024u
static uint32_t replies[MAX_REPLIES];
static uint loaded;
static PIO const pio = pio0;
static uint offset;
static int tx_dma;
enum { REPLY_SM = 0 };

static uint32_t crc_update(uint32_t crc, const void *ptr, size_t n) {
    const uint8_t *p = ptr;
    while (n--) {
        crc ^= *p++;
        for (uint i = 0; i < 8; ++i)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return crc;
}

static void stop(void) {
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    pio_sm_set_enabled(pio, REPLY_SM, false);
    dma_channel_abort(tx_dma);
    pio_sm_clear_fifos(pio, REPLY_SM);
    pio_sm_restart(pio, REPLY_SM);
}

static bool read_word(uint32_t *word, absolute_time_t deadline) {
    uint8_t *p = (uint8_t *)word;
    for (uint i = 0; i < 4;) {
        if (time_reached(deadline)) return false;
        int c = getchar_timeout_us(1000);
        if (c >= 0) p[i++] = (uint8_t)c;
    }
    return true;
}

static void load(uint n, uint32_t wanted_crc) {
    stop(); loaded = 0;
    printf("LOAD %u\n", n); stdio_flush();
    absolute_time_t deadline = make_timeout_time_ms(30000);
    uint32_t crc = UINT32_MAX;
    for (uint i = 0; i < n; ++i) {
        if (!read_word(&replies[i], deadline)) {
            printf("ERROR upload timeout; reset the Pico\n");
            return;
        }
        crc = crc_update(crc, &replies[i], 4);
    }
    if (~crc != wanted_crc) {
        printf("ERROR upload CRC\n");
        return;
    }
    loaded = n;
    printf("LOADED %u crc=%08" PRIx32 "\n", loaded, ~crc);
}

static void run(uint timeout_ms) {
    if (!loaded) { printf("ERROR load replies first\n"); return; }
    uint n = loaded; loaded = 0;
    pio_sm_config c = fast_reply_program_get_default_config(offset);
    sm_config_set_out_pins(&c, BC250_MISO, 1);
    sm_config_set_sideset_pins(&c, BC250_MISO);
    sm_config_set_out_shift(&c, false, false, 32);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(pio, REPLY_SM, offset, &c);
    pio_sm_set_consecutive_pindirs(pio, REPLY_SM, BC250_MISO, 1, false);
    dma_channel_config dc = dma_channel_get_default_config(tx_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_dreq(&dc, pio_get_dreq(pio, REPLY_SM, true));
    dma_channel_configure(tx_dma, &dc, &pio->txf[REPLY_SM], replies, n, false);
    dma_start_channel_mask(1u << tx_dma);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
    pio_sm_set_enabled(pio, REPLY_SM, true);
    printf("ARMED FAST-BENCH replies=%u clock_hz=%" PRIu32 " outputs=GP5-only\n",
           n, clock_get_hz(clk_sys));
    stdio_flush();
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    const char *done = "done\n";
    uint matched = 0;
    bool aborted = false;
    while (matched < 5 && !time_reached(deadline)) {
        int ch = getchar_timeout_us(0);
        if (ch == 'x' || ch == 'X') { aborted = true; break; }
        matched = ch == done[matched] ? matched + 1u : (ch == 'd' ? 1u : 0u);
        tight_loop_contents();
    }
    bool dma_done = !dma_channel_is_busy(tx_dma);
    stop();
    if (aborted || matched < 5) {
        printf("ERROR bench aborted/timeout; outputs off\n");
        return;
    }
    printf("RESULT %u dma_complete=%u outputs=OFF\n", n, dma_done ? 1u : 0u);
}

static void command(char *line) {
    uint n, timeout, crc;
    char extra;
    if (!strcmp(line, "status")) {
        printf("BC250-PICO2-FAST-BENCH v1 clock_hz=%" PRIu32
               " outputs=OFF-UNTIL-RUN GP6=INPUT isolated_only=1 loaded=%u\n",
               clock_get_hz(clk_sys), loaded);
    } else if (sscanf(line, "load %u %x %c", &n, &crc, &extra) == 2 &&
               n > 0 && n <= MAX_REPLIES) {
        load(n, crc);
    } else if (sscanf(line, "bench-isolated %u %c", &timeout, &extra) == 1 &&
               timeout >= 100 && timeout <= 120000) {
        run(timeout);
    } else {
        printf("ERROR status; load N CRC32; bench-isolated TIMEOUT_MS\n");
    }
}

int main(void) {
    for (uint pin = BC250_CS; pin <= BC250_FLASH_CS; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    /* Experimental, isolated 200 MHz clock. RP2350 is specified to 150 MHz. */
    vreg_set_voltage(VREG_VOLTAGE_1_20);
    sleep_ms(10);
    bool clock_ok = set_sys_clock_khz(200000, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != 200000000u) {
        for (;;) { printf("ERROR 200 MHz clock setup failed; outputs off\n"); sleep_ms(1000); }
    }
    pio_sm_claim(pio, REPLY_SM);
    offset = pio_add_program(pio, &fast_reply_program);
    tx_dma = dma_claim_unused_channel(true);
    for (uint pin = BC250_CS; pin <= BC250_MISO; ++pin) {
        pio_gpio_init(pio, pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    char line[96]; uint used = 0; bool overflow = false;
    for (;;) {
        int ch = getchar_timeout_us(10000);
        if (ch < 0 || ch == '\r') continue;
        if (ch == '\n') {
            line[used] = 0;
            if (overflow) printf("ERROR line too long\n");
            else if (used) command(line);
            used = 0; overflow = false;
        } else if (used < sizeof(line) - 1) line[used++] = (char)ch;
        else overflow = true;
    }
}
