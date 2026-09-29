bc250_original_reset_resume = 0xe0fc1e;
bc250_postload_readback_failure = 0xe0fd49;
SECTIONS {
  .pre_reset_hook 0xe0fc16 : { *(.pre_reset_hook) }
  .map_cave 0xe17c54 : { *(.map_cave) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
