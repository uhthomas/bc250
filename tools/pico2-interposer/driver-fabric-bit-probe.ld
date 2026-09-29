bc250_postload_readback_failure = 0xe0fd49;
SECTIONS {
  .map_cave 0xe17c54 : { *(.map_cave) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
