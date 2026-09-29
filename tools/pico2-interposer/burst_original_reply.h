#ifndef BC250_BURST_ORIGINAL_REPLY_H
#define BC250_BURST_ORIGINAL_REPLY_H

/* Exact 64 bytes at SPI 0xae0140 in working control ROM SHA256
 * f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183.
 * Data is MSB-first for PIO OUT with left-shifting OSR.
 */
#define BURST_TRIGGER_COMMAND 0x03ae0100u
#define BURST_TARGET_COMMAND 0x03ae0140u
#define BURST_WORD_COUNT 16u
static const uint32_t burst_original_words[BURST_WORD_COUNT] = {
    0x0c753da5u, 0xf49ffff6u, 0x98279b4au, 0xb7fe639cu,
    0x198727b3u, 0xcdf93e61u, 0xb953cd0du, 0xdd88f92fu,
    0xcaced044u, 0x894ee8ebu, 0xe29c6711u, 0x4c5113d6u,
    0x7e1ef2b9u, 0x9e54ecd3u, 0xb5ff3d79u, 0x85bc2746u,
};

#endif
