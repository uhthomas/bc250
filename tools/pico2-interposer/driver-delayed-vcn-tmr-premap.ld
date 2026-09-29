bc250_postcache_map_failure = 0xe17cd4;
bc250_postcache_map_loop_setup = 0xe17c92;
bc250_tmr_read_map = 0xe06900;
SECTIONS {
  .dispatch_cave 0xe00200 : { *(.dispatch_cave) }
  .premap_branch 0xe17c8e : { *(.premap_branch) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
