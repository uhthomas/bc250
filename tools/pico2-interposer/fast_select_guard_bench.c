/* Isolated Pi SPI0 -> Pico 2 full-command guarded selector experiment only.
 * GP7 drives an otherwise UNCONNECTED pin. No BC250, BIOS flash, or CS-routing
 * hardware may be connected. There is no BC250 board profile or arm command.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "hardware/structs/io_bank0.h"
#include "hardware/structs/pads_bank0.h"
#include "fast_select_guard.pio.h"
#include "select_observe.pio.h"
#include "address_hunt.pio.h"
#include "pins.h"

#define MAX_REPLIES 1024u
static uint32_t script_words[3u * MAX_REPLIES];
static uint32_t observed[MAX_REPLIES];
static uint32_t observed_commands[MAX_REPLIES];
static uint loaded;
static PIO const pio = pio0;
static PIO const observer = pio1;
static uint offset, observer_offset, command_offset;
static int tx_dma, observe_dma, command_dma;
enum { SELECT_SM = 0, OBSERVE_SM = 0, COMMAND_SM = 1 };

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
    gpio_set_oeover(BC250_FLASH_CS, GPIO_OVERRIDE_LOW);
    pio_sm_set_enabled(pio, SELECT_SM, false);
    pio_sm_set_enabled(observer, OBSERVE_SM, false);
    pio_sm_set_enabled(observer, COMMAND_SM, false);
    dma_channel_abort(tx_dma);
    dma_channel_abort(observe_dma);
    dma_channel_abort(command_dma);
    pio_sm_clear_fifos(pio, SELECT_SM);
    pio_sm_clear_fifos(observer, OBSERVE_SM);
    pio_sm_clear_fifos(observer, COMMAND_SM);
    pio_sm_restart(pio, SELECT_SM);
    pio_sm_restart(observer, OBSERVE_SM);
    pio_sm_restart(observer, COMMAND_SM);
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
    for (uint i = 0; i < 3u * n; ++i) {
        if (!read_word(&script_words[i], deadline)) {
            printf("ERROR upload timeout; reset the Pico\n");
            return;
        }
        crc = crc_update(crc, &script_words[i], 4);
    }
    if (~crc != wanted_crc) {
        printf("ERROR upload CRC\n");
        return;
    }
    for (uint i = 0; i < n; ++i) {
        if (script_words[3u * i] > 1u ||
            script_words[3u * i + 1u] != 0x03100000u + 4u * i) {
            printf("ERROR invalid route or expected command\n");
            return;
        }
    }
    loaded = n;
    printf("LOADED %u crc=%08" PRIx32 "\n", loaded, ~crc);
}

static void run(uint timeout_ms) {
    if (!loaded) { printf("ERROR load PASS/PATCH script first\n"); return; }
    uint n = loaded; loaded = 0;
    if (!gpio_get(BC250_CS) || gpio_get(BC250_SCLK)) {
        printf("ERROR isolated master must idle with CS=1 SCLK=0\n");
        return;
    }
    pio_interrupt_clear(pio, 0);
    pio_sm_config c = fast_select_guard_program_get_default_config(offset);
    sm_config_set_out_pins(&c, BC250_MISO, 1);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_sideset_pins(&c, BC250_MISO);
    sm_config_set_set_pins(&c, BC250_FLASH_CS, 1);
    sm_config_set_out_shift(&c, false, false, 32);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(pio, SELECT_SM, offset, &c);
    pio_sm_set_pins_with_mask(pio, SELECT_SM, 1u << BC250_FLASH_CS,
                              1u << BC250_FLASH_CS);
    pio_sm_set_consecutive_pindirs(pio, SELECT_SM, BC250_MISO, 1, false);
    pio_sm_set_consecutive_pindirs(pio, SELECT_SM, BC250_FLASH_CS, 1, true);

    c = select_observe_program_get_default_config(observer_offset);
    sm_config_set_in_pins(&c, BC250_FLASH_CS);
    sm_config_set_in_shift(&c, true, false, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(observer, OBSERVE_SM, observer_offset, &c);

    c = address_hunt_program_get_default_config(command_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(observer, COMMAND_SM, command_offset, &c);

    dma_channel_config dc = dma_channel_get_default_config(tx_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, true);
    channel_config_set_write_increment(&dc, false);
    channel_config_set_dreq(&dc, pio_get_dreq(pio, SELECT_SM, true));
    dma_channel_configure(tx_dma, &dc, &pio->txf[SELECT_SM], script_words,
                          3u * n, false);
    dc = dma_channel_get_default_config(observe_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(observer, OBSERVE_SM, false));
    dma_channel_configure(observe_dma, &dc, observed,
                          &observer->rxf[OBSERVE_SM], n, false);
    dc = dma_channel_get_default_config(command_dma);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(observer, COMMAND_SM, false));
    dma_channel_configure(command_dma, &dc, observed_commands,
                          &observer->rxf[COMMAND_SM], n, false);

    dma_start_channel_mask((1u << tx_dma) | (1u << observe_dma) |
                           (1u << command_dma));
    gpio_set_oeover(BC250_FLASH_CS, GPIO_OVERRIDE_NORMAL);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_NORMAL);
    pio_sm_set_enabled(observer, OBSERVE_SM, true);
    pio_sm_set_enabled(observer, COMMAND_SM, true);
    pio_sm_set_enabled(pio, SELECT_SM, true);
    printf("ARMED FAST-GUARD rows=%u clock_hz=%" PRIu32
           " GP%u=OUTPUT-ISOLATED board_arm=UNAVAILABLE\n",
           n, clock_get_hz(clk_sys), BC250_FLASH_CS);
    stdio_flush();
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    char input[16];
    uint used = 0;
    bool finished = false;
    bool aborted = false;
    while (!finished && !time_reached(deadline)) {
        int ch = getchar_timeout_us(0);
        if (ch == 'x' || ch == 'X') { aborted = true; break; }
        if (ch == '\r') continue;
        if (ch == '\n') {
            input[used] = 0;
            if (!strcmp(input, "done")) finished = true;
            else if (!strcmp(input, "peek")) {
                uint32_t const bit = 1u << BC250_FLASH_CS;
                printf("PEEK cs=%u sclk=%u pad=%u pio_out=%u pio_oe=%u"
                       " pc=%u tx_level=%u fdebug=%08" PRIx32
                       " io_status=%08" PRIx32 " io_ctrl=%08" PRIx32
                       " pad_ctrl=%08" PRIx32 "\n",
                       gpio_get(BC250_CS) ? 1u : 0u,
                       gpio_get(BC250_SCLK) ? 1u : 0u,
                       gpio_get(BC250_FLASH_CS) ? 1u : 0u,
                       (pio->dbg_padout & bit) ? 1u : 0u,
                       (pio->dbg_padoe & bit) ? 1u : 0u,
                       pio_sm_get_pc(pio, SELECT_SM),
                       pio_sm_get_tx_fifo_level(pio, SELECT_SM),
                       pio->fdebug,
                       io_bank0_hw->io[BC250_FLASH_CS].status,
                       io_bank0_hw->io[BC250_FLASH_CS].ctrl,
                       pads_bank0_hw->io[BC250_FLASH_CS]);
                stdio_flush();
            } else if (used) printf("ERROR run accepts peek or done\n");
            used = 0;
        } else if (ch >= 0 && used < sizeof(input) - 1u) input[used++] = (char)ch;
        else if (ch >= 0) { aborted = true; break; }
        tight_loop_contents();
    }
    bool reply_dma_done = !dma_channel_is_busy(tx_dma);
    bool select_dma_done = !dma_channel_is_busy(observe_dma);
    bool command_dma_done = !dma_channel_is_busy(command_dma);
    bool fault_irq = pio_interrupt_get(pio, 0);
    uint fault_miso_pio_oe = (pio->dbg_padoe >> BC250_MISO) & 1u;
    uint fault_flash_cs_pad = gpio_get(BC250_FLASH_CS) ? 1u : 0u;
    stop();
    if (aborted || !finished) {
        printf("ERROR bench aborted/timeout; outputs off\n");
        return;
    }
    uint first_errors = 0, second_errors = 0, bad_rows = 0;
    if (select_dma_done) {
        for (uint i = 0; i < n; ++i) {
            uint wanted = script_words[3u * i];
            bool bad_first = ((observed[i] >> 30) & 1u) != wanted;
            bool bad_second = ((observed[i] >> 31) & 1u) != wanted;
            first_errors += bad_first;
            second_errors += bad_second;
            bad_rows += bad_first || bad_second;
        }
    } else {
        first_errors = second_errors = bad_rows = n;
    }
    uint command_errors = 0;
    if (command_dma_done) {
        for (uint i = 0; i < n; ++i)
            command_errors += observed_commands[i] != (0x03100000u + 4u * i);
    } else command_errors = n;
    printf("RESULT %u reply_dma_complete=%u select_dma_complete=%u"
           " command_dma_complete=%u first_errors=%u second_errors=%u"
           " bad_rows=%u command_errors=%u fault_irq=%u"
           " miso_pio_oe=%u flash_cs_pad=%u outputs=OFF\n",
           n, reply_dma_done ? 1u : 0u, select_dma_done ? 1u : 0u,
           command_dma_done ? 1u : 0u, first_errors, second_errors,
           bad_rows, command_errors, fault_irq ? 1u : 0u,
           fault_miso_pio_oe, fault_flash_cs_pad);
    if (select_dma_done) {
        uint printed = 0;
        for (uint i = 0; i < n && printed < 16u; ++i) {
            uint wanted = script_words[3u * i];
            uint first = (observed[i] >> 30) & 1u;
            uint second = (observed[i] >> 31) & 1u;
            if (first != wanted || second != wanted) {
                printf("BAD %u wanted=%u first=%u second=%u\n",
                       i, wanted, first, second);
                ++printed;
            }
        }
    }
    if (command_dma_done) {
        uint printed = 0;
        for (uint i = 0; i < n && printed < 16u; ++i) {
            uint32_t expected = 0x03100000u + 4u * i;
            if (observed_commands[i] != expected) {
                printf("BADCMD %u expected=%08" PRIx32 " observed=%08" PRIx32 "\n",
                       i, expected, observed_commands[i]);
                ++printed;
            }
        }
    }
    printf("END\n");
}

static void command(char *line) {
    uint n, timeout, crc;
    char extra;
    if (!strcmp(line, "status")) {
        printf("BC250-PICO2-FAST-GUARD v7 clock_hz=%" PRIu32
               " outputs=OFF-UNTIL-RUN GP%u=ISOLATED-OUTPUT board_arm=UNAVAILABLE loaded=%u\n",
               clock_get_hz(clk_sys), BC250_FLASH_CS, loaded);
    } else if (sscanf(line, "load %u %x %c", &n, &crc, &extra) == 2 &&
               n > 0 && n <= MAX_REPLIES) {
        load(n, crc);
    } else if (sscanf(line, "select-isolated %u %c", &timeout, &extra) == 1 &&
               timeout >= 100 && timeout <= 120000) {
        run(timeout);
    } else {
        printf("ERROR status; load N CRC32; select-isolated TIMEOUT_MS\n");
    }
}

int main(void) {
    for (uint pin = BC250_CS; pin <= BC250_FLASH_CS; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    /* Experimental, isolated 340 MHz clock. RP2350 is specified to 150 MHz. */
    vreg_set_voltage(VREG_VOLTAGE_1_30);
    sleep_ms(10);
    bool clock_ok = set_sys_clock_khz(340000, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != 340000000u) {
        for (;;) { printf("ERROR 340 MHz clock setup failed; outputs off\n"); sleep_ms(1000); }
    }
    pio_sm_claim(pio, SELECT_SM);
    offset = pio_add_program(pio, &fast_select_guard_program);
    pio_sm_claim(observer, OBSERVE_SM);
    observer_offset = pio_add_program(observer, &select_observe_program);
    pio_sm_claim(observer, COMMAND_SM);
    command_offset = pio_add_program(observer, &address_hunt_program);
    tx_dma = dma_claim_unused_channel(true);
    observe_dma = dma_claim_unused_channel(true);
    command_dma = dma_claim_unused_channel(true);
    for (uint pin = BC250_CS; pin <= BC250_FLASH_CS; ++pin) {
        pio_gpio_init(pio, pin);
        gpio_disable_pulls(pin);
        gpio_set_input_enabled(pin, true);
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
