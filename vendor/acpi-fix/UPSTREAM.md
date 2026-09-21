Source: https://github.com/e-tho/bc250-acpi-fix

Revision: 5fafc82bda4230acc423a359bc07b86188160942

The DSL sources, Makefile and MIT LICENSE are copied without modification.
The tables support the stock 6-core/12-thread and unlocked 8-core/16-thread
topologies. Compile them in the build stage and include them in the early
initramfs; do not also inject ACPI fixes through the BIOS.
