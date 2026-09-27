#!/usr/bin/env python3
"""Retain a local RSA signer and build private SRAM overlays; no device access.

Requires the previously modeled, pinned TOS template. The resulting patched
ROM is invalid without the copy/check substitution. NEVER flash it on-board.
The private key stays on the workstation; overlay.bin contains no private key.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SHA = lambda b: hashlib.sha256(b).hexdigest()
BASE_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
TEMPLATE_SHA = 'd6c906e273b497ec9840a82cb4b35e020c11bb0b34fd7a024283e36fb82686fe'
COMPONENT_TEST_SHA = 'e2cf096c9acc7493434f76caaf56703d2058c44e5b6526ef9c0ddcb19b3cb52a'
KDB, KDB_LEN, MODULUS = 0x9dad00, 0xdd0, 0x9db140
TOS, TOS_LEN, DRIVER, DRIVER_LEN = 0x8eac00, 0x14350, 0x984f00, 0x1a770
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_private(path, blob):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(blob)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template-manifest', type=Path, required=True)
    parser.add_argument('--analysis-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, 'do not run with Python -O: native model uses assertions')
    out = args.output.resolve()
    require(not out.exists(), 'output already exists; retaining existing signer, refusing overwrite')
    m = json.loads(args.template_manifest.read_text())
    clean = Path(m['clean_path']).read_bytes()
    template = Path(m['patched_path']).read_bytes()
    require(len(clean) == len(template) == 0x1000000, 'expected 16 MiB ROMs')
    require(SHA(clean) == BASE_SHA and SHA(template) == TEMPLATE_SHA, 'pinned template mismatch')
    test_path = args.analysis_dir.resolve() / 'test-tos-video-interposer-component.py'
    require(SHA(test_path.read_bytes()) == COMPONENT_TEST_SHA, 'component model changed')
    spec = importlib.util.spec_from_file_location('tos_component', test_path)
    tc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tc)

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    patched = bytearray(template)
    patched[MODULUS:MODULUS+256] = public.public_numbers().n.to_bytes(256, 'little')
    for offset, size in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = bytes(patched[offset:offset+size-256])
        patched[offset+size-256:offset+size] = private.sign(body, PSS, hashes.SHA256())
        public.verify(bytes(patched[offset+size-256:offset+size]), body, PSS, hashes.SHA256())
    # Require all template modifications outside the replacement key/signatures
    # to remain byte-identical to the already-tested TOS component.
    allowed = lambda i: (MODULUS <= i < MODULUS+256 or
                         TOS+TOS_LEN-256 <= i < TOS+TOS_LEN or
                         DRIVER+DRIVER_LEN-256 <= i < DRIVER+DRIVER_LEN)
    require(all(a == b or allowed(i) for i,(a,b) in enumerate(zip(template,patched))),
            'unexpected change outside signer/signatures')
    cases = []
    for fill in (0, 0xa5):
        for switch in (False, True):
            model = tc.s.SplitView(fill, 0x50, switch)
            require(model.original == clean[KDB:KDB+KDB_LEN], 'native model ROM mismatch')
            model.input = bytes(patched[KDB:KDB+KDB_LEN])
            model.m.mem_write(tc.s.p.FLASH+model.offset, model.input)
            result = model.call(0x7088, (0x50,), stops=(tc.t.STOP,0x6fdc))
            accepted = model.stop == tc.t.STOP and result == 0x42444b24
            require(accepted == switch, 'native copy/check control failed')
            cases.append(dict(fill=fill, switch_after_copy=switch, accepted=accepted,
                              stop=hex(model.stop)))
    payload = bytes(patched[TOS+0x100:TOS+TOS_LEN-256])
    entry_cases = [tc.run_entry(payload, fill, r0, variant)
                   for fill in (0,0xa5) for r0 in (0,1)
                   for variant in ('original','bad_ps1','bad_kdb','bad_length','bad_usage')]

    public_pem = public.public_bytes(serialization.Encoding.PEM,
                                     serialization.PublicFormat.SubjectPublicKeyInfo)
    private_pem = private.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
    overlay = bytearray()
    segments = []
    for name, address, source, length, policy in (
        ('type50-clean', KDB, clean, KDB_LEN, 'verification pass'),
        ('type50-patched', KDB, patched, KDB_LEN, 'RAM-copy pass only'),
        ('tos-patched', TOS, patched, TOS_LEN, 'all TOS reads'),
        ('driver-patched', DRIVER, patched, DRIVER_LEN, 'all driver-entries reads')):
        blob = bytes(source[address:address+length])
        segments.append(dict(name=name, flash_address=address, length=length,
                             buffer_offset=len(overlay), sha256=SHA(blob), policy=policy))
        overlay += blob
    require(len(overlay) < 256*1024, 'overlay exceeds planned SRAM allocation')
    changed = [i for i,(a,b) in enumerate(zip(clean,patched)) if a != b]
    # Retain old verifier metadata, with the persistent signer and actual bytes.
    m.update(scope=__doc__, script_sha256=SHA(Path(__file__).read_bytes()),
             template_sha256=TEMPLATE_SHA,
             clean_path=str(out/'CLEAN-working-backup.rom'),
             patched_path=str(out/'PATCHED-interposer-only-NEVER-flash-on-board.rom'),
             clean_sha256=SHA(clean), patched_sha256=SHA(patched),
             changed_byte_count=len(changed), changed_first=hex(changed[0]),
             changed_last=hex(changed[-1]), actual_pair_native_split_cases=cases,
             tos_entry_cases=entry_cases, private_signing_key_saved=True,
             private_key_path=str(out/'signer-private.pem'),
             public_key_sha256=SHA(public_pem),
             trial_tos_and_driver_verify_under_disposable_signer=False,
             trial_tos_and_driver_verify_under_retained_signer=True,
             intended_use='Isolated interposer only; Pico SRAM timings/triggers not yet measured',
             overlay=dict(path=str(out/'overlay.bin'),bytes=len(overlay),sha256=SHA(overlay),
                          segments=segments,contains_private_key=False,
                          trigger_profile_ready=False),
             physical_trial=False, hardware_decode_verified=False, flash_written=False)
    out.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.private-staging-',dir=out.parent))
    os.chmod(staging, 0o700)
    for name, blob in {
        'signer-private.pem':private_pem, 'signer-public.pem':public_pem,
        'CLEAN-working-backup.rom':clean,
        'PATCHED-interposer-only-NEVER-flash-on-board.rom':bytes(patched),
        'overlay.bin':bytes(overlay),
        'MANIFEST.json':(json.dumps(m,indent=2)+'\n').encode(),
    }.items():
        write_private(staging/name, blob)
        require(stat.S_IMODE((staging/name).stat().st_mode)==0o600, 'private file mode')
    require(serialization.load_pem_private_key((staging/'signer-private.pem').read_bytes(),None)
            .public_key().public_numbers()==public.public_numbers(), 'saved key roundtrip failed')
    staging.rename(out)
    print(json.dumps(dict(output=str(out),public_key_sha256=SHA(public_pem),
                          patched_sha256=SHA(patched),overlay_bytes=len(overlay),
                          overlay_sha256=SHA(overlay),native_split_cases=len(cases),
                          tos_entry_cases=len(entry_cases),private_key_printed=False,
                          physical_trial=False),indent=2))


if __name__ == '__main__':
    main()
