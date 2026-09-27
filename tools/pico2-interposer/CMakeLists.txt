cmake_minimum_required(VERSION 3.20)
set(PICO_BOARD pico2 CACHE STRING "Target board")
if(NOT PICO_SDK_PATH AND DEFINED ENV{PICO_SDK_PATH})
  set(PICO_SDK_PATH "$ENV{PICO_SDK_PATH}")
endif()
if(NOT EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
  message(FATAL_ERROR "Set PICO_SDK_PATH to Pico SDK 2.3.1")
endif()
include("${PICO_SDK_PATH}/pico_sdk_init.cmake")
project(bc250_pico2 C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(bc250_passive main.c)
pico_generate_pio_header(bc250_passive ${CMAKE_CURRENT_LIST_DIR}/capture.pio)
pico_generate_pio_header(bc250_passive ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_passive PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_passive PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(bc250_passive pico_stdlib pico_multicore hardware_pio hardware_dma hardware_clocks)
pico_enable_stdio_usb(bc250_passive 1)
pico_enable_stdio_uart(bc250_passive 0)
pico_set_program_name(bc250_passive "BC250 passive SPI capture")
pico_set_program_version(bc250_passive "0.3")
pico_add_extra_outputs(bc250_passive)

# Durable input-only recovery image. The only change from passive v0.3 is
# Pico SDK's vendor USB reset interface, allowing picotool to enter BOOTSEL
# remotely for later RAM-only candidates after one manual installation.
add_executable(bc250_passive_usb_reset main.c)
pico_generate_pio_header(bc250_passive_usb_reset ${CMAKE_CURRENT_LIST_DIR}/capture.pio)
pico_generate_pio_header(bc250_passive_usb_reset ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_passive_usb_reset PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_passive_usb_reset PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
target_link_libraries(bc250_passive_usb_reset pico_stdlib pico_multicore hardware_pio hardware_dma hardware_clocks)
pico_enable_stdio_usb(bc250_passive_usb_reset 1)
pico_enable_stdio_uart(bc250_passive_usb_reset 0)
pico_set_program_name(bc250_passive_usb_reset "BC250 passive capture USB reset")
pico_set_program_version(bc250_passive_usb_reset "0.3-reset")
pico_add_extra_outputs(bc250_passive_usb_reset)

# Experimental reply-timing image for the isolated Pi SPI0 bench only. It
# never routes the BIOS chip or accepts a BC250 board-arm command.
add_executable(bc250_fast_bench fast_bench.c)
pico_set_binary_type(bc250_fast_bench no_flash)
pico_generate_pio_header(bc250_fast_bench ${CMAKE_CURRENT_LIST_DIR}/fast_reply.pio)
target_compile_options(bc250_fast_bench PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_fast_bench PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(bc250_fast_bench pico_stdlib hardware_pio hardware_dma hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_fast_bench 1)
pico_enable_stdio_uart(bc250_fast_bench 0)
pico_set_program_name(bc250_fast_bench "BC250 fast reply ISOLATED BENCH ONLY")
pico_set_program_version(bc250_fast_bench "0.1")
pico_add_extra_outputs(bc250_fast_bench)

# RAM-only combined PASS/PATCH selector/reply experiment. GP6 must remain
# disconnected from the BC250 and from any external flash on this bench.
add_executable(bc250_fast_select_bench fast_select_bench.c)
pico_set_binary_type(bc250_fast_select_bench no_flash)
pico_generate_pio_header(bc250_fast_select_bench ${CMAKE_CURRENT_LIST_DIR}/fast_select.pio)
pico_generate_pio_header(bc250_fast_select_bench ${CMAKE_CURRENT_LIST_DIR}/select_observe.pio)
pico_generate_pio_header(bc250_fast_select_bench ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_fast_select_bench PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_fast_select_bench PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(bc250_fast_select_bench pico_stdlib hardware_pio hardware_dma hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_fast_select_bench 1)
pico_enable_stdio_uart(bc250_fast_select_bench 0)
pico_set_program_name(bc250_fast_select_bench "BC250 combined select/reply ISOLATED BENCH ONLY")
pico_set_program_version(bc250_fast_select_bench "0.6")
pico_add_extra_outputs(bc250_fast_select_bench)

# Same isolated selector, but route simulated flash CS to otherwise unused GP7
# (Pico physical pin 10). This distinguishes a GP6-specific pad fault from a
# selector/timing problem without connecting either pin to the BC250.
add_executable(bc250_fast_select_gp7_bench fast_select_bench.c)
pico_set_binary_type(bc250_fast_select_gp7_bench no_flash)
pico_generate_pio_header(bc250_fast_select_gp7_bench ${CMAKE_CURRENT_LIST_DIR}/fast_select.pio)
pico_generate_pio_header(bc250_fast_select_gp7_bench ${CMAKE_CURRENT_LIST_DIR}/select_observe.pio)
pico_generate_pio_header(bc250_fast_select_gp7_bench ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_fast_select_gp7_bench PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_fast_select_gp7_bench PRIVATE
  BC250_FLASH_CS=7u
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(bc250_fast_select_gp7_bench pico_stdlib hardware_pio hardware_dma hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_fast_select_gp7_bench 1)
pico_enable_stdio_uart(bc250_fast_select_gp7_bench 0)
pico_set_program_name(bc250_fast_select_gp7_bench "BC250 GP7 select/reply ISOLATED BENCH ONLY")
pico_set_program_version(bc250_fast_select_gp7_bench "0.6-gp7")
pico_add_extra_outputs(bc250_fast_select_gp7_bench)

# Full-command guarded PATCH selector, isolated Pi SPI0 bench only. GP7 is
# unconnected; the 340 MHz RP2350 clock is an experimental overclock.
add_executable(bc250_fast_select_guard_bench fast_select_guard_bench.c)
pico_set_binary_type(bc250_fast_select_guard_bench no_flash)
pico_generate_pio_header(bc250_fast_select_guard_bench ${CMAKE_CURRENT_LIST_DIR}/fast_select_guard.pio)
pico_generate_pio_header(bc250_fast_select_guard_bench ${CMAKE_CURRENT_LIST_DIR}/select_observe.pio)
pico_generate_pio_header(bc250_fast_select_guard_bench ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_fast_select_guard_bench PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_fast_select_guard_bench PRIVATE
  BC250_FLASH_CS=7u
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
target_link_libraries(bc250_fast_select_guard_bench pico_stdlib hardware_pio hardware_dma hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_fast_select_guard_bench 1)
pico_enable_stdio_uart(bc250_fast_select_guard_bench 0)
pico_set_program_name(bc250_fast_select_guard_bench "BC250 guarded select/reply ISOLATED BENCH ONLY")
pico_set_program_version(bc250_fast_select_guard_bench "0.7-gp7")
pico_add_extra_outputs(bc250_fast_select_guard_bench)

# RAM-only, original-flash CS# pass-through diagnostic. GP7 only sinks CS#;
# the already-installed flash pull-up releases it to the board's 3.3 V rail.
add_executable(bc250_cs_pass cs_pass.c)
pico_set_binary_type(bc250_cs_pass no_flash)
pico_generate_pio_header(bc250_cs_pass ${CMAKE_CURRENT_LIST_DIR}/cs_open_drain.pio)
target_compile_options(bc250_cs_pass PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_cs_pass PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
target_link_libraries(bc250_cs_pass pico_stdlib hardware_pio hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_cs_pass 1)
pico_enable_stdio_uart(bc250_cs_pass 0)
pico_set_program_name(bc250_cs_pass "BC250 original-flash CS pass-through diagnostic")
pico_set_program_version(bc250_cs_pass "0.2-ram")
pico_add_extra_outputs(bc250_cs_pass)

# RAM-only CS pass-through plus filtered command/predecessor capture for
# deriving a real BC250 boot profile. Adds input-only GP3/GP4 wires; MISO
# remains an input. Build and model locally before any board connection.
add_executable(bc250_cs_pass_hunt cs_pass_hunt.c)
pico_set_binary_type(bc250_cs_pass_hunt no_flash)
pico_generate_pio_header(bc250_cs_pass_hunt ${CMAKE_CURRENT_LIST_DIR}/cs_open_drain.pio)
pico_generate_pio_header(bc250_cs_pass_hunt ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_cs_pass_hunt PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_cs_pass_hunt PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
target_link_libraries(bc250_cs_pass_hunt pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_cs_pass_hunt 1)
pico_enable_stdio_uart(bc250_cs_pass_hunt 0)
pico_set_program_name(bc250_cs_pass_hunt "BC250 CS pass-through address context hunt")
pico_set_program_version(bc250_cs_pass_hunt "0.1-ram")
pico_add_extra_outputs(bc250_cs_pass_hunt)

# RAM-only full-command stream with the same board-proven CS# relay. USB
# transfer and command capture are diagnostic only; no MISO/BIOS writes.
add_executable(bc250_cs_pass_stream cs_pass_stream.c)
pico_set_binary_type(bc250_cs_pass_stream no_flash)
pico_generate_pio_header(bc250_cs_pass_stream ${CMAKE_CURRENT_LIST_DIR}/cs_open_drain.pio)
pico_generate_pio_header(bc250_cs_pass_stream ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
target_compile_options(bc250_cs_pass_stream PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_cs_pass_stream PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
target_link_libraries(bc250_cs_pass_stream pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg)
pico_enable_stdio_usb(bc250_cs_pass_stream 1)
pico_enable_stdio_uart(bc250_cs_pass_stream 0)
pico_set_program_name(bc250_cs_pass_stream "BC250 CS pass-through RLE command stream")
pico_set_program_version(bc250_cs_pass_stream "0.2-ram")
pico_add_extra_outputs(bc250_cs_pass_stream)

set(BC250_SPARSE_PROFILE_HEADER "" CACHE FILEPATH
  "Verified physical sparse profile header under private output/; enables dry-run target")
if(BC250_SPARSE_PROFILE_HEADER)
  if(NOT EXISTS "${BC250_SPARSE_PROFILE_HEADER}")
    message(FATAL_ERROR "BC250_SPARSE_PROFILE_HEADER does not exist")
  endif()
  get_filename_component(BC250_SPARSE_PROFILE_DIR "${BC250_SPARSE_PROFILE_HEADER}" DIRECTORY)
  add_executable(bc250_sparse_dryrun sparse_dryrun.c)
  pico_set_binary_type(bc250_sparse_dryrun no_flash)
  pico_generate_pio_header(bc250_sparse_dryrun ${CMAKE_CURRENT_LIST_DIR}/sparse_select_od.pio)
  pico_generate_pio_header(bc250_sparse_dryrun ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  target_compile_options(bc250_sparse_dryrun PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_dryrun PRIVATE
    PICO_STDIO_ENABLE_CRLF_SUPPORT=0
    PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
    PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_dryrun PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_dryrun pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_dryrun 1)
  pico_enable_stdio_uart(bc250_sparse_dryrun 0)
  pico_set_program_name(bc250_sparse_dryrun "BC250 physical sparse profile dry run")
  pico_set_program_version(bc250_sparse_dryrun "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_dryrun)

  add_executable(bc250_sparse_active sparse_active.c)
  pico_set_binary_type(bc250_sparse_active no_flash)
  pico_generate_pio_header(bc250_sparse_active ${CMAKE_CURRENT_LIST_DIR}/sparse_select_early.pio)
  pico_generate_pio_header(bc250_sparse_active ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  target_compile_options(bc250_sparse_active PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_active PRIVATE
    BC250_EARLY_MISO=1
    BC250_FAST_MISO_PAD=1
    PICO_STDIO_ENABLE_CRLF_SUPPORT=0
    PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
    PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_active PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_active pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg hardware_watchdog)
  pico_enable_stdio_usb(bc250_sparse_active 1)
  pico_enable_stdio_uart(bc250_sparse_active 0)
  pico_set_program_name(bc250_sparse_active "BC250 sparse guarded PASS/PATCH candidate")
  pico_set_program_version(bc250_sparse_active "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_active)

  add_executable(bc250_sparse_probe sparse_active.c)
  pico_set_binary_type(bc250_sparse_probe no_flash)
  pico_generate_pio_header(bc250_sparse_probe ${CMAKE_CURRENT_LIST_DIR}/sparse_select_od.pio)
  pico_generate_pio_header(bc250_sparse_probe ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  pico_generate_pio_header(bc250_sparse_probe ${CMAKE_CURRENT_LIST_DIR}/miso_probe.pio)
  target_compile_options(bc250_sparse_probe PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_probe PRIVATE
    BC250_FLASH_CS=7
    BC250_MISO_PROBE=1
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_probe PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_probe pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_probe 1)
  pico_enable_stdio_uart(bc250_sparse_probe 0)
  pico_set_program_name(bc250_sparse_probe "BC250 sparse guarded MISO probe")
  pico_set_program_version(bc250_sparse_probe "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_probe)

  add_executable(bc250_sparse_early_probe sparse_active.c)
  pico_set_binary_type(bc250_sparse_early_probe no_flash)
  pico_generate_pio_header(bc250_sparse_early_probe ${CMAKE_CURRENT_LIST_DIR}/sparse_select_early.pio)
  pico_generate_pio_header(bc250_sparse_early_probe ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  pico_generate_pio_header(bc250_sparse_early_probe ${CMAKE_CURRENT_LIST_DIR}/miso_probe.pio)
  target_compile_options(bc250_sparse_early_probe PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_early_probe PRIVATE
    BC250_FLASH_CS=7
    BC250_MISO_PROBE=1
    BC250_EARLY_MISO=1
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_early_probe PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_early_probe pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_early_probe 1)
  pico_enable_stdio_uart(bc250_sparse_early_probe 0)
  pico_set_program_name(bc250_sparse_early_probe "BC250 early MISO guarded control")
  pico_set_program_version(bc250_sparse_early_probe "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_early_probe)

  add_executable(bc250_sparse_fast_early_probe sparse_active.c)
  pico_set_binary_type(bc250_sparse_fast_early_probe no_flash)
  pico_generate_pio_header(bc250_sparse_fast_early_probe ${CMAKE_CURRENT_LIST_DIR}/sparse_select_early.pio)
  pico_generate_pio_header(bc250_sparse_fast_early_probe ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  pico_generate_pio_header(bc250_sparse_fast_early_probe ${CMAKE_CURRENT_LIST_DIR}/miso_probe.pio)
  target_compile_options(bc250_sparse_fast_early_probe PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_fast_early_probe PRIVATE
    BC250_FLASH_CS=7
    BC250_MISO_PROBE=1
    BC250_EARLY_MISO=1
    BC250_FAST_MISO_PAD=1
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_fast_early_probe PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_fast_early_probe pico_stdlib pico_multicore hardware_pio hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_fast_early_probe 1)
  pico_enable_stdio_uart(bc250_sparse_fast_early_probe 0)
  pico_set_program_name(bc250_sparse_fast_early_probe "BC250 fast-pad early MISO control")
  pico_set_program_version(bc250_sparse_fast_early_probe "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_fast_early_probe)

  add_executable(bc250_sparse_snapshot_probe sparse_active.c)
  pico_set_binary_type(bc250_sparse_snapshot_probe no_flash)
  pico_generate_pio_header(bc250_sparse_snapshot_probe ${CMAKE_CURRENT_LIST_DIR}/sparse_select_early.pio)
  pico_generate_pio_header(bc250_sparse_snapshot_probe ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  pico_generate_pio_header(bc250_sparse_snapshot_probe ${CMAKE_CURRENT_LIST_DIR}/miso_probe.pio)
  pico_generate_pio_header(bc250_sparse_snapshot_probe ${CMAKE_CURRENT_LIST_DIR}/bus_snapshot.pio)
  target_compile_options(bc250_sparse_snapshot_probe PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_snapshot_probe PRIVATE
    BC250_FLASH_CS=7
    BC250_MISO_PROBE=1
    BC250_EARLY_MISO=1
    BC250_FAST_MISO_PAD=1
    BC250_BUS_SNAPSHOT=1
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_snapshot_probe PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_snapshot_probe pico_stdlib pico_multicore hardware_pio hardware_dma hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_snapshot_probe 1)
  pico_enable_stdio_uart(bc250_sparse_snapshot_probe 0)
  pico_set_program_name(bc250_sparse_snapshot_probe "BC250 six-wire SPI snapshot")
  pico_set_program_version(bc250_sparse_snapshot_probe "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_snapshot_probe)

  add_executable(bc250_sparse_release_snapshot sparse_active.c)
  pico_set_binary_type(bc250_sparse_release_snapshot no_flash)
  pico_generate_pio_header(bc250_sparse_release_snapshot ${CMAKE_CURRENT_LIST_DIR}/sparse_select_early.pio)
  pico_generate_pio_header(bc250_sparse_release_snapshot ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  pico_generate_pio_header(bc250_sparse_release_snapshot ${CMAKE_CURRENT_LIST_DIR}/miso_probe.pio)
  pico_generate_pio_header(bc250_sparse_release_snapshot ${CMAKE_CURRENT_LIST_DIR}/bus_release_snapshot.pio)
  target_compile_options(bc250_sparse_release_snapshot PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_release_snapshot PRIVATE
    BC250_FLASH_CS=7
    BC250_MISO_PROBE=1
    BC250_EARLY_MISO=1
    BC250_FAST_MISO_PAD=1
    BC250_BUS_SNAPSHOT=1
    BC250_RELEASE_SNAPSHOT=1
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_release_snapshot PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_release_snapshot pico_stdlib pico_multicore hardware_pio hardware_dma hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_release_snapshot 1)
  pico_enable_stdio_uart(bc250_sparse_release_snapshot 0)
  pico_set_program_name(bc250_sparse_release_snapshot "BC250 flash-CS release snapshot")
  pico_set_program_version(bc250_sparse_release_snapshot "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_release_snapshot)

  add_executable(bc250_sparse_late_snapshot sparse_active.c)
  pico_set_binary_type(bc250_sparse_late_snapshot no_flash)
  pico_generate_pio_header(bc250_sparse_late_snapshot ${CMAKE_CURRENT_LIST_DIR}/sparse_select_early.pio)
  pico_generate_pio_header(bc250_sparse_late_snapshot ${CMAKE_CURRENT_LIST_DIR}/address_hunt.pio)
  pico_generate_pio_header(bc250_sparse_late_snapshot ${CMAKE_CURRENT_LIST_DIR}/miso_probe.pio)
  pico_generate_pio_header(bc250_sparse_late_snapshot ${CMAKE_CURRENT_LIST_DIR}/bus_snapshot.pio)
  target_compile_options(bc250_sparse_late_snapshot PRIVATE -Wall -Wextra -Werror)
  target_compile_definitions(bc250_sparse_late_snapshot PRIVATE
    BC250_FLASH_CS=7
    BC250_MISO_PROBE=1
    BC250_EARLY_MISO=1
    BC250_FAST_MISO_PAD=1
    BC250_BUS_SNAPSHOT=1
    BC250_SNAPSHOT_COMMAND=0x038fef4c
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1)
  target_include_directories(bc250_sparse_late_snapshot PRIVATE "${BC250_SPARSE_PROFILE_DIR}")
  target_link_libraries(bc250_sparse_late_snapshot pico_stdlib pico_multicore hardware_pio hardware_dma hardware_clocks hardware_vreg)
  pico_enable_stdio_usb(bc250_sparse_late_snapshot 1)
  pico_enable_stdio_uart(bc250_sparse_late_snapshot 0)
  pico_set_program_name(bc250_sparse_late_snapshot "BC250 late VCN SPI snapshot")
  pico_set_program_version(bc250_sparse_late_snapshot "0.1-ram")
  pico_add_extra_outputs(bc250_sparse_late_snapshot)
endif()

option(BC250_BUILD_LEGACY_BENCH "Build the development-only reply experiment" OFF)
if(BC250_BUILD_LEGACY_BENCH)
add_executable(bc250_bench_only bench.c)
pico_generate_pio_header(bc250_bench_only ${CMAKE_CURRENT_LIST_DIR}/reply.pio)
target_compile_options(bc250_bench_only PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_bench_only PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(bc250_bench_only pico_stdlib hardware_pio hardware_dma)
pico_enable_stdio_usb(bc250_bench_only 1)
pico_enable_stdio_uart(bc250_bench_only 0)
pico_set_program_name(bc250_bench_only "BC250 ISOLATED BENCH ONLY")
pico_set_program_version(bc250_bench_only "0.1")
pico_add_extra_outputs(bc250_bench_only)
endif()

# Strict-script router candidate. Generated profiles contain public/signed
# words only. The checked-in default is an isolated demo, not a BC250 profile.
set(BC250_ROUTER_PROFILE_HEADER "${CMAKE_CURRENT_LIST_DIR}/router_demo.h" CACHE FILEPATH "Generated isolated router profile")
configure_file("${BC250_ROUTER_PROFILE_HEADER}" "${CMAKE_CURRENT_BINARY_DIR}/router_profile.h" COPYONLY)
add_executable(bc250_interceptor router.c)
target_include_directories(bc250_interceptor PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
pico_generate_pio_header(bc250_interceptor ${CMAKE_CURRENT_LIST_DIR}/router.pio)
pico_generate_pio_header(bc250_interceptor ${CMAKE_CURRENT_LIST_DIR}/router_count.pio)
target_compile_options(bc250_interceptor PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(bc250_interceptor PRIVATE
  PICO_STDIO_ENABLE_CRLF_SUPPORT=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(bc250_interceptor pico_stdlib pico_multicore hardware_pio hardware_clocks)
pico_enable_stdio_usb(bc250_interceptor 1)
pico_enable_stdio_uart(bc250_interceptor 0)
pico_set_program_name(bc250_interceptor "BC250 interceptor ISOLATED PROFILE")
pico_set_program_version(bc250_interceptor "0.4")
pico_add_extra_outputs(bc250_interceptor)
