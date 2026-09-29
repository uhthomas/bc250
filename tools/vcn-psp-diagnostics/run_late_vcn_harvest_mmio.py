#!/usr/bin/env python3
"""Run the pinned postrelease trial with one guarded host-MMIO harvest read."""

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path('/var/lib/bc250/validation/video-20260922/kernel')
RUNNER = ROOT / 'run_late_vcn_postrelease_measure.py'
RUNNER_SHA = 'b1834e08dfb4155fd5cb03adf6da2a1ba710d055512b7032574340ee23dee16c'
MODULE = ROOT / 'amdgpu-vcn-harvest-mmio.ko'
MODULE_SHA = 'c835b22df299c94c0357a564dc79b54e68ccd50e483c832da83c267acf3e7b18'


def main():
    assert hashlib.sha256(RUNNER.read_bytes()).hexdigest() == RUNNER_SHA
    assert hashlib.sha256(MODULE.read_bytes()).hexdigest() == MODULE_SHA
    spec = importlib.util.spec_from_file_location('pinned_postrelease', RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.MODULE = MODULE
    runner.MODULE_SHA = MODULE_SHA
    runner.main()


if __name__ == '__main__':
    main()
