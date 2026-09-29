#!/usr/bin/env python3
"""Run the pinned postrelease trial with one guarded host-MMIO harvest write."""

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path('/var/lib/bc250/validation/video-20260922/kernel')
RUNNER = ROOT / 'run_late_vcn_postrelease_measure.py'
RUNNER_SHA = 'b1834e08dfb4155fd5cb03adf6da2a1ba710d055512b7032574340ee23dee16c'
MODULE = ROOT / 'amdgpu-vcn-harvest-write.ko'
MODULE_SHA = '8ff186ee1f75c41850f7bb657ba2cd8cf0561e9b83a6fdf00c24254f22869c9a'


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
