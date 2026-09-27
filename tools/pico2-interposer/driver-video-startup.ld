bc250_original_initializer = 0xe09891;
bc250_zero_helper = 0xe01729;
bc250_original_region_alloc = 0xe121ed;
SECTIONS {
  .hook 0xe09622 : { *(.hook) }
  .cave 0xe17d00 : { *(.cave) }
  .tmr_hook 0xe0e85e : { *(.tmr_hook) }
  .tmr_cave 0xe17d40 : { *(.tmr_cave) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
