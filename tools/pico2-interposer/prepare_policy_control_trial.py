#!/usr/bin/env python3
"""Add one policy-service omission to the proven RAM-only VCN trial.

The input profile already omits the later native type-13 0x1f820 write. This
trial omits the identical earlier SEC_GASKET service request only when both
its address and value match. It never edits the signed policy or BIOS EEPROM.
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
BASE_SHA = 'c2cd1cbf810f634eb30e183af05d053aa746f8dd9411434e271d91b971629995'
PROFILE_SHA = '39419ef5ff09fa88c399ccceb31c8886b379da5fb258dfca49a1d98fb18e5d5b'
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
HOOK, CAVE = DRIVER + 0x22c6, DRIVER + 0x19100
TOS, TOS_LEN = 0x8eac00, 0x14350
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def parse_header(source):
    run_block = source.split('static const struct expected_run expected_runs[PROFILE_RUNS] = {', 1)[1].split('};', 1)[0]
    runs = [(int(a, 16), int(n)) for a, n in
            re.findall(r'\{0x([0-9a-f]+)u, (\d+)u\}', run_block)]
    word_block = source.split('static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {', 1)[1].split('};', 1)[0]
    words = [(int(a, 16), int(v, 16)) for a, v in
             re.findall(r'\{0x([0-9a-f]+)u, 0x([0-9a-f]+)u\}', word_block)]
    if len(runs) != 39 or sum(n for _, n in runs) != 873480:
        raise ValueError('physical profile geometry changed')
    return runs, words


def replies_for(runs, changed):
    addresses = {a for a, _ in changed}
    count = row = 0
    for start, length in runs:
        for offset in range(length):
            command = start + 4 * offset
            address = command & 0xffffff
            if command in addresses and not (
                0x9dad00 <= address < 0x9dbad0 and row >= 696
            ) and not (
                0x9dbda0 <= address < 0x9dbef0 and row >= 873080
            ):
                count += 1
            row += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--base-rom', required=True, type=Path)
    parser.add_argument('--base-profile', required=True, type=Path)
    parser.add_argument('--private-key', required=True, type=Path)
    parser.add_argument('--hook', required=True, type=Path)
    parser.add_argument('--cave', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()

    clean, base = args.clean.read_bytes(), args.base_rom.read_bytes()
    original_profile = args.base_profile.read_bytes()
    if (len(clean) != 0x1000000 or len(base) != len(clean) or
            sha(clean) != CLEAN_SHA or sha(base) != BASE_SHA or
            sha(original_profile) != PROFILE_SHA):
        raise ValueError('clean ROM, prior trial, or physical profile does not match')
    profile = original_profile.decode()
    runs, old_words = parse_header(profile)
    expected_old = [(0x03000000 | i, int.from_bytes(base[i:i+4], 'big'))
                    for i in range(0, len(base), 4)
                    if clean[i:i+4] != base[i:i+4]]
    if len(old_words) != 478 or old_words != expected_old or replies_for(runs, old_words) != 703:
        raise ValueError('prior physical response set differs')

    hook, cave = args.hook.read_bytes(), args.cave.read_bytes()
    if len(hook) != 4 or not 32 <= len(cave) <= 64 or len(cave) % 4:
        raise ValueError('unexpected hook or cave size')
    if hook != bytes.fromhex('16f01bbf'):
        raise ValueError('hook no longer branches to the pinned cave')
    if base[HOOK:HOOK+4] != bytes.fromhex('7cdf641c') or clean[HOOK:HOOK+4] != base[HOOK:HOOK+4]:
        raise ValueError('original policy SVC/loop increment differs')
    if any(base[CAVE:CAVE+len(cave)]) or clean[CAVE:CAVE+len(cave)] != base[CAVE:CAVE+len(cave)]:
        raise ValueError('policy code cave is occupied')
    if base[DRIVER+0xe9c2:DRIVER+0xe9c4] != bytes.fromhex('0020'):
        raise ValueError('prior native type-13 omission is absent')
    if clean[0x982000:0x984e50] != base[0x982000:0x984e50]:
        raise ValueError('SEC_GASKET is not the original signed policy')
    if clean[0x983068:0x983070] != bytes.fromhex('20f8010003511800'):
        raise ValueError('SEC_GASKET target record differs')

    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    if key.key_size != 2048:
        raise ValueError('expected RSA-2048 signer')
    if base[0x9db140:0x9db240] != key.public_key().public_numbers().n.to_bytes(256, 'little'):
        raise ValueError('prior type-30 signer key differs')
    for address, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = base[address:address+length-256]
        key.public_key().verify(base[address+length-256:address+length], body, PSS, hashes.SHA256())

    modified = bytearray(base)
    modified[HOOK:HOOK+4] = hook
    modified[CAVE:CAVE+len(cave)] = cave
    modified[DRIVER+0xd0:DRIVER+0xf0] = hashlib.sha256(
        modified[DRIVER+0x100:DRIVER+DRIVER_LEN-256]).digest()
    body = bytes(modified[DRIVER:DRIVER+DRIVER_LEN-256])
    signature = key.sign(body, PSS, hashes.SHA256())
    key.public_key().verify(signature, body, PSS, hashes.SHA256())
    modified[DRIVER+DRIVER_LEN-256:DRIVER+DRIVER_LEN] = signature
    allowed = ((HOOK, HOOK+4), (CAVE, CAVE+len(cave)),
               (DRIVER+0xd0, DRIVER+0xf0),
               (DRIVER+DRIVER_LEN-256, DRIVER+DRIVER_LEN))
    if any(not any(lo <= i < hi for lo, hi in allowed)
           for i, (old, new) in enumerate(zip(base, modified)) if old != new):
        raise ValueError('unexpected change outside policy hook or driver authentication')

    words = [(0x03000000 | i, int.from_bytes(modified[i:i+4], 'big'))
             for i in range(0, len(modified), 4)
             if clean[i:i+4] != modified[i:i+4]]
    replies = replies_for(runs, words)
    if replies <= 703 or words != sorted(words):
        raise ValueError('new physical profile has no effective substitutions')
    source = re.sub(r'#define PROFILE_NAME ".*"',
                    '#define PROFILE_NAME "vcn-skip-both-1f820"', profile, count=1)
    source = re.sub(r'#define PROFILE_CHANGED_WORDS \d+u',
                    f'#define PROFILE_CHANGED_WORDS {len(words)}u', source, count=1)
    source = re.sub(r'#define PROFILE_EXPECTED_PATCH_READS \d+u',
                    f'#define PROFILE_EXPECTED_PATCH_READS {replies}u', source, count=1)
    word_lines = '\n'.join(f'    {{0x{a:08x}u, 0x{v:08x}u}},' for a, v in words)
    source = re.sub(r'(static const struct patch_word patch_words\[PROFILE_CHANGED_WORDS\] = \{).*?(\};)',
                    lambda m: m.group(1) + '\n' + word_lines + '\n' + m.group(2),
                    source, count=1, flags=re.DOTALL)
    if parse_header(source)[1] != words:
        raise ValueError('generated physical profile does not round-trip')

    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(args.output_dir/'trial-NEVER-flash.rom', bytes(modified))
    private_write(args.output_dir/'sparse_physical_profile.h', source.encode())
    summary = dict(mode='skip-native-and-policy-1f820',
                   clean_sha256=CLEAN_SHA, base_sha256=BASE_SHA,
                   trial_sha256=sha(modified), profile_sha256=sha(source.encode()),
                   hook_sha256=sha(hook), cave_sha256=sha(cave),
                   changed_words=len(words), expected_patch_reads_per_pass=replies,
                   policy_object_byte_identical=True,
                   policy_loop_target=(hex(0x1f820), hex(0x185103)),
                   native_type13_svc_still_omitted=True,
                   bios_flash_allowed=False)
    private_write(args.output_dir/'summary.json', (json.dumps(summary, indent=2)+'\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
