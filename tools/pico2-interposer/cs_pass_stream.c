/* RAM-only original-flash CS# relay plus lossless RLE READ03 command stream.
 * PIO0 alone owns the lifted flash CS# output. PIO1 observes GP2/3/4 only.
 * The command stream is sent over USB; no BIOS/Pico flash or MISO writes.
 */
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "hardware/vreg.h"
#include "cs_open_drain.pio.h"
#include "address_hunt.pio.h"
#include "pins.h"

enum { FLASH_CS = 7u, CS_SM = 0u, STREAM_SM = 0u,
       RING_RECORDS = 32768u, CHUNK_RECORDS = 256u };
struct record { uint32_t start, count; };
static struct record ring[RING_RECORDS];
static PIO const relay_pio = pio0;
static PIO const stream_pio = pio1;
static uint relay_offset, stream_offset;
static bool armed, gate;
static _Atomic bool stream_running, worker_active, worker_done;
static _Atomic uint32_t producer, consumer;
static volatile uint32_t seen, overflow;
static uint32_t commands_sent;

static uint32_t crc32(const struct record *records, uint n) {
    uint32_t crc = UINT32_MAX;
    const uint8_t *p = (const uint8_t *)records;
    for (uint i = 0; i < n * sizeof(*records); ++i) {
        crc ^= p[i];
        for (uint bit = 0; bit < 8u; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

static void __not_in_flash_func(stream_worker)(void) {
    uint32_t run_start = 0u, run_last = 0u, run_count = 0u;
    bool active = false;
    for (;;) {
        if (!atomic_load_explicit(&stream_running, memory_order_acquire)) {
            if (active && run_count) {
                uint32_t write = atomic_load_explicit(&producer, memory_order_relaxed);
                uint32_t read = atomic_load_explicit(&consumer, memory_order_acquire);
                if (write - read == RING_RECORDS) overflow += run_count;
                else {
                    ring[write & (RING_RECORDS - 1u)] =
                        (struct record){run_start, run_count};
                    atomic_store_explicit(&producer, write + 1u, memory_order_release);
                }
                run_count = 0u;
            }
            if (active) {
                active = false;
                atomic_store_explicit(&worker_active, false, memory_order_release);
                atomic_store_explicit(&worker_done, true, memory_order_release);
            }
            tight_loop_contents();
            continue;
        }
        if (!active) {
            active = true;
            atomic_store_explicit(&worker_active, true, memory_order_release);
        }
        if (pio_sm_is_rx_fifo_empty(stream_pio, STREAM_SM)) continue;
        uint32_t word = stream_pio->rxf[STREAM_SM];
        ++seen;
        if (!run_count) {
            run_start = run_last = word;
            run_count = 1u;
            continue;
        }
        if (word == run_last + 4u && run_count < UINT32_MAX) {
            run_last = word;
            ++run_count;
            continue;
        }
        uint32_t write = atomic_load_explicit(&producer, memory_order_relaxed);
        uint32_t read = atomic_load_explicit(&consumer, memory_order_acquire);
        if (write - read == RING_RECORDS) overflow += run_count;
        else {
            ring[write & (RING_RECORDS - 1u)] =
                (struct record){run_start, run_count};
            atomic_store_explicit(&producer, write + 1u, memory_order_release);
        }
        run_start = run_last = word;
        run_count = 1u;
    }
}

static void gate_off(void) {
    gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate = false;
}

static void status(void) {
    printf("BC250-PICO2-CS-PASS-STREAM v2 clock_hz=%" PRIu32
           " armed=%u gate=%u host_cs=%u pio_oe=%u out_override=LOW"
           " miso=INPUT bios_write=UNAVAILABLE ring_records=%u\n",
           clock_get_hz(clk_sys), armed ? 1u : 0u, gate ? 1u : 0u,
           gpio_get(BC250_CS) ? 1u : 0u,
           (unsigned)((relay_pio->dbg_padoe >> FLASH_CS) & 1u), RING_RECORDS);
}

static void send_chunk(uint32_t read, uint n) {
    struct record const *records = ring + (read & (RING_RECORDS - 1u));
    printf("CHNK %u %08" PRIx32 "\n", n, crc32(records, n));
    stdio_put_string((const char *)records, n * sizeof(*records), false, false);
    printf("\n");
    stdio_flush();
    for (uint i = 0; i < n; ++i) commands_sent += records[i].count;
    atomic_store_explicit(&consumer, read + n, memory_order_release);
}

static void stream(uint32_t timeout_ms) {
    if (!armed || atomic_load_explicit(&stream_running, memory_order_acquire)) {
        printf("ERROR arm-pass before stream-pass; one stream at a time\n");
        return;
    }
    pio_sm_config c = address_hunt_program_get_default_config(stream_offset);
    sm_config_set_in_pins(&c, BC250_MOSI);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(stream_pio, STREAM_SM, stream_offset, &c);
    pio_sm_set_consecutive_pindirs(stream_pio, STREAM_SM, BC250_CS, 3, false);
    atomic_store_explicit(&consumer, 0u, memory_order_relaxed);
    atomic_store_explicit(&producer, 0u, memory_order_relaxed);
    seen = overflow = commands_sent = 0u;
    uint32_t stall_mask = 1u << (PIO_FDEBUG_RXSTALL_LSB + STREAM_SM);
    stream_pio->fdebug = stall_mask;
    atomic_store_explicit(&worker_done, false, memory_order_release);
    atomic_store_explicit(&stream_running, true, memory_order_release);
    while (!atomic_load_explicit(&worker_active, memory_order_acquire))
        tight_loop_contents();
    pio_sm_set_enabled(stream_pio, STREAM_SM, true);
    printf("ARMED STREAM-PASS timeout_ms=%" PRIu32
           " outputs=CS_ONLY framing=RLE-v2\n", timeout_ms);
    stdio_flush();
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    bool cancelled = false;
    while (!time_reached(deadline)) {
        uint32_t read = atomic_load_explicit(&consumer, memory_order_relaxed);
        uint32_t write = atomic_load_explicit(&producer, memory_order_acquire);
        uint32_t available = write - read;
        if (available >= CHUNK_RECORDS) {
            uint n = available > CHUNK_RECORDS ? CHUNK_RECORDS : available;
            uint contiguous = RING_RECORDS - (read & (RING_RECORDS - 1u));
            if (n > contiguous) n = contiguous;
            send_chunk(read, n);
        } else {
            int ch = getchar_timeout_us(0);
            if (ch == 'x' || ch == 'X') { cancelled = true; break; }
            tight_loop_contents();
        }
    }
    pio_sm_set_enabled(stream_pio, STREAM_SM, false);
    sleep_ms(10); /* core1 drains the final RX FIFO words */
    atomic_store_explicit(&stream_running, false, memory_order_release);
    for (;;) {
        uint32_t read = atomic_load_explicit(&consumer, memory_order_relaxed);
        uint32_t write = atomic_load_explicit(&producer, memory_order_acquire);
        if (read == write && atomic_load_explicit(&worker_done, memory_order_acquire)) break;
        uint n = write - read;
        if (n > CHUNK_RECORDS) n = CHUNK_RECORDS;
        uint contiguous = RING_RECORDS - (read & (RING_RECORDS - 1u));
        if (n > contiguous) n = contiguous;
        if (n) send_chunk(read, n);
        else tight_loop_contents();
    }
    printf("DONE seen=%" PRIu32 " sent=%" PRIu32 " records=%" PRIu32
           " overflow=%" PRIu32 " stall=%u cancelled=%u\n", seen,
           commands_sent, atomic_load_explicit(&consumer, memory_order_acquire), overflow,
           (stream_pio->fdebug & stall_mask) ? 1u : 0u, cancelled ? 1u : 0u);
    stdio_flush();
}

static void usb_test(uint32_t words) {
    if (armed || words == 0u || words > RING_RECORDS) {
        printf("ERROR USB test requires unarmed output and 1..%u records\n", RING_RECORDS);
        return;
    }
    atomic_store_explicit(&consumer, 0u, memory_order_relaxed);
    atomic_store_explicit(&producer, words, memory_order_relaxed);
    commands_sent = 0u;
    for (uint32_t i = 0; i < words; ++i)
        ring[i] = (struct record){0x03000000u + 4u * i, 1u};
    printf("ARMED STREAM-PASS timeout_ms=0 outputs=OFF framing=RLE-v2 synthetic=1\n");
    stdio_flush();
    for (uint32_t read = 0; read < words;) {
        uint n = words - read > CHUNK_RECORDS ? CHUNK_RECORDS : words - read;
        send_chunk(read, n);
        read += n;
    }
    printf("DONE seen=%" PRIu32 " sent=%" PRIu32 " records=%" PRIu32
           " overflow=0 stall=0 cancelled=0\n", words, commands_sent, words);
    stdio_flush();
}

static void command(const char *line) {
    uint32_t timeout_ms;
    char extra;
    if (!strcmp(line, "status")) {
        status();
    } else if (!strcmp(line, "arm-pass")) {
        if (armed) {
            printf("ERROR already armed\n");
        } else {
            gate_off();
            pio_sm_set_enabled(relay_pio, CS_SM, false);
            pio_sm_restart(relay_pio, CS_SM);
            pio_sm_exec(relay_pio, CS_SM, pio_encode_jmp(relay_offset));
            pio_sm_set_consecutive_pindirs(relay_pio, CS_SM, FLASH_CS, 1, false);
            pio_sm_set_enabled(relay_pio, CS_SM, true);
            sleep_us(10);
            gpio_set_oeover(FLASH_CS, GPIO_OVERRIDE_NORMAL);
            armed = gate = true;
            printf("ARMED CS-PASS GP7=open-drain-sink wait-for-host-CS-high\n");
        }
    } else if (!strcmp(line, "cancel")) {
        gate_off();
        armed = false;
        printf("CANCELLED CS-PASS output=OFF\n");
    } else if (sscanf(line, "stream-pass %" SCNu32 " %c", &timeout_ms, &extra) == 1 &&
               timeout_ms >= 1000u && timeout_ms <= 120000u) {
        stream(timeout_ms);
    } else if (sscanf(line, "usb-test %" SCNu32 " %c", &timeout_ms, &extra) == 1 &&
               timeout_ms > 0u && timeout_ms <= RING_RECORDS) {
        usb_test(timeout_ms);
    } else {
        printf("ERROR status; arm-pass; stream-pass TIMEOUT_MS; usb-test WORDS; cancel\n");
    }
    stdio_flush();
}

int main(void) {
    gpio_init(FLASH_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_input_enabled(FLASH_CS, false);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate_off();
    gpio_init(BC250_CS);
    gpio_disable_pulls(BC250_CS);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_oeover(BC250_CS, GPIO_OVERRIDE_LOW);
    gpio_init(BC250_MISO);
    gpio_disable_pulls(BC250_MISO);
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    for (uint pin = BC250_SCLK; pin <= BC250_MOSI; ++pin) {
        gpio_init(pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    vreg_set_voltage(VREG_VOLTAGE_1_20);
    sleep_ms(10);
    bool clock_ok = set_sys_clock_khz(200000, false);
    stdio_init_all();
    if (!clock_ok || clock_get_hz(clk_sys) != 200000000u) {
        for (;;) { printf("ERROR clock setup failed; output off\n"); sleep_ms(1000); }
    }

    pio_sm_claim(relay_pio, CS_SM);
    relay_offset = pio_add_program(relay_pio, &cs_open_drain_program);
    pio_gpio_init(relay_pio, BC250_CS);
    pio_gpio_init(relay_pio, FLASH_CS);
    gpio_disable_pulls(BC250_CS);
    gpio_disable_pulls(FLASH_CS);
    gpio_set_input_enabled(BC250_CS, true);
    gpio_set_input_enabled(FLASH_CS, false);
    gpio_set_outover(FLASH_CS, GPIO_OVERRIDE_LOW);
    gate_off();
    pio_sm_config c = cs_open_drain_program_get_default_config(relay_offset);
    sm_config_set_set_pins(&c, FLASH_CS, 1);
    sm_config_set_clkdiv_int_frac(&c, 1, 0);
    pio_sm_init(relay_pio, CS_SM, relay_offset, &c);
    pio_sm_set_pins_with_mask(relay_pio, CS_SM, 0, 1u << FLASH_CS);
    pio_sm_set_consecutive_pindirs(relay_pio, CS_SM, FLASH_CS, 1, false);
    pio_sm_set_enabled(relay_pio, CS_SM, true);
    gate_off();

    pio_sm_claim(stream_pio, STREAM_SM);
    stream_offset = pio_add_program(stream_pio, &address_hunt_program);
    for (uint pin = BC250_CS; pin <= BC250_MOSI; ++pin) {
        /* Input-only PIO1 reads pads without taking GP2 from relay PIO0. */
        gpio_disable_pulls(pin);
        gpio_set_input_enabled(pin, true);
        gpio_set_oeover(pin, GPIO_OVERRIDE_LOW);
    }
    multicore_launch_core1(stream_worker);
    char line[48];
    uint used = 0;
    bool line_overflow = false;
    for (;;) {
        int ch = getchar_timeout_us(0);
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[used] = 0;
            if (line_overflow) printf("ERROR line too long\n");
            else if (used) command(line);
            used = 0;
            line_overflow = false;
        } else if (ch >= 0 && used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        } else if (ch >= 0) {
            line_overflow = true;
        }
        sleep_us(50);
    }
}
