/* Pi-only SPI0 master traffic for a three-wire PIO command-capture bench test.
 * Never connect this SPI0 output harness to the BC250 during this test.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/spi/spidev.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int spi_read_command(int fd, uint32_t address, uint32_t hz)
{
    uint8_t tx[8] = { 0x03, (uint8_t)(address >> 16),
                      (uint8_t)(address >> 8), (uint8_t)address, 0, 0, 0, 0 };
    struct spi_ioc_transfer transfer = {
        .tx_buf = (uintptr_t)tx,
        .len = sizeof(tx),
        .speed_hz = hz,
        .bits_per_word = 8,
    };
    return ioctl(fd, SPI_IOC_MESSAGE(1), &transfer) == (int)sizeof(tx) ? 0 : -1;
}

static int send_region(int fd, uint32_t start, uint32_t end,
                       uint32_t hz, size_t *sent)
{
    for (uint32_t address = start; address < end; address += 4) {
        if (spi_read_command(fd, address, hz))
            return -1;
        ++*sent;
    }
    return 0;
}

int main(int argc, char **argv)
{
    uint32_t hz = 1000000;
    uint8_t mode = SPI_MODE_0, bits = 8;
    const char *device = "/dev/spidev0.0";
    size_t sent = 0;
    int fd;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--hz") && i + 1 < argc) {
            char *end = NULL;
            unsigned long value = strtoul(argv[++i], &end, 0);
            if (!end || *end || !value || value > UINT32_MAX) goto usage;
            hz = (uint32_t)value;
        } else if (!strcmp(argv[i], "--mode3")) {
            mode = SPI_MODE_3;
        } else if (!strcmp(argv[i], "--device") && i + 1 < argc) {
            device = argv[++i];
        } else {
            goto usage;
        }
    }
    fd = open(device, O_RDWR);
    if (fd < 0) {
        perror("open SPI0 device");
        return 1;
    }
    if (ioctl(fd, SPI_IOC_WR_MODE, &mode) ||
        ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) ||
        ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &hz)) {
        perror("configure SPI0");
        close(fd);
        return 1;
    }
    for (int pass = 0; pass < 2; ++pass) {
        if (send_region(fd, 0x9dae00, 0x9db8d0, hz, &sent) ||
            send_region(fd, 0x9dbc00, 0x9dc040, hz, &sent)) {
            perror("send key-database read sequence");
            close(fd);
            return 1;
        }
    }
    /* Extra commands let the finite-length PIO capture finish after losses. */
    if (send_region(fd, 0x10000, 0x14000, hz, &sent)) {
        perror("send filler sequence");
        close(fd);
        return 1;
    }
    if (close(fd)) {
        perror("close SPI0 device");
        return 1;
    }
    fprintf(stderr, "sent %zu SPI0 read commands at requested %" PRIu32
                    " Hz, mode %u; no BC250 attached\n",
            sent, hz, mode == SPI_MODE_3 ? 3u : 0u);
    return 0;
usage:
    fprintf(stderr, "Usage: %s [--hz 1000000] [--mode3] "
                    "[--device /dev/spidev0.0]\n", argv[0]);
    return 2;
}
