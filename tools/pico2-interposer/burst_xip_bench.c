/* RAM-only, on-chip SPI/XIP timing probe. The real BC250 BIOS stays on the
 * separate PIO0 GP7 open-drain CS# relay; no BIOS or Pico flash is written.
 * SPI1 drives only the Pico's unconnected GP9/10/11. PIO1 replies on GP8 and
 * toggles unconnected GP12. PIO2 samples GP8, then DMA compares every byte
 * against a diverse 64-byte range already present in the Pico's own flash.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/address_mapped.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/flash.h"
#include "hardware/pio.h"
#include "hardware/spi.h"
#include "hardware/vreg.h"
#include "burst_xip_bench.pio.h"
#include "burst_xip_capture.pio.h"
#include "cs_open_drain.pio.h"
#include "pins.h"

enum {
    FLASH_CS = 7u, BENCH_MISO = 8u, BENCH_CS = 9u,
    BENCH_SCK = 10u, BENCH_MOSI = 11u, BENCH_FLASH_CS = 12u,
    RELAY_SM = 0u, REPLY_SM = 0u, CAPTURE_SM = 0u,
    REPLY_WORDS = 16u,
    COMMAND = 0x03ae0140u
};
static PIO const relay_pio = pio0;
static PIO const reply_pio = pio1;
static PIO const capture_pio = pio2;
static uint relay_offset, reply_offset, capture_offset, source_dma, capture_dma;
static bool relay_armed;
static uint32_t captured[REPLY_WORDS];
static uint8_t tx_bytes[4u + REPLY_WORDS * 4u];
static uint8_t ignored_rx[sizeof(tx_bytes)];
/* Independent oracle: the public bootflash marker in the normal bench, or
 * a private generated candidate block in the payload bench. */
#ifdef BC250_XIP_BENCH_PRIVATE
#include "df_lock_xip_expected.h"
#else
#define SOURCE_OFFSET 0x7f000u
static const uint32_t expected_source_words[REPLY_WORDS] = {
    0x5069636fu, 0x2050726fu, 0x64756374u, 0x696f6e20u,
    0x54657374u, 0x0a566572u, 0x73696f6eu, 0x3a20302eu,
    0x390a4461u, 0x74653a20u, 0x32382f30u, 0x392f3230u,
    0x32342030u, 0x343a3236u, 0x3a30390au, 0x51522063u,
};
#endif

static inline const volatile uint8_t *source(bool nocache) {
    return (const volatile uint8_t *)(uintptr_t)
        ((nocache ? XIP_NOCACHE_NOALLOC_BASE : XIP_BASE) + SOURCE_OFFSET);
}

static uint32_t first_word(const volatile uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | p[3];
}

static void status(void) {
    printf("BC250-PICO2-XIP-BENCH relay=%u host_cs=%u relay_oe=%u"
           " real_miso_oe=%u clock_hz=%" PRIu32 " peri_hz=%" PRIu32
           " flash_write=UNAVAILABLE bios_write=UNAVAILABLE\n",
           relay_armed ? 1u : 0u, gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((relay_pio->dbg_padoe >> FLASH_CS) & 1u),
           (unsigned)((reply_pio->dbg_padoe >> BC250_MISO) & 1u),
           clock_get_hz(clk_sys), clock_get_hz(clk_peri));
}

static void arm_relay(void) {
    if (!gpio_get(BC250_CS)) return;
    pio_sm_set_enabled(relay_pio, RELAY_SM, false);
    pio_sm_restart(relay_pio, RELAY_SM);
    pio_sm_exec(relay_pio, RELAY_SM, pio_encode_jmp(relay_offset));
    pio_sm_set_consecutive_pindirs(relay_pio, RELAY_SM, FLASH_CS, 1, false);
    pio_sm_set_enabled(relay_pio, RELAY_SM, true);
    sleep_us(10);
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
    relay_armed = true;
}

