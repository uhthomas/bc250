/*
 * Experimental, input-only BC250 boot SPI command/address capture on Pi 5.
 *
 * Captures the first 32 MOSI bits after each CS# assertion. This only models
 * single-I/O 03h reads (8-bit opcode + 24-bit address) when the transaction
 * contains at least 32 clocks. It does not capture MISO, verify data, measure
 * the SPI clock, or guarantee gap-free capture on this board.
 *
 * The three Pi GPIO output enables are forced OFF before selecting PIO, and
 * there are no PIO SET PINS, OUT PINS, or side-set output instructions.
 * Do not connect Pi 3.3 V, the CH347, or any Pi output to a running BC250.
 */

#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "piolib.h"
#include "hardware/pio.h"

enum { PROGRAM_LENGTH = 7, DEFAULT_WORDS = 16000, MAX_WORDS = 16000 };

static volatile sig_atomic_t interrupted;

static void on_interrupt(int signo)
{
    interrupted = signo;
}

struct options {
    uint cs;
    uint sclk;
    uint mosi;
    uint words;
    bool mode3;
    const char *output;
};

static void usage(const char *name)
{
    fprintf(stderr,
            "Usage: %s --output RAW [--cs GPIO17] [--sclk GPIO27] "
            "[--mosi GPIO22] [--words 1..16000] [--mode3]\n"
            "Captures input-only 32-bit SPI command/address words; start the "
            "wired test source after READY.\n", name);
}

static bool parse_uint(const char *arg, uint *value)
{
    char *end = NULL;
    unsigned long parsed;
    errno = 0;
    parsed = strtoul(arg, &end, 0);
    if (errno || !arg[0] || !end || *end || parsed > UINT32_MAX)
        return false;
    *value = (uint)parsed;
    return true;
}

static bool parse_args(int argc, char **argv, struct options *opt)
{
    *opt = (struct options){ .cs = 17, .sclk = 27, .mosi = 22,
                             .words = DEFAULT_WORDS };
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--mode3")) {
            opt->mode3 = true;
        } else if (!strcmp(argv[i], "--output") && i + 1 < argc) {
            opt->output = argv[++i];
        } else if (!strcmp(argv[i], "--cs") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &opt->cs)) return false;
        } else if (!strcmp(argv[i], "--sclk") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &opt->sclk)) return false;
        } else if (!strcmp(argv[i], "--mosi") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &opt->mosi)) return false;
        } else if (!strcmp(argv[i], "--words") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &opt->words)) return false;
        } else {
            return false;
        }
    }
    return opt->output && opt->output[0] && opt->words >= 1 &&
           opt->words <= MAX_WORDS && opt->cs < 28 && opt->sclk < 28 &&
           opt->mosi < 28 && opt->cs != opt->sclk &&
           opt->cs != opt->mosi && opt->sclk != opt->mosi;
}

static int program_at_free_offset(PIO pio, struct pio_program *program,
                                  uint16_t instructions[PROGRAM_LENGTH])
{
    const int limit = (int)pio_get_instruction_count(pio) - PROGRAM_LENGTH;
    for (int at = 0; at <= limit; ++at) {
        instructions[6] = pio_encode_jmp_x_dec((uint)at + 3);
        program->origin = (int8_t)at;
        if (!pio_can_add_program_at_offset(pio, program, (uint)at))
            continue;
        pio_add_program_at_offset(pio, program, (uint)at);
        if (!pio_get_error(pio))
            return at;
        pio_clear_error(pio);
    }
    return -1;
}

