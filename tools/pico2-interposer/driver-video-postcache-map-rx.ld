bc250_postload_readback_success = 0xe0fc23;
bc250_postload_readback_failure = 0xe0fd49;
SECTIONS {
  .readback_hook 0xe0fc1e : { *(.readback_hook) }
  .map_cave 0xe17c54 : { *(.map_cave) }
  .map_addr_table 0xe17d98 : { *(.map_addr_table) }
  .map_value_table 0xe17fb8 : { *(.map_value_table) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
