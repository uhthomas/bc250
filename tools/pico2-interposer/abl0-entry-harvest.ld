SECTIONS {
    . = 0x54070;
    .text.abl0_first : { *(.text.abl0_first) }
    . = 0x540a4;
    .text.abl0_second : { *(.text.abl0_second) }
    . = 0x540f0;
    .text.abl0_third : { *(.text.abl0_third) }
    /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
