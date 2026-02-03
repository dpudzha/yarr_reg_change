#!/usr/bin/env python3
"""
Script to measure vmux and imux register values for ITkPixV2 chips.

Usage:
    python change_registers.py <input_json> <chip_numbers> <vmux_values> <imux_values> [output_file]

Examples:
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 0,5,12 0,5,12
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,3 10 20 my_output.txt
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime


CHIP_NUMBER_TO_ID = {1: 12, 2: 13, 3: 14, 4: 15}

SCAN_CONSOLE = "/YARR/bin/scanConsole"
CONTROLLER_CONFIG = "/configs/yarr/controller/controller_demi.json"


def parse_csv_ints(value):
    """Parse a comma-separated string of integers."""
    return [int(x.strip()) for x in value.split(",")]


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def set_monitor(chip_json_path, monitor_v, monitor_i):
    """Set MonitorV and MonitorI in a chip JSON file via text replacement."""
    import re

    with open(chip_json_path, "r") as f:
        text = f.read()

    text = re.sub(r'("MonitorV"\s*:\s*)\d+', rf'\g<1>{monitor_v}', text)
    text = re.sub(r'("MonitorI"\s*:\s*)\d+', rf'\g<1>{monitor_i}', text)

    with open(chip_json_path, "w") as f:
        f.write(text)


def run_scan(input_json, max_retries=3):
    """Run the scanConsole executable with retry logic."""
    cmd = [SCAN_CONSOLE, "-r", CONTROLLER_CONFIG, "-c", input_json, "-o", "/dev/null"]

    for attempt in range(1, max_retries + 1):
        print(f"  Running (attempt {attempt}/{max_retries}): {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Check for failure: critical error in output
        output = result.stdout + result.stderr
        if "[critical]" in output.lower():
            print(f"  Attempt {attempt} failed.")
            if attempt < max_retries:
                print("  Retrying...")
                time.sleep(2)
            else:
                print(f"  All {max_retries} attempts failed. Exiting.")
                sys.exit(1)
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"  Configuration completed successfully at {timestamp}.")
            return timestamp


def main():
    parser = argparse.ArgumentParser(
        description="Measure vmux and imux register values for ITkPixV2 chips."
    )
    parser.add_argument("input_json", help="Path to the main connectivity JSON file")
    parser.add_argument(
        "chip_numbers",
        help="Comma-separated chip numbers to measure (1-4)",
    )
    parser.add_argument(
        "vmux",
        help="Comma-separated vmux values (0-63)",
    )
    parser.add_argument(
        "imux",
        help="Comma-separated imux values (0-63)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Output filename (default: registers_info_{datetime}.txt)",
    )
    args = parser.parse_args()

    # Parse arguments
    chip_numbers = parse_csv_ints(args.chip_numbers)
    vmux_values = parse_csv_ints(args.vmux)
    imux_values = parse_csv_ints(args.imux)

    # Validate chip numbers
    for cn in chip_numbers:
        if cn not in CHIP_NUMBER_TO_ID:
            sys.exit(f"Error: chip number {cn} is invalid. Must be 1-4.")

    # Validate vmux/imux ranges
    for v in vmux_values:
        if not 0 <= v <= 63:
            sys.exit(f"Error: vmux value {v} out of range (0-63).")
    for i in imux_values:
        if not 0 <= i <= 63:
            sys.exit(f"Error: imux value {i} out of range (0-63).")

    # Output file
    if args.output:
        output_file = args.output
    else:
        output_file = f"registers_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    # Resolve paths
    input_json_path = os.path.abspath(args.input_json)
    input_dir = os.path.dirname(input_json_path)
    module_name = os.path.basename(input_dir)

    # Load main connectivity JSON
    connectivity = load_json(input_json_path)
    chips_entries = connectivity["chips"]

    # Resolve all chip JSON paths and read their ChipIds
    chip_files = []  # list of (abs_path, chip_id, chip_name)
    for entry in chips_entries:
        config_rel = entry["config"]
        chip_json_path = os.path.join(input_dir, config_rel)
        chip_json_path = os.path.abspath(chip_json_path)
        chip_data = load_json(chip_json_path)
        chip_id = chip_data["ITKPIXV2"]["Parameter"]["ChipId"]
        chip_name = chip_data["ITKPIXV2"]["Parameter"]["Name"]
        chip_files.append((chip_json_path, chip_id, chip_name))

    # Map chip_number -> (chip_json_path, chip_id, chip_name)
    id_to_number = {v: k for k, v in CHIP_NUMBER_TO_ID.items()}
    chip_number_map = {}
    for path, chip_id, chip_name in chip_files:
        cn = id_to_number.get(chip_id)
        if cn is not None:
            chip_number_map[cn] = (path, chip_id, chip_name)

    # Verify requested chips exist
    for cn in chip_numbers:
        if cn not in chip_number_map:
            expected_id = CHIP_NUMBER_TO_ID[cn]
            sys.exit(
                f"Error: chip number {cn} (ChipId={expected_id}) not found in any config file."
            )

    all_chip_paths = [path for path, _, _ in chip_files]

    # Collect output rows
    rows = []

    for cn in chip_numbers:
        target_path, chip_id, chip_name = chip_number_map[cn]
        other_paths = [p for p in all_chip_paths if p != target_path]

        # --- vmux measurements ---
        for vmux in vmux_values:
            print(f"\n=== Chip {cn} (ChipId={chip_name}): vmux={vmux} ===")

            # Set target chip: MonitorV=vmux, MonitorI=63
            set_monitor(target_path, vmux, 63)

            # Set all other chips: MonitorV=63, MonitorI=63
            for op in other_paths:
                set_monitor(op, 63, 63)

            # Run scan
            timestamp = run_scan(args.input_json)

            # Wait
            print("  Waiting 10 seconds...")
            time.sleep(10)

            rows.append((module_name, chip_name, cn, "vmux", vmux, timestamp))

        # --- imux measurements ---
        for imux in imux_values:
            print(f"\n=== Chip {cn} (ChipId={chip_name}): imux={imux} ===")

            # Set target chip: MonitorV=1, MonitorI=imux
            set_monitor(target_path, 1, imux)

            # Set all other chips: MonitorV=63, MonitorI=63
            for op in other_paths:
                set_monitor(op, 63, 63)

            # Run scan
            timestamp = run_scan(args.input_json)

            # Wait
            print("  Waiting 10 seconds...")
            time.sleep(10)

            rows.append((module_name, chip_name, cn, "imux", imux, timestamp))

    # Write output table
    header = f"{'Module':<25} {'ChipId':<10} {'ChipNum':<8} {'RegType':<8} {'RegValue':<8} {'Timestamp':<20}"
    sep = "-" * len(header)

    with open(output_file, "w") as f:
        f.write(header + "\n")
        f.write(sep + "\n")
        for module, cid, cn, rtype, rval, ts in rows:
            f.write(f"{module:<25} {cid:<10} {cn:<8} {rtype:<8} {rval:<8} {ts:<20}\n")

    print(f"\nResults written to {output_file}")


if __name__ == "__main__":
    main()
