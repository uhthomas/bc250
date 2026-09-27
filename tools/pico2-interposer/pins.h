#ifndef BC250_PINS_H
#define BC250_PINS_H
/* Pico 2 physical pins 4, 5, 6, 7; ground at physical pin 8. */
#define BC250_CS 2u
#define BC250_SCLK 3u
#define BC250_MOSI 4u
#define BC250_MISO 5u
/* Legacy experimental flash CS# output on GP6 / physical pin 9. The GP7
 * isolated bench overrides this macro with 7u / physical pin 10; any later
 * board interposer must be built explicitly for GP7 after qualification. */
#ifndef BC250_FLASH_CS
#define BC250_FLASH_CS 6u
#endif
#define BC250_BUS_MASK (0x1fu << BC250_CS)
#endif
