bc250_original_initializer = 0xe09891;
bc250_zero_helper = 0xe01729;
bc250_original_region_alloc = 0xe121ed;
bc250_original_rsmu_client_init = 0xe0514d;
bc250_video_svc_success = 0xe0e9d9;
bc250_video_svc_failure = 0xe0e9ef;
bc250_postload_success = 0xe0fc23;
bc250_postload_failure = 0xe0fd49;
bc250_postload_readback_success = 0xe0fc23;
bc250_postload_readback_failure = 0xe0fd49;
SECTIONS {
  .hook 0xe09622 : { *(.hook) }
  .map_cave 0xe17c54 : { *(.map_cave) }
  .gasket_readback_cave 0xe17c80 : { *(.gasket_readback_cave) }
  .cave 0xe17d00 : { *(.cave) }
  .tmr_hook 0xe0e85e : { *(.tmr_hook) }
  .tmr_cave 0xe17d40 : { *(.tmr_cave) }
  .svc_hook 0xe0e9c4 : { *(.svc_hook) }
  .svc_cave 0xe17d80 : { *(.svc_cave) }
  .map_addr_table 0xe17d98 : { *(.map_addr_table) }
  .postload_hook 0xe0fc1e : { *(.postload_hook) }
  .postload_cave 0xe17dc0 : { *(.postload_cave) }
  .readback_hook 0xe0fc1e : { *(.readback_hook) }
  .readback_cave 0xe17e00 : { *(.readback_cave) }
  .gasket_cave 0xe17e00 : { *(.gasket_cave) }
  .map_value_table 0xe17fb8 : { *(.map_value_table) }
  .program_table 0xe19010 : { *(.program_table) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