static void prepare_reply(const volatile uint8_t *data) {
    /* GP8 and GP12 are unwired. Keep them inactive while restarting both SMs. */
    gpio_set_oeover(BENCH_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BENCH_FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_set_enabled(reply_pio, REPLY_SM, false);
    pio_sm_clear_fifos(reply_pio, REPLY_SM);
    pio_sm_restart(reply_pio, REPLY_SM);
    pio_sm_exec(reply_pio, REPLY_SM, pio_encode_jmp(reply_offset));
    pio_sm_set_consecutive_pindirs(reply_pio, REPLY_SM, BENCH_MISO, 1, false);
    pio_sm_set_consecutive_pindirs(reply_pio, REPLY_SM, BENCH_FLASH_CS, 1, false);
    pio_interrupt_clear(reply_pio, 0);
    pio_interrupt_clear(reply_pio, 1);
    reply_pio->txf[REPLY_SM] = COMMAND >> 1;
    pio_sm_set_enabled(reply_pio, REPLY_SM, true);
    sleep_us(5);
    reply_pio->txf[REPLY_SM] = first_word(data);
    dma_channel_set_read_addr(source_dma, (const void *)(data + 4), false);
    dma_channel_set_trans_count(source_dma, REPLY_WORDS - 1u, false);
    dma_channel_start(source_dma);
    sleep_us(5);
    reply_pio->fdebug = (1u << (PIO_FDEBUG_TXSTALL_LSB + REPLY_SM)) |
                        (1u << (PIO_FDEBUG_TXOVER_LSB + REPLY_SM));
    gpio_set_oeover(BENCH_FLASH_CS, GPIO_OVERRIDE_NORMAL);
    gpio_set_oeover(BENCH_MISO, GPIO_OVERRIDE_NORMAL);
}

static void prepare_capture(void) {
    dma_channel_abort(capture_dma);
    pio_sm_set_enabled(capture_pio, CAPTURE_SM, false);
    pio_sm_clear_fifos(capture_pio, CAPTURE_SM);
    pio_sm_restart(capture_pio, CAPTURE_SM);
    pio_sm_exec(capture_pio, CAPTURE_SM, pio_encode_jmp(capture_offset));
    pio_interrupt_clear(capture_pio, 1);
    memset(captured, 0xa5, sizeof(captured));
    dma_channel_set_write_addr(capture_dma, captured, false);
    dma_channel_set_trans_count(capture_dma, REPLY_WORDS, false);
    dma_channel_start(capture_dma);
    pio_sm_set_enabled(capture_pio, CAPTURE_SM, true);
}

static bool bench_one(uint requested_hz, bool nocache, uint iteration) {
    if (!relay_armed || !gpio_get(BC250_CS)) {
        printf("ERROR relay not armed or BC250 CS# active\n");
        return false;
    }
    const volatile uint8_t *data = source(nocache);
    prepare_reply(data);
    prepare_capture();
    uint actual_hz = spi_set_baudrate(spi1, requested_hz);
    sleep_us(10);
    gpio_put(BENCH_CS, 0);
    sleep_us(2);
    int sent = spi_write_read_blocking(spi1, tx_bytes, ignored_rx, sizeof(tx_bytes));
    gpio_put(BENCH_CS, 1);
    sleep_us(20);
    bool selector_done = pio_interrupt_get(reply_pio, 1);
    bool capture_done = pio_interrupt_get(capture_pio, 1);
    uint capture_remaining = dma_channel_hw_addr(capture_dma)->transfer_count;
    uint reply_remaining = dma_channel_hw_addr(source_dma)->transfer_count;
    uint first_bad = REPLY_WORDS;
    uint32_t expected = 0, received = 0;
    for (uint i = 0; i < REPLY_WORDS; ++i) {
        uint32_t word = first_word(data + i * 4u);
        if ((word != expected_source_words[i] ||
             captured[i] != expected_source_words[i]) &&
            first_bad == REPLY_WORDS) {
            first_bad = i;
            expected = expected_source_words[i];
            received = captured[i];
        }
    }
    bool ok = sent == sizeof(tx_bytes) && selector_done && capture_done &&
              !pio_interrupt_get(reply_pio, 0) && !capture_remaining &&
              !reply_remaining && !dma_channel_is_busy(source_dma) &&
              !dma_channel_is_busy(capture_dma) &&
              !pio_sm_get_tx_fifo_level(reply_pio, REPLY_SM) &&
              !((reply_pio->fdebug >> (PIO_FDEBUG_TXSTALL_LSB + REPLY_SM)) & 1u) &&
              first_bad == REPLY_WORDS;
    if (!ok) {
        printf("FAIL iter=%u requested_hz=%u actual_hz=%u nocache=%u"
               " sent=%d selector_done=%u capture_done=%u selector_fault=%u"
               " source_remaining=%u capture_remaining=%u tx_fifo=%u"
               " tx_stall=%u first_bad=%u expected=%08" PRIx32
               " received=%08" PRIx32 "\n",
               iteration, requested_hz, actual_hz, nocache ? 1u : 0u,
               sent, selector_done ? 1u : 0u, capture_done ? 1u : 0u,
               pio_interrupt_get(reply_pio, 0) ? 1u : 0u,
               reply_remaining, capture_remaining,
               pio_sm_get_tx_fifo_level(reply_pio, REPLY_SM),
               (unsigned)((reply_pio->fdebug >>
                    (PIO_FDEBUG_TXSTALL_LSB + REPLY_SM)) & 1u),
               first_bad, expected, received);
    }
    gpio_set_oeover(BENCH_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BENCH_FLASH_CS, GPIO_OVERRIDE_LOW);
    return ok;
}

static void command(const char *line) {
    if (!strcmp(line, "status")) {
        status();
        return;
    }
    unsigned requested_hz, count;
    char cache_mode[12], extra;
    if (sscanf(line, "bench %u %u %11s %c", &requested_hz, &count,
               cache_mode, &extra) != 3 ||
        requested_hz < 1000000u || requested_hz > 50000000u ||
        count < 1u || count > 1000u ||
        (strcmp(cache_mode, "nocache") && strcmp(cache_mode, "cached"))) {
        printf("ERROR commands: status; bench HZ COUNT nocache|cached"
               " (1..50 MHz; count 1..1000)\n");
        return;
    }
    bool nocache = !strcmp(cache_mode, "nocache");
    unsigned passed = 0;
    for (unsigned i = 0; i < count; ++i) {
        if (!bench_one(requested_hz, nocache, i)) break;
        ++passed;
    }
    printf("RESULT passed=%u requested=%u requested_hz=%u actual_hz=%u"
           " nocache=%u relay=%u bios_write=UNAVAILABLE pico_write=UNAVAILABLE\n",
           passed, count, requested_hz, spi_get_baudrate(spi1),
           nocache ? 1u : 0u, relay_armed ? 1u : 0u);
}

int main(void) {
    /* The only real-board output is the existing, board-powered CS# sink. */
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
    bool clock_ok = set_sys_clock_khz(340000, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != 340000000u) {
        for (;;) { printf("ERROR clock setup; relay off\n"); sleep_ms(1000); }
    }
    flash_start_xip();
    rom_flash_select_xip_read_mode(BOOTROM_XIP_MODE_0BH_SERIAL, 6u);
    /* SDK defaults clk_peri to PLL_USB/48 MHz after changing clk_sys. SPI1
     * cannot reach the measured 33.27 MHz bus rate until its source is
     * explicitly changed to the 340 MHz system clock. USB has its own clock. */
    clock_configure_undivided(clk_peri, 0,
        CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS, clock_get_hz(clk_sys));

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
    arm_relay();

    gpio_init(BENCH_MISO);
    gpio_disable_pulls(BENCH_MISO);
    gpio_set_input_enabled(BENCH_MISO, true);
    gpio_set_oeover(BENCH_MISO, GPIO_OVERRIDE_LOW);
    gpio_init(BENCH_FLASH_CS);
    gpio_disable_pulls(BENCH_FLASH_CS);
    gpio_set_outover(BENCH_FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BENCH_FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_claim(reply_pio, REPLY_SM);
    reply_offset = pio_add_program(reply_pio, &burst_xip_bench_program);
    pio_gpio_init(reply_pio, BENCH_MISO);
    pio_gpio_init(reply_pio, BENCH_FLASH_CS);
    gpio_set_input_enabled(BENCH_MISO, true);
    gpio_set_outover(BENCH_FLASH_CS, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BENCH_MISO, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(BENCH_FLASH_CS, GPIO_OVERRIDE_LOW);
    c = burst_xip_bench_program_get_default_config(reply_offset);
    sm_config_set_in_pins(&c, BENCH_MOSI);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_out_pins(&c, BENCH_MISO, 1);
    sm_config_set_out_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_set_pins(&c, BENCH_FLASH_CS, 1);
    sm_config_set_sideset_pins(&c, BENCH_MISO);
    sm_config_set_jmp_pin(&c, BENCH_MOSI);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(reply_pio, REPLY_SM, reply_offset, &c);
    pio_sm_set_pins_with_mask(reply_pio, REPLY_SM, 0, 1u << BENCH_FLASH_CS);
    pio_sm_set_consecutive_pindirs(reply_pio, REPLY_SM, BENCH_FLASH_CS, 1, false);
    pio_sm_set_consecutive_pindirs(reply_pio, REPLY_SM, BENCH_MISO, 1, false);

    source_dma = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(source_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_bswap(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(reply_pio, REPLY_SM, true));
    dma_channel_configure(source_dma, &dc, &reply_pio->txf[REPLY_SM],
                          (const void *)(source(true) + 4), REPLY_WORDS - 1u, false);

    pio_sm_claim(capture_pio, CAPTURE_SM);
    capture_offset = pio_add_program(capture_pio, &burst_xip_capture_program);
    c = burst_xip_capture_program_get_default_config(capture_offset);
    sm_config_set_in_pins(&c, BENCH_MISO);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(capture_pio, CAPTURE_SM, capture_offset, &c);
    pio_sm_set_consecutive_pindirs(capture_pio, CAPTURE_SM, BENCH_MISO, 1, false);
    capture_dma = dma_claim_unused_channel(true);
    dc = dma_channel_get_default_config(capture_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(capture_pio, CAPTURE_SM, false));
    dma_channel_configure(capture_dma, &dc, captured,
                          &capture_pio->rxf[CAPTURE_SM], REPLY_WORDS, false);

    gpio_init(BENCH_CS);
    gpio_disable_pulls(BENCH_CS);
    gpio_put(BENCH_CS, 1);
    gpio_set_dir(BENCH_CS, GPIO_OUT);
    gpio_set_function(BENCH_SCK, GPIO_FUNC_SPI);
    gpio_set_function(BENCH_MOSI, GPIO_FUNC_SPI);
    gpio_set_input_enabled(BENCH_SCK, true);
    gpio_set_input_enabled(BENCH_MOSI, true);
    spi_init(spi1, 1000000u);
    spi_set_format(spi1, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    tx_bytes[0] = 0x03u;
    tx_bytes[1] = 0xaeu;
    tx_bytes[2] = 0x01u;
    tx_bytes[3] = 0x40u;

    printf("BC250-PICO2-XIP-BENCH ready source_offset=%06x"
           " source_bytes=64 relay=%u pins=GP8..12 only"
           " pico_write=UNAVAILABLE bios_write=UNAVAILABLE\n",
           SOURCE_OFFSET, relay_armed ? 1u : 0u);
    char line[96];
    unsigned used = 0;
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
            stdio_flush();
        } else if (ch >= 0 && used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        } else if (ch >= 0) {
            overflow = true;
        }
        sleep_us(50);
    }
}
