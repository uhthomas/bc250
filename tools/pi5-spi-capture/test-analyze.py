#!/usr/bin/env python3
"""Check full/partial split-read classification using synthetic SPI commands."""

import importlib.util
from pathlib import Path
import struct

SOURCE = Path(__file__).with_name("analyze.py")
spec = importlib.util.spec_from_file_location("capture_analysis", SOURCE)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def encoded(addresses):
    return b"".join(struct.pack("<I", (0x03 << 24) | address)
                    for address in addresses)


def complete_body(name):
    start, end = analysis.WINDOWS[name]
    return list(range(start, end, 4))


def main():
    prefix = [0x821000, 0x821004, 0x821008]
    body50 = complete_body("type50_body")
    body51 = complete_body("type51_body")
    complete = prefix + body50 + [0x000000] + body50 + body51 + body51
    report = analysis.analyze(encoded(complete))
    assert report["windows"]["type50_body"]["complete_contiguous_passes"] == 2
    assert report["windows"]["type51_body"]["complete_contiguous_passes"] == 2
    assert report["windows"]["type50_body"]["complete_pass_first_command_words"] == [3, 696]
    assert report["windows"]["type50_body"]["complete_pass_last_command_words"] == [694, 1387]
    assert report["windows"]["type50_body"]["successive_pass_end_to_end_command_counts"] == [693]
    assert report["windows"]["type51_body"]["successive_pass_end_to_end_command_counts"] == [272]
    assert not report["warnings"]

    # One missing address must split a pass and prevent a false complete count.
    gap = prefix + body50 + body50[:100] + body50[101:] + body51
    report = analysis.analyze(encoded(gap))
    assert report["windows"]["type50_body"]["complete_contiguous_passes"] == 1
    assert report["windows"]["type51_body"]["complete_contiguous_passes"] == 1
    assert len(report["warnings"]) == 2

    # Non-03h data cannot be represented as trusted addresses.
    report = analysis.analyze(struct.pack("<IIII", 0x05000000, 0x9F000000,
                                          0x00000000, 0x039DAE00))
    assert report["recognized_03_fraction"] == 0.25
    assert any("Fewer than 80%" in warning for warning in report["warnings"])
    print("PASS: complete, gapped and implausible-command controls")


if __name__ == "__main__":
    main()
