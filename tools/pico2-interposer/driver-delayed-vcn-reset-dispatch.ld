bc250_postcache_map_failure = 0xe17cd4;
bc250_postcache_map_resume = 0xe17caa;
SECTIONS {
  .map_branch 0xe17ca6 : { *(.map_branch) }
  .dispatch_cave 0xe17d98 : { *(.dispatch_cave) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