int main(int argc, char **argv)
{
    struct options opt;
    PIO pio = NULL;
    int sm = -1, offset = -1, result = 1;
    unsigned configured_pins = 0;
    uint16_t instructions[PROGRAM_LENGTH];
    struct pio_program program = {
        .instructions = instructions, .length = PROGRAM_LENGTH,
        .origin = -1, .pio_version = 0,
    };
    uint32_t *words = NULL;
    FILE *file = NULL;

    if (!parse_args(argc, argv, &opt)) {
        usage(argv[0]);
        return 2;
    }
    words = calloc(opt.words, sizeof(*words));
    if (!words) {
        perror("allocate capture buffer");
        goto done;
    }
    pio = pio0;
    if (!pio) {
        fprintf(stderr, "RP1 PIO device unavailable (check /dev/pio0)\n");
        goto done;
    }
    pio_enable_fatal_errors(pio, false);
    sm = pio_claim_unused_sm(pio, false);
    if (sm < 0) {
        fprintf(stderr, "No free RP1 PIO state machine\n");
        goto done;
    }

    /* Absolute GPIO waits avoid assumptions about input-base relative pins. */
    /* Prime the bit count before CS# falls, as in the published Pico sniffer. */
    instructions[0] = pio_encode_set(pio_x, 31);
    instructions[1] = pio_encode_wait_gpio(true, opt.cs);
    instructions[2] = pio_encode_wait_gpio(false, opt.cs);
    if (opt.mode3) {
        /* CPOL=1/CPHA=1: first falling edge launches, rising edge samples. */
        instructions[3] = pio_encode_wait_gpio(false, opt.sclk);
        instructions[4] = pio_encode_wait_gpio(true, opt.sclk);
        instructions[5] = pio_encode_in(pio_pins, 1);
    } else {
        /* CPOL=0/CPHA=0: rising edge samples, then wait for falling edge. */
        instructions[3] = pio_encode_wait_gpio(true, opt.sclk);
        instructions[4] = pio_encode_in(pio_pins, 1);
        instructions[5] = pio_encode_wait_gpio(false, opt.sclk);
    }
    /* instruction 6 is the loop jump, relocated for the chosen origin. */
    offset = program_at_free_offset(pio, &program, instructions);
    if (offset < 0) {
        fprintf(stderr, "No free seven-instruction RP1 PIO program range\n");
        goto done;
    }
    if (pio_sm_config_xfer(pio, sm, PIO_DIR_FROM_SM,
                           opt.words * sizeof(*words), 1)) {
        fprintf(stderr, "RP1 DMA receive configuration failed\n");
        goto done;
    }

    const uint pins[] = { opt.cs, opt.sclk, opt.mosi };
    for (unsigned i = 0; i < 3; ++i) {
        /* OEOVER=2 forces output disabled even if a peripheral requests it. */
        gpio_set_oeover(pins[i], 2);
        gpio_disable_pulls(pins[i]);
        gpio_set_input_enabled(pins[i], true);
        pio_gpio_init(pio, pins[i]);
        ++configured_pins;
    }
    pio_sm_config config = pio_get_default_sm_config();
    sm_config_set_wrap(&config, (uint)offset, (uint)offset + 6);
    sm_config_set_in_pins(&config, opt.mosi);
    sm_config_set_in_shift(&config, false, true, 32);
    sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv(&config, 1.0f);
    pio_sm_init(pio, (uint)sm, (uint)offset, &config);
    for (unsigned i = 0; i < 3; ++i)
        pio_sm_set_consecutive_pindirs(pio, (uint)sm, pins[i], 1, false);
    pio_sm_clear_fifos(pio, (uint)sm);
    if ((file = fopen(opt.output, "wx")) == NULL) {
        perror("create raw capture (will not overwrite)");
        goto done;
    }
    struct sigaction action = { .sa_handler = on_interrupt };
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    pio_sm_set_enabled(pio, (uint)sm, true);
    fprintf(stderr,
            "READY: %u input-only words; CS#=GPIO%u SCLK=GPIO%u "
            "MOSI=GPIO%u; mode %d. Start the wired test source now.\n",
            opt.words, opt.cs, opt.sclk, opt.mosi, opt.mode3 ? 3 : 0);
    if (pio_sm_xfer_data(pio, (uint)sm, PIO_DIR_FROM_SM,
                         opt.words * sizeof(*words), words)) {
        fprintf(stderr, "RP1 DMA receive failed%s; raw file is incomplete\n",
                interrupted ? " after signal" : "");
        goto done;
    }
    if (fwrite(words, sizeof(*words), opt.words, file) != opt.words) {
        perror("write raw capture");
        goto done;
    }
    if (fflush(file)) {
        perror("flush raw capture");
        goto done;
    }
    fprintf(stderr, "CAPTURED %u command words to %s\n", opt.words, opt.output);
    result = 0;

done:
    if (pio && sm >= 0)
        pio_sm_set_enabled(pio, (uint)sm, false);
    /* Leave the listening pins high impedance after capture. Restoring the
     * Pi's default pull-down here could bias CS# while the board stays on. */
    const uint cleanup_pins[] = { opt.cs, opt.sclk, opt.mosi };
    for (unsigned i = 0; pio && i < configured_pins; ++i) {
        gpio_set_oeover(cleanup_pins[i], 2);
        gpio_set_function(cleanup_pins[i], GPIO_FUNC_NULL);
        gpio_disable_pulls(cleanup_pins[i]);
        gpio_set_input_enabled(cleanup_pins[i], false);
        gpio_set_oeover(cleanup_pins[i], 0);
    }
    if (pio && offset >= 0)
        pio_remove_program(pio, &program, (uint)offset);
    if (pio && sm >= 0)
        pio_sm_unclaim(pio, (uint)sm);
    if (file && fclose(file)) {
        perror("close raw capture");
        result = 1;
    }
    free(words);
    if (result && file)
        remove(opt.output);
    return result;
}
