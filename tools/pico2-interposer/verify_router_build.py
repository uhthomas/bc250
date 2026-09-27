#!/usr/bin/env python3
"""Check the linked UF2 source ELF against the signed-word replay and PIO.

Checks actual linked data, SRAM placement and absence of flash calls in the
fault monitor. No hardware access; no claim about physical execution timing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
from router_model import NativePolicy, assemble, encode
from prepare_router_profile import compress


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--pioasm', required=True)
    p.add_argument('--tool-prefix', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    plan = json.loads(args.profile.read_text())
    digest = hashlib.sha256(json.dumps(plan['rows'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    require(plan['schema'] == 3 and digest == plan['row_sha256'], 'profile schema/hash mismatch')
    programs = assemble(args.pioasm)
    expected = encode([(r['command'], r['patch'], r['word']) for r in plan['rows']], programs[0]['publicLabels'])
    runs, payload = compress(plan['rows'])
    run_words = [x for r in runs for x in (r['command'], r['count'], r['payload'])]
    wanted_runs = struct.pack(f'<{len(run_words)}I', *run_words)
    wanted_payload = struct.pack(f'<{max(1,len(payload))}I', *(payload or [0]))
    symbols = {}
    for line in subprocess.check_output([args.tool_prefix+'nm', '-S', str(args.elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4:
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
    run_address, run_size = symbols['router_runs']
    payload_address, payload_size = symbols['router_payload']
    monitor_address, monitor_size = symbols['monitor']
    for address, size in ((run_address, run_size), (payload_address, payload_size), (monitor_address, monitor_size)):
        require(0x20000000 <= address < address+size <= 0x20080000, 'critical item is not in main SRAM')
    sections = subprocess.check_output([args.tool_prefix+'objdump', '-h', str(args.elf)], text=True)
    elf = args.elf.read_bytes()
    def extract(address, size):
        for match in re.finditer(r'^\s*\d+\s+(\.\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)', sections, re.M):
            section_size, base, file_offset = (int(x, 16) for x in match.groups()[1:])
            if base <= address < address+size <= base+section_size:
                offset = file_offset+address-base
                return elf[offset:offset+size]
        raise ValueError(f'no file section contains {address:x} size {size:x}')
    actual_runs = extract(run_address, run_size)
    actual_payload = extract(payload_address, payload_size)
    require(actual_runs == wanted_runs, 'linked command runs differ from signed replay')
    require(actual_payload == wanted_payload, 'linked SRAM replies differ from signed replay')
    linked_runs = [dict(command=c,count=n,payload=p) for c,n,p in struct.iter_unpack('<III',actual_runs)]
    linked_payload = list(struct.unpack(f'<{payload_size//4}I',actual_payload))
    native = NativePolicy()
    try:
        expanded = native.expand(linked_runs,linked_payload,programs[0]['publicLabels'])
        require(expanded == expected, 'native expansion of linked data differs from modeled script')
    finally:
        native.close()
    for program in programs:
        address, size = symbols[program['name']+'_program_instructions']
        instructions = [int(i['hex'], 16) for i in program['instructions']]
        require(extract(address, size) == struct.pack(f'<{len(instructions)}H', *instructions),
                f'linked {program["name"]} PIO differs from modeled instructions')
    disassembly = subprocess.check_output([args.tool_prefix+'objdump', '-d',
                                           '--disassemble=monitor', str(args.elf)], text=True)
    # The monitor is an infinite loop with all fault paths inlined. Any call,
    # indirect jump, or explicit flash address needs manual reassessment.
    require(not re.search(r'\b(jalr?|call|tail|jr|ret)\b', disassembly), 'monitor contains a call/indirect jump')
    require(not re.search(r'#\s+10[0-9a-f]{6}\b', disassembly), 'monitor refers to XIP flash')
    report = dict(profile=plan['name'], rows=len(plan['rows']),
                  unique_changed_words=plan['unique_changed_words'],
                  linked_compressed_sha256=hashlib.sha256(actual_runs+actual_payload).hexdigest(),
                  expanded_script_sha256=hashlib.sha256(struct.pack(f'<{len(expanded)}I',*expanded)).hexdigest(),
                  elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),
                  run_table_sram_address=hex(run_address), run_count=len(runs), run_table_bytes=run_size,
                  payload_sram_address=hex(payload_address), payload_bytes=payload_size,
                  compressed_bytes=run_size+payload_size, expanded_bytes=len(expanded)*4,
                  fault_monitor_sram_address=hex(monitor_address), fault_monitor_bytes=monitor_size,
                  fault_monitor_has_flash_calls=False, linked_pio_programs_checked=len(programs),
                  physical_test=False, board_profile=False)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
