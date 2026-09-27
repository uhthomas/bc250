/* ISOLATED PI-TO-PICO BENCH ONLY. Not an active BC250 interposer firmware.
 * Tests preloaded SRAM replies at <= 1 MHz with 64-clock, mode-0 transactions.
 * GP6 stays input. No original flash is connected in this experiment.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/regs/pio.h"
#include "reply.pio.h"
#include "pins.h"

#define MAX_REPLIES 32768u
static uint32_t expected[MAX_REPLIES], replies[MAX_REPLIES], observed[MAX_REPLIES];
static uint loaded;
static PIO const pio = pio0;
static uint reply_offset, release_offset;
static int tx_dma, rx_dma;
enum { REPLY_SM=0, RELEASE_SM=3 };

static uint32_t crc_update(uint32_t crc, const void *ptr, size_t n) {
    const uint8_t *p=ptr;
    while (n--) {
        crc ^= *p++;
        for (uint i=0; i<8; ++i) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1u)));
    }
    return crc;
}

static void stop(void) {
    gpio_set_oeover(BC250_MISO, GPIO_OVERRIDE_LOW);
    pio_set_sm_mask_enabled(pio, (1u<<REPLY_SM)|(1u<<RELEASE_SM), false);
    dma_channel_abort(tx_dma);
    dma_channel_abort(rx_dma);
    pio_sm_clear_fifos(pio, REPLY_SM);
    pio_sm_clear_fifos(pio, RELEASE_SM);
}

static bool read_word(uint32_t *word, absolute_time_t deadline) {
    uint8_t *p=(uint8_t *)word;
    for (uint i=0; i<4;) {
        if (time_reached(deadline)) return false;
        int c=getchar_timeout_us(1000);
        if (c>=0) p[i++]=(uint8_t)c;
    }
    return true;
}

static void load(uint n, uint32_t wanted_crc) {
    stop(); loaded=0;
    printf("LOAD %u\n", n); stdio_flush();
    absolute_time_t deadline=make_timeout_time_ms(30000);
    uint32_t crc=UINT32_MAX;
    bool valid=true;
    for (uint i=0; i<n; ++i) {
        if (!read_word(&expected[i],deadline) || !read_word(&replies[i],deadline)) {
            printf("ERROR upload timeout; reset Pico before another upload\n"); return;
        }
        crc=crc_update(crc,&expected[i],4);
        crc=crc_update(crc,&replies[i],4);
        if (expected[i]>>24 != 3) valid=false;
    }
    if (~crc != wanted_crc || !valid) { printf("ERROR upload CRC/opcode\n"); return; }
    loaded=n;
    printf("LOADED %u crc=%08" PRIx32 "\n", loaded, ~crc);
}

static void run(uint timeout_ms) {
    if (!loaded) { printf("ERROR load a read script first\n"); return; }
    uint n=loaded; loaded=0;
    pio_sm_config c=bench_reply_program_get_default_config(reply_offset);
    sm_config_set_in_pins(&c,BC250_MOSI);
    sm_config_set_in_shift(&c,false,true,32);
    sm_config_set_out_pins(&c,BC250_MISO,1);
    sm_config_set_out_shift(&c,false,false,32);
    sm_config_set_set_pins(&c,BC250_MISO,1);
    pio_sm_init(pio,REPLY_SM,reply_offset,&c);
    c=bench_release_program_get_default_config(release_offset);
    sm_config_set_set_pins(&c,BC250_MISO,1);
    pio_sm_init(pio,RELEASE_SM,release_offset,&c);
    pio_sm_set_consecutive_pindirs(pio,REPLY_SM,BC250_MISO,1,false);
    pio_sm_set_consecutive_pindirs(pio,RELEASE_SM,BC250_MISO,1,false);
    for (uint pin=BC250_CS; pin<=BC250_MISO; ++pin) {
        pio_gpio_init(pio,pin);
        gpio_disable_pulls(pin);
        gpio_set_oeover(pin,GPIO_OVERRIDE_LOW);
    }
    dma_channel_config t=dma_channel_get_default_config(tx_dma);
    channel_config_set_transfer_data_size(&t,DMA_SIZE_32);
    channel_config_set_read_increment(&t,true);
    channel_config_set_write_increment(&t,false);
    channel_config_set_dreq(&t,pio_get_dreq(pio,REPLY_SM,true));
    dma_channel_configure(tx_dma,&t,&pio->txf[REPLY_SM],replies,n,false);
    dma_channel_config r=dma_channel_get_default_config(rx_dma);
    channel_config_set_transfer_data_size(&r,DMA_SIZE_32);
    channel_config_set_read_increment(&r,false);
    channel_config_set_write_increment(&r,true);
    channel_config_set_dreq(&r,pio_get_dreq(pio,REPLY_SM,false));
    dma_channel_configure(rx_dma,&r,observed,&pio->rxf[REPLY_SM],n,false);
    uint32_t stall=1u<<(PIO_FDEBUG_RXSTALL_LSB+REPLY_SM);
    pio->fdebug=stall;
    dma_start_channel_mask((1u<<tx_dma)|(1u<<rx_dma));
    gpio_set_oeover(BC250_MISO,GPIO_OVERRIDE_NORMAL);
    pio_enable_sm_mask_in_sync(pio,(1u<<REPLY_SM)|(1u<<RELEASE_SM));
    printf("ARMED ISOLATED-BENCH replies=%u mode=0 max_hz=1000000\n",n);
    stdio_flush();
    absolute_time_t deadline=make_timeout_time_ms(timeout_ms);
    bool failed=false;
    while (dma_channel_is_busy(rx_dma) || !gpio_get(BC250_CS)) {
        int c=getchar_timeout_us(0);
        if (c=='x' || time_reached(deadline)) { failed=true; break; }
        tight_loop_contents();
    }
    uint flags=(pio->fdebug&stall) ? 1u : 0u;
    stop();
    if (failed) { printf("ERROR bench aborted/timeout; MISO disabled\n"); return; }
    uint mismatches=0;
    for (uint i=0; i<n; ++i) mismatches+=expected[i]!=observed[i];
    printf("RESULT %u %u %u %08" PRIx32 "\n",n,mismatches,flags,
           ~crc_update(UINT32_MAX,observed,n*4));
    fwrite(observed,4,n,stdout);
    printf("\nDONE\n"); stdio_flush();
}

static void command(char *line) {
    uint n, timeout, crc;
    char extra;
    if (!strcmp(line,"status")) {
        printf("BC250-PICO2-BENCH v1 outputs=OFF-UNTIL-RUN GP6=INPUT loaded=%u\n",loaded);
    } else if (sscanf(line,"load %u %x %c",&n,&crc,&extra)==2 && n && n<=MAX_REPLIES) {
        load(n,crc);
    } else if (sscanf(line,"bench-isolated %u %c",&timeout,&extra)==1 && timeout>=100 && timeout<=120000) {
        run(timeout);
    } else printf("ERROR status; load N CRC32; bench-isolated TIMEOUT_MS\n");
}

int main(void) {
    for (uint pin=BC250_CS; pin<=BC250_FLASH_CS; ++pin) {
        gpio_init(pin); gpio_disable_pulls(pin);
        gpio_set_oeover(pin,GPIO_OVERRIDE_LOW);
    }
    stdio_init_all();
    pio_sm_claim(pio,REPLY_SM); pio_sm_claim(pio,RELEASE_SM);
    reply_offset=pio_add_program(pio,&bench_reply_program);
    release_offset=pio_add_program(pio,&bench_release_program);
    tx_dma=dma_claim_unused_channel(true); rx_dma=dma_claim_unused_channel(true);
    char line[96]; uint used=0; bool overflow=false;
    for (;;) {
        int c=getchar_timeout_us(10000);
        if (c<0 || c=='\r') continue;
        if (c=='\n') {
            line[used]=0;
            if (overflow) printf("ERROR line too long\n");
            else if (used) command(line);
            used=0; overflow=false;
        } else if (used<sizeof(line)-1) line[used++]=(char)c;
        else overflow=true;
    }
}
