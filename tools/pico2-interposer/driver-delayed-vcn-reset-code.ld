/* Keep the proven cache address/value tables in the executable image.
 * The format-0x100 driver copies through 0xe1a000, but the earlier data-area
 * table at 0xe19010 did not complete powered LOAD_IP_FW on the BC250.
 * 0xe00200..0xe007ff is zero in the pinned signed driver's code image.
 */
bc250_postcache_map_failure = 0xe17cd4;
bc250_postcache_map_resume = 0xe17caa;
SECTIONS {
  .dispatch_cave 0xe00200 : { *(.dispatch_cave) }
  .map_branch 0xe17ca6 : { *(.map_branch) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
