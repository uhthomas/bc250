#!/usr/bin/env python3
"""Build a RAM-only signer, VCN-key and PSP-driver startup trial.

The original EEPROM must remain untouched. The input key is private and the
generated 16-MiB view is deliberately invalid as a standalone BIOS image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

CLEAN_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
TYPE51_PROFILE_SHA = '47c18374c8f5889ca760a90ae96bb000804a73c266a11d6196d17ab8fc29545f'
KDB_MODULUS = 0x9db140
TOS, TOS_LEN = 0x8eac00, 0x14350
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
HOOK, CAVE = DRIVER + 0x9622, DRIVER + 0x17d00
TMR_HOOK, TMR_CAVE = DRIVER + 0xe85e, DRIVER + 0x17d40
SVC_HOOK, SVC_CAVE = DRIVER + 0xe9c4, DRIVER + 0x17d80
POSTLOAD_HOOK, POSTLOAD_CAVE = DRIVER + 0xfc1e, DRIVER + 0x17dc0
READBACK_HOOK, READBACK_CAVE = DRIVER + 0xfc1e, DRIVER + 0x17e00
PRE_RESET_HOOK = DRIVER + 0xfc16
GASKET_CAVE = DRIVER + 0x17e00
GASKET_READBACK_CAVE = DRIVER + 0x17c80
MAP_CAVE = DRIVER + 0x17c54
PROGRAM_TABLE = DRIVER + 0x19010
MAP_ADDR_TABLE = DRIVER + 0x17d98
MAP_VALUE_TABLE = DRIVER + 0x17fb8
MAP_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-postcache-map'
MAP_MODES = (MAP_MODE,) + tuple(f'{MAP_MODE}-prefix{count:02d}'
                                 for count in (1, 2, 4, 8, 12, 16)) + (f'{MAP_MODE}-prefix01-inline',)
MAP_RX_MODE = f'{MAP_MODE}-rx'
SKIP_NATIVE_VIDEO_CONTROL_MODE = f'{MAP_RX_MODE}-skip-1f820'
PRE_RESET_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-reset'
PRE_UVD_RESET_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-uvd-reset'
PRE_VCPU_CNTL_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-vcpu-cntl'
PRE_LMI_CTRL2_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-lmi-ctrl2'
PRE_CGC_GATE_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-cgc-gate'
PRE_CGC_CTRL_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-cgc-ctrl'
PRE_LMI_VM_CTRL_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-lmi-vm-ctrl'
PRE_UVD_HARVEST_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-uvd-harvest'
PRE_UVD_HARVEST_CLEAR_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-uvd-harvest-clear'
PRE_EARLY_UVD_HARVEST_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-early-uvd-harvest'
PRE_EARLY_UVD_HARVEST_CLEAR_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-early-uvd-harvest-clear'
PRE_DIRECT_EARLY_UVD_HARVEST_MODE = 'metadata-tmr-svc-guard-direct-early-uvd-harvest'
PRE_VCPU_TRACE_MODE = 'metadata-tmr-svc-guard-rsmu12-gasket-readback-pre-vcpu-trace'
PRE_RESET_MODES = (PRE_RESET_MODE, PRE_UVD_RESET_MODE,
                   PRE_VCPU_CNTL_MODE, PRE_LMI_CTRL2_MODE,
                   PRE_CGC_GATE_MODE, PRE_CGC_CTRL_MODE,
                   PRE_LMI_VM_CTRL_MODE, PRE_UVD_HARVEST_MODE,
                   PRE_UVD_HARVEST_CLEAR_MODE, PRE_EARLY_UVD_HARVEST_MODE,
                   PRE_EARLY_UVD_HARVEST_CLEAR_MODE,
                   PRE_DIRECT_EARLY_UVD_HARVEST_MODE,
                   PRE_VCPU_TRACE_MODE)
MAP_RX_MODES = (MAP_RX_MODE,) + tuple(f'{MAP_RX_MODE}-prefix{count:02d}'
                                      for count in (1, 2, 4, 8, 12, 16)) + (
                                          f'{MAP_RX_MODE}-verify16', f'{MAP_RX_MODE}-verify17',
                                          f'{MAP_RX_MODE}-gfx-readback',
                                          f'{MAP_RX_MODE}-reset-release',
                                          f'{MAP_RX_MODE}-uvd-reset-release',
                                          f'{MAP_RX_MODE}-uvd-reset-status',
                                          f'{MAP_RX_MODE}-uvd-reset-before-write',
                                          f'{MAP_RX_MODE}-uvd-reset2-before-write',
                                          f'{MAP_RX_MODE}-uvd-reset-stability',
                                          f'{MAP_RX_MODE}-uvd-release-cgc-status',
                                          f'{MAP_RX_MODE}-uvd-release-lmi-status',
                                          SKIP_NATIVE_VIDEO_CONTROL_MODE)
ALL_MAP_MODES = MAP_MODES + MAP_RX_MODES
EXPECTED_MAP = (
    (0x2107c, 0x1fa00000), (0x21078, 0xf4),
    (0x20108, 0), (0x2010c, 0x64000),
    (0x20eb0, 0x1fd00000), (0x20eb4, 0xf4),
    (0x20110, 0), (0x20114, 0x20000),
    (0x20ec0, 0x1fd20000), (0x20ec4, 0xf4),
    (0x20118, 0), (0x2011c, 0x80000),
    (0x2108c, 0x1fda0000), (0x21088, 0xf4),
    (0x20150, 0), (0x20154, 0x1000),
    (0x1f928, 0x100044),
)
KEY_START, KEY_END = 0x9dbda0, 0x9dbef0
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def private_write(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def parse_profile(source):
    head = source.split('static const struct expected_run expected_runs[PROFILE_RUNS] = {', 1)[1]
    run_block = head.split('};', 1)[0]
    runs = [(int(a, 16), int(n)) for a, n in
            re.findall(r'\{0x([0-9a-f]+)u, (\d+)u\}', run_block)]
    words = source.split('static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {', 1)[1]
    key_words = [(int(a, 16), int(v, 16)) for a, v in
                 re.findall(r'\{0x([0-9a-f]+)u, 0x([0-9a-f]+)u\}', words.split('};', 1)[0])]
    if len(runs) != 39 or sum(n for _, n in runs) != 873480:
        raise ValueError('unexpected physical full trace')
    if len(key_words) != 69 or any(not KEY_START <= a & 0xffffff < KEY_END for a, _ in key_words):
        raise ValueError('unexpected key-copy patch')
    return run_block, runs, key_words


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--clean', required=True, type=Path)
    ap.add_argument('--private-key', required=True, type=Path)
    ap.add_argument('--type51-profile', required=True, type=Path)
    ap.add_argument('--hook', required=True, type=Path)
    ap.add_argument('--cave', required=True, type=Path)
    ap.add_argument('--tmr-hook', type=Path)
    ap.add_argument('--tmr-cave', type=Path)
    ap.add_argument('--svc-hook', type=Path)
    ap.add_argument('--svc-cave', type=Path)
    ap.add_argument('--postload-hook', type=Path)
    ap.add_argument('--postload-cave', type=Path)
    ap.add_argument('--readback-hook', type=Path)
    ap.add_argument('--readback-cave', type=Path)
    ap.add_argument('--program-table', type=Path)
    ap.add_argument('--map-addr-table', type=Path)
    ap.add_argument('--map-value-table', type=Path)
    ap.add_argument('--gasket-cave', type=Path)
    ap.add_argument('--mode', required=True,
                    choices=('noop', 'metadata', 'metadata-tmr',
                             'metadata-tmr-svc-guard',
                             'metadata-tmr-svc-guard-rsmu12',
                             'metadata-tmr-svc-guard-rsmu12-postload',
                             'metadata-tmr-svc-guard-rsmu12-readback',
                             'metadata-tmr-svc-guard-rsmu12-readback-uvd',
                             'metadata-tmr-svc-guard-rsmu12-gasket',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-cache',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-cache-write',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-power',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-reset',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-postpower-reset',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-postpower-cache',
                             'metadata-tmr-svc-guard-rsmu12-gasket-readback-postpower-cache-write')
                            + ALL_MAP_MODES + PRE_RESET_MODES)
    ap.add_argument('--output-dir', required=True, type=Path)
    ap.add_argument('--spi-diag', action='store_true',
                    help='capture four post-profile SPI address diagnostics')
    a = ap.parse_args()
    if a.spi_diag and a.mode != 'noop':
        ap.error('--spi-diag is only supported for the no-op startup probe')

    clean = a.clean.read_bytes()
    if len(clean) != 0x1000000 or sha(clean) != CLEAN_SHA:
        raise ValueError('clean ROM hash or size differs')
    profile_data = a.type51_profile.read_bytes()
    if sha(profile_data) != TYPE51_PROFILE_SHA:
        raise ValueError('type-51 physical profile hash differs')
    profile_source = profile_data.decode()
    run_block, runs, key_words = parse_profile(profile_source)
    hook, cave = a.hook.read_bytes(), a.cave.read_bytes()
    if len(hook) != 4 or not 6 <= len(cave) <= 0x80 or len(cave) % 4:
        raise ValueError('unexpected driver patch geometry')
    if clean[CAVE:CAVE+len(cave)] != bytes(len(cave)):
        raise ValueError('driver cave not empty')
    if clean[HOOK:HOOK+4] != bytes.fromhex('00 f0 35 f9'):
        # The pinned BL target is checked independently below if this changes.
        raise ValueError(f'unexpected original startup BL: {clean[HOOK:HOOK+4].hex()}')
    if (a.tmr_hook is None) != (a.tmr_cave is None):
        raise ValueError('TMR hook and cave must be supplied together')
    if (a.mode.startswith('metadata-tmr')) != (a.tmr_hook is not None):
        raise ValueError('TMR patch belongs only to metadata-tmr modes')
    if a.tmr_hook is not None:
        tmr_hook, tmr_cave = a.tmr_hook.read_bytes(), a.tmr_cave.read_bytes()
        if len(tmr_hook) != 4 or not 8 <= len(tmr_cave) <= 0x80 or len(tmr_cave) % 4:
            raise ValueError('unexpected TMR patch geometry')
        if clean[TMR_HOOK:TMR_HOOK+4] != bytes.fromhex('03 f0 c5 fc'):
            raise ValueError('unexpected original TMR allocator BL')
        if clean[TMR_CAVE:TMR_CAVE+len(tmr_cave)] != bytes(len(tmr_cave)):
            raise ValueError('TMR driver cave not empty')
    else:
        tmr_hook = tmr_cave = b''
    if (a.svc_hook is None) != (a.svc_cave is None):
        raise ValueError('SVC hook and cave must be supplied together')
    if (a.mode.startswith('metadata-tmr-svc-guard')) != (a.svc_hook is not None):
        raise ValueError('SVC guard belongs only to SVC-guard modes')
    if a.svc_hook is not None:
        svc_hook, svc_cave = a.svc_hook.read_bytes(), a.svc_cave.read_bytes()
        if len(svc_hook) != 8 or not 8 <= len(svc_cave) <= 0x80 or len(svc_cave) % 4:
            raise ValueError('unexpected SVC guard geometry')
        if clean[SVC_HOOK:SVC_HOOK+8] != bytes.fromhex('32 20 40 f6 22 45 05 e0'):
            raise ValueError('unexpected original post-SVC instructions')
        if clean[SVC_CAVE:SVC_CAVE+len(svc_cave)] != bytes(len(svc_cave)):
            raise ValueError('SVC driver cave not empty')
    else:
        svc_hook = svc_cave = b''
    if (a.postload_hook is None) != (a.postload_cave is None):
        raise ValueError('post-load hook and cave must be supplied together')
    if a.mode.endswith('-postload') != (a.postload_hook is not None):
        raise ValueError('post-load guard belongs only to the postload mode')
    if a.postload_hook is not None:
        postload_hook = a.postload_hook.read_bytes()
        postload_cave = a.postload_cave.read_bytes()
        if len(postload_hook) != 4 or not 8 <= len(postload_cave) <= 0x40 or len(postload_cave) % 4:
            raise ValueError('unexpected post-load guard geometry')
        if clean[POSTLOAD_HOOK:POSTLOAD_HOOK+4] != bytes.fromhex('07 f0 5f fa'):
            raise ValueError('unexpected original post-load helper call')
        if clean[POSTLOAD_CAVE:POSTLOAD_CAVE+len(postload_cave)] != bytes(len(postload_cave)):
            raise ValueError('post-load driver cave not empty')
    else:
        postload_hook = postload_cave = b''
    if (a.readback_hook is None) != (a.readback_cave is None):
        raise ValueError('readback hook and cave must be supplied together')
    gasket_readback = a.mode.startswith('metadata-tmr-svc-guard-rsmu12-gasket-readback')
    readback_hook_offset = PRE_RESET_HOOK if a.mode in PRE_RESET_MODES else READBACK_HOOK
    readback_offset = (MAP_CAVE if a.mode in ALL_MAP_MODES or a.mode in PRE_RESET_MODES else
                       GASKET_READBACK_CAVE if gasket_readback else READBACK_CAVE)
    if (a.mode in ('metadata-tmr-svc-guard-rsmu12-readback',
                   'metadata-tmr-svc-guard-rsmu12-readback-uvd',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-cache',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-cache-write',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-power',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-reset',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-postpower-reset',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-postpower-cache',
                   'metadata-tmr-svc-guard-rsmu12-gasket-readback-postpower-cache-write')
        or a.mode in ALL_MAP_MODES or a.mode in PRE_RESET_MODES) != (a.readback_hook is not None):
        raise ValueError('readback patch belongs only to the readback mode')
    if a.readback_hook is not None:
        readback_hook = a.readback_hook.read_bytes()
        readback_cave = a.readback_cave.read_bytes()
        limit = 0xac if a.mode in ALL_MAP_MODES or a.mode in PRE_RESET_MODES else 0x80
        if len(readback_hook) != 4 or not 8 <= len(readback_cave) <= limit or len(readback_cave) % 4:
            raise ValueError('unexpected readback patch geometry')
        original_hook = ('01 21 57 48' if a.mode in PRE_RESET_MODES else '07 f0 5f fa')
        if clean[readback_hook_offset:readback_hook_offset+4] != bytes.fromhex(original_hook):
            raise ValueError('unexpected original post-load helper call')
        if clean[readback_offset:readback_offset+len(readback_cave)] != bytes(len(readback_cave)):
            raise ValueError('readback driver cave not empty')
    else:
        readback_hook = readback_cave = b''
    if (a.mode in MAP_MODES) != (a.program_table is not None):
        raise ValueError('program table belongs only to the post-cache map mode')
    if a.program_table is not None:
        program_table = a.program_table.read_bytes()
        expected = b''.join(address.to_bytes(4, 'little') + value.to_bytes(4, 'little')
                            for address, value in EXPECTED_MAP)
        if program_table != expected or clean[PROGRAM_TABLE:PROGRAM_TABLE+len(expected)] != bytes(len(expected)):
            raise ValueError('unexpected pinned VCN map table or occupied driver data cave')
    else:
        program_table = b''
    if (a.map_addr_table is None) != (a.map_value_table is None):
        raise ValueError('RX address/value tables must be supplied together')
    if (a.mode in MAP_RX_MODES) != (a.map_addr_table is not None):
        raise ValueError('RX map tables belong only to RX map modes')
    if a.map_addr_table is not None:
        map_addrs = a.map_addr_table.read_bytes()
        map_values = a.map_value_table.read_bytes()
        expected_addrs = b''.join(address.to_bytes(4, 'little')
                                  for address, _ in EXPECTED_MAP)
        expected_values = b''.join(value.to_bytes(4, 'little')
                                   for _, value in EXPECTED_MAP)
        if (map_addrs != expected_addrs or map_values != expected_values or
            clean[MAP_ADDR_TABLE:MAP_ADDR_TABLE+len(map_addrs)] != bytes(len(map_addrs)) or
            clean[MAP_VALUE_TABLE:MAP_VALUE_TABLE+len(map_values)] != bytes(len(map_values))):
            raise ValueError('unexpected pinned RX VCN map table or occupied code cave')
    else:
        map_addrs = map_values = b''
    if (a.mode.endswith('-gasket') or gasket_readback) != (a.gasket_cave is not None):
        raise ValueError('gasket patch belongs only to gasket mode')
    if a.gasket_cave is not None:
        gasket_cave = a.gasket_cave.read_bytes()
        if not 0x1a0 <= len(gasket_cave) <= 0x200 or len(gasket_cave) % 4:
            raise ValueError('unexpected gasket patch geometry')
        if clean[GASKET_CAVE:GASKET_CAVE+len(gasket_cave)] != bytes(len(gasket_cave)):
            raise ValueError('gasket driver cave not empty')
    else:
        gasket_cave = b''

    modified = bytearray(clean)
    for command, reply in key_words:
        address = command & 0xffffff
        modified[address:address+4] = reply.to_bytes(4, 'big')
    modified[HOOK:HOOK+4] = hook
    modified[CAVE:CAVE+len(cave)] = cave
    if tmr_hook:
        modified[TMR_HOOK:TMR_HOOK+4] = tmr_hook
        modified[TMR_CAVE:TMR_CAVE+len(tmr_cave)] = tmr_cave
    if svc_hook:
        modified[SVC_HOOK:SVC_HOOK+len(svc_hook)] = svc_hook
        modified[SVC_CAVE:SVC_CAVE+len(svc_cave)] = svc_cave
    if postload_hook:
        modified[POSTLOAD_HOOK:POSTLOAD_HOOK+len(postload_hook)] = postload_hook
        modified[POSTLOAD_CAVE:POSTLOAD_CAVE+len(postload_cave)] = postload_cave
    if readback_hook:
        modified[readback_hook_offset:readback_hook_offset+len(readback_hook)] = readback_hook
        modified[readback_offset:readback_offset+len(readback_cave)] = readback_cave
    if program_table:
        modified[PROGRAM_TABLE:PROGRAM_TABLE+len(program_table)] = program_table
    if map_addrs:
        modified[MAP_ADDR_TABLE:MAP_ADDR_TABLE+len(map_addrs)] = map_addrs
        modified[MAP_VALUE_TABLE:MAP_VALUE_TABLE+len(map_values)] = map_values
    if gasket_cave:
        modified[GASKET_CAVE:GASKET_CAVE+len(gasket_cave)] = gasket_cave
    if a.mode == SKIP_NATIVE_VIDEO_CONTROL_MODE:
        native_svc = DRIVER + 0xe9c2
        if (clean[native_svc:native_svc+2] != bytes.fromhex('7c df') or
                modified[native_svc:native_svc+2] != bytes.fromhex('7c df')):
            raise ValueError('original video-control SVC does not match pinned bytes')
        # Skip only the original 0x1f820 <- 0x185103 SVC. The existing guard
        # immediately afterward checks R0, so return a synthetic success.
        modified[native_svc:native_svc+2] = bytes.fromhex('00 20')  # movs r0, #0
    driver_body = modified[DRIVER+0x100:DRIVER+DRIVER_LEN-256]
    modified[DRIVER+0xd0:DRIVER+0xf0] = hashlib.sha256(driver_body).digest()

    key = serialization.load_pem_private_key(a.private_key.read_bytes(), None)
    if key.key_size != 2048:
        raise ValueError('expected RSA-2048 key')
    modified[KDB_MODULUS:KDB_MODULUS+256] = key.public_key().public_numbers().n.to_bytes(256, 'little')
    for start, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = bytes(modified[start:start+length-256])
        signature = key.sign(body, PSS, hashes.SHA256())
        key.public_key().verify(signature, body, PSS, hashes.SHA256())
        modified[start+length-256:start+length] = signature
        if modified[start+0xd0:start+0xf0] != hashlib.sha256(
                modified[start+0x100:start+length-256]).digest():
            raise ValueError('signed header body hash mismatch')

    changed = [(0x03000000 | address, int.from_bytes(modified[address:address+4], 'big'))
               for address in range(0, len(clean), 4)
               if clean[address:address+4] != modified[address:address+4]]
    native_svc_range = ((DRIVER+0xe9c0, DRIVER+0xe9c4),) if (
        a.mode == SKIP_NATIVE_VIDEO_CONTROL_MODE) else ()
    allowed_ranges = ((KEY_START, KEY_END), (KDB_MODULUS, KDB_MODULUS+256),
                      (TOS+TOS_LEN-256, TOS+TOS_LEN),
                      (DRIVER+0xd0, DRIVER+0xf0), (HOOK & ~3, (HOOK+7) & ~3),
                      (CAVE, CAVE+len(cave)),
                      (TMR_HOOK & ~3, (TMR_HOOK+7) & ~3),
                      (TMR_CAVE, TMR_CAVE+len(tmr_cave)),
                      (SVC_HOOK, SVC_HOOK+len(svc_hook)),
                      *native_svc_range,
                      (SVC_CAVE, SVC_CAVE+len(svc_cave)),
                      (POSTLOAD_HOOK & ~3, (POSTLOAD_HOOK+len(postload_hook)+3) & ~3),
                      (POSTLOAD_CAVE, POSTLOAD_CAVE+len(postload_cave)),
                      (readback_hook_offset & ~3,
                       (readback_hook_offset+len(readback_hook)+3) & ~3),
                      (readback_offset, readback_offset+len(readback_cave)),
                      (PROGRAM_TABLE, PROGRAM_TABLE+len(program_table)),
                      (MAP_ADDR_TABLE, MAP_ADDR_TABLE+len(map_addrs)),
                      (MAP_VALUE_TABLE, MAP_VALUE_TABLE+len(map_values)),
                      (GASKET_CAVE, GASKET_CAVE+len(gasket_cave)),
                      (DRIVER+DRIVER_LEN-256, DRIVER+DRIVER_LEN))
    if any(not any(lo <= command & 0xffffff < hi for lo, hi in allowed_ranges)
           for command, _ in changed):
        raise ValueError('change outside allowlist')

    changes = {command: value for command, value in changed}
    reply_count, row = 0, 0
    for start, count in runs:
        for offset in range(count):
            command = start + 4*offset
            address = command & 0xffffff
            if (command in changes and
                    not (0x9dad00 <= address < 0x9dbad0 and row >= 696) and
                    not (KEY_START <= address < KEY_END and row >= 873080)):
                reply_count += 1
            row += 1
    if row != 873480 or reply_count < 200:
        raise ValueError('unexpected physical response count')
    if changed != sorted(changed):
        raise ValueError('patch words not sorted')

    name = f'vcn-driver-{a.mode}' + ('-spi-diag' if a.spi_diag else '')
    lines = ['/* Private RAM-only interposer trial. NEVER flash to BC250. */',
             '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
             '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
             f'#define PROFILE_NAME "{name}"',
             *(['#define PROFILE_DIAG_SPI 1', '#define PROFILE_DIAG_CAPACITY 4u']
               if a.spi_diag else []),
             *(['#define PROFILE_DIAG_MARKER 0x03c3fffcu'] if a.spi_diag else []),
             '#define PROFILE_ROWS 873480u', '#define PROFILE_RUNS 39u',
             f'#define PROFILE_CHANGED_WORDS {len(changed)}u',
             '#define PROFILE_SECOND_KEYDB_ROW 696u',
             '#define PROFILE_TYPE51_HASH_ROW 873080u',
             f'#define PROFILE_EXPECTED_PATCH_READS {reply_count}u',
             'static const struct expected_run expected_runs[PROFILE_RUNS] = {' + run_block + '};',
             'static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {']
    lines.extend(f'    {{0x{command:08x}u, 0x{value:08x}u}},' for command, value in changed)
    lines += ['};', '#endif', '']
    a.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(a.output_dir/'trial-NEVER-flash.rom', bytes(modified))
    private_write(a.output_dir/'sparse_physical_profile.h', '\n'.join(lines).encode())
    summary = dict(mode=a.mode, clean_sha256=CLEAN_SHA,
                   trial_sha256=sha(modified), changed_words=len(changed),
                   expected_patch_reads_per_pass=reply_count,
                   driver_hook=hex(HOOK), driver_cave=hex(CAVE),
                   driver_cave_bytes=len(cave), type51_key_words=len(key_words),
                   tmr_hook=(hex(TMR_HOOK) if tmr_hook else None),
                   tmr_cave=(hex(TMR_CAVE) if tmr_cave else None),
                   tmr_cave_bytes=len(tmr_cave),
                   svc_hook=(hex(SVC_HOOK) if svc_hook else None),
                   svc_cave=(hex(SVC_CAVE) if svc_cave else None),
                   svc_cave_bytes=len(svc_cave),
                   native_video_control_svc_omitted=(a.mode == SKIP_NATIVE_VIDEO_CONTROL_MODE),
                   postload_hook=(hex(POSTLOAD_HOOK) if postload_hook else None),
                   postload_cave=(hex(POSTLOAD_CAVE) if postload_cave else None),
                   postload_cave_bytes=len(postload_cave),
                   readback_hook=(hex(readback_hook_offset) if readback_hook else None),
                   readback_cave=(hex(readback_offset) if readback_cave else None),
                   readback_cave_bytes=len(readback_cave),
                   program_table=(hex(PROGRAM_TABLE) if program_table else None),
                   program_table_bytes=len(program_table),
                   map_addr_table=(hex(MAP_ADDR_TABLE) if map_addrs else None),
                   map_value_table=(hex(MAP_VALUE_TABLE) if map_values else None),
                   map_table_entries=len(map_addrs)//4,
                   original_tos_body=clean[TOS:TOS+TOS_LEN-256] == modified[TOS:TOS+TOS_LEN-256],
                   spi_diag=a.spi_diag,
                   bios_flash_allowed=False)
    private_write(a.output_dir/'summary.json', (json.dumps(summary, indent=2)+'\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
