#!/usr/bin/env python3
"""Summarize Pi 5 PIO SPI command words without inferring uncaptured reads.

The input is little-endian uint32 words; each word is assumed to contain the
first 32 MOSI bits after one CS# assertion, MSB first. Only opcode 0x03 with
a 24-bit address is decoded. The capture has no MISO, clock measurements or
overflow markers and is not proof of module contents or PSP execution.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

WINDOWS = {
    "type50_body": (0x9DAE00, 0x9DB8D0),
    "type51_body": (0x9DBC00, 0x9DC040),
    "encrypted_bootloader": (0x821000, 0x82B800),
}


def runs_in_window(reads, start, end):
    """Return ordered, adjacent 4-byte address runs within [start, end)."""
    runs = []
    current = None
    for event in reads:
        index, address = event
        if not start <= address < end:
            if current is not None:
                runs.append(current)
                current = None
            continue
        if current and index == current["last_word"] + 1 and address == current["end"]:
            current["last_word"] = index
            current["end"] += 4
            current["words"] += 1
        else:
            if current is not None:
                runs.append(current)
            current = dict(first_word=index, last_word=index, start=address,
                           end=address + 4, words=1)
    if current is not None:
        runs.append(current)
    return runs


def analyze(raw):
    if len(raw) % 4:
        raise ValueError("capture length is not a multiple of four bytes")
    words = struct.unpack("<" + "I" * (len(raw) // 4), raw)
    opcodes = Counter(word >> 24 for word in words)
    reads = [(index, word & 0xFFFFFF) for index, word in enumerate(words)
             if word >> 24 == 0x03]
    result = {
        "scope": __doc__.strip(),
        "capture_sha256": hashlib.sha256(raw).hexdigest(),
        "total_command_words": len(words),
        "opcode_counts": {f"0x{opcode:02x}": count for opcode, count
                          in sorted(opcodes.items(), key=lambda item: (-item[1], item[0]))},
        "recognized_03_fraction": round(len(reads) / len(words), 6) if words else 0,
        "warnings": [],
        "windows": {},
    }
    if not words:
        result["warnings"].append("Empty capture; no read-order inference is possible.")
    elif len(reads) / len(words) < 0.8:
        result["warnings"].append(
            "Fewer than 80% of words are opcode 03h. SPI phase, command length, "
            "alignment or capture loss may differ; do not infer absent reads.")
    for name, (start, end) in WINDOWS.items():
        runs = runs_in_window(reads, start, end)
        complete = [run for run in runs if run["start"] == start and run["end"] == end]
        result["windows"][name] = {
            "start": hex(start), "end_exclusive": hex(end),
            "expected_words_per_pass": (end - start) // 4,
            "complete_contiguous_passes": len(complete),
            "complete_pass_first_command_words": [run["first_word"] for run in complete],
            "complete_pass_last_command_words": [run["last_word"] for run in complete],
            "successive_pass_end_to_end_command_counts": [
                next_run["last_word"] - run["last_word"]
                for run, next_run in zip(complete, complete[1:])],
            "observed_in_window_words": sum(run["words"] for run in runs),
            "longest_runs": sorted(runs, key=lambda run: (-run["words"], run["first_word"]))[:8],
        }
        if name.startswith("type") and len(complete) < 2:
            result["warnings"].append(
                f"{name}: fewer than two complete contiguous body passes in this "
                "capture. This may be a short/lossy trace, not absence on the bus.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="raw little-endian uint32 word file")
    parser.add_argument("--json", type=Path, help="write complete JSON report")
    args = parser.parse_args()
    report = analyze(args.capture.read_bytes())
    print("capture", args.capture, "SHA256", report["capture_sha256"])
    print("command words", report["total_command_words"],
          "recognized 03h", report["recognized_03_fraction"])
    print("opcodes", report["opcode_counts"])
    for name, window in report["windows"].items():
        print(name, "complete contiguous passes", window["complete_contiguous_passes"],
              "start/end command words", list(zip(
                  window["complete_pass_first_command_words"],
                  window["complete_pass_last_command_words"])),
              "end-to-end counts", window["successive_pass_end_to_end_command_counts"],
              "longest", [run["words"] for run in window["longest_runs"][:3]])
    for warning in report["warnings"]:
        print("WARNING:", warning)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
