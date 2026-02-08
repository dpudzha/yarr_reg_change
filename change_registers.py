#!/usr/bin/env python3
"""
Script to change vmux and imux register values and configure ITkPixV2 quad modules.

Supports both single-module and multi-module connectivity files.
When using multi-module files, the specified chip position is configured
across ALL modules, then a single scan is run.

Usage:
    python change_registers.py <input_json> <chip_numbers> [--vmux <values>] [--imux <values>] [--scan-type TYPE] [output_file]

Examples:
    # Single module - both vmux and imux
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5,12 --imux 0,5,12

    # Only vmux measurements
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5,12

    # Only imux measurements
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --imux 0,5,12

    # Multi-module: configure chip 4 in all modules, run one scan
    python3 change_registers.py /configs/modules/SP_4_modules.json 4 --vmux 0,5,12 --imux 0,5,12

    # With dedicated scan type (runs std_digitalscan.json instead of simple config)
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5 --scan-type digital

    # Available scan types: digital, analog, noise, random, selftrigger
    python3 change_registers.py module.json 1 --imux 10 --scan-type selftrigger

    # With Grafana readback (queries M1-M4 REG[V] panels after each scan)
    python3 change_registers.py SP_4_modules.json 4 --vmux 0,5,12 --grafana module_map.txt
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from grafana_query import fetch_register_values, load_module_map


CHIP_NUMBER_TO_ID = {1: 12, 2: 13, 3: 14, 4: 15}
ID_TO_CHIP_NUMBER = {v: k for k, v in CHIP_NUMBER_TO_ID.items()}

SCAN_CONSOLE = "/YARR/bin/scanConsole"
CONTROLLER_CONFIG = "/configs/yarr/controller/controller_demi.json"
SCAN_CONFIGS_DIR = "/configs/yarr/scans/itkpixv2"

# Mapping from scan type to JSON filename
SCAN_TYPE_TO_FILE = {
    "digital": "std_digitalscan.json",
    "analog": "std_analogscan.json",
    "noise": "std_noisescan.json",
    "random": "randomtrigger_sourcescan.json",
    "selftrigger": "selftrigger_source.json",
}


def parse_csv_ints(value):
    """Parse a comma-separated string of integers."""
    return [int(x.strip()) for x in value.split(",")]


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def extract_module_name(config_path):
    """Extract module name from config path (first directory component)."""
    parts = config_path.split("/")
    return parts[0] if parts else "unknown"


def load_all_chips(chips_entries, input_dir):
    """
    Load all chip entries and group by module.

    Returns:
        list of dicts: [{
            'module': str,
            'path': str (absolute),
            'chip_id': int,
            'chip_name': str,
            'chip_number': int or None
        }, ...]
    """
    chips = []
    for entry in chips_entries:
        config_rel = entry["config"]
        module_name = extract_module_name(config_rel)
        chip_json_path = os.path.abspath(os.path.join(input_dir, config_rel))
        chip_data = load_json(chip_json_path)
        chip_id = chip_data["ITKPIXV2"]["Parameter"]["ChipId"]
        chip_name = chip_data["ITKPIXV2"]["Parameter"]["Name"]
        chip_number = ID_TO_CHIP_NUMBER.get(chip_id)

        chips.append({
            'module': module_name,
            'path': chip_json_path,
            'chip_id': chip_id,
            'chip_name': chip_name,
            'chip_number': chip_number
        })
    return chips


def set_monitor(chip_json_path, monitor_v, monitor_i):
    """Set MonitorV and MonitorI in a chip JSON file via text replacement."""
    with open(chip_json_path, "r") as f:
        text = f.read()

    text = re.sub(r'("MonitorV"\s*:\s*)\d+', rf'\g<1>{monitor_v}', text)
    text = re.sub(r'("MonitorI"\s*:\s*)\d+', rf'\g<1>{monitor_i}', text)

    with open(chip_json_path, "w") as f:
        f.write(text)


def run_config(input_json, max_retries=3):
    """Run scanConsole for configuration only (blocking)."""
    cmd = [SCAN_CONSOLE, "-r", CONTROLLER_CONFIG, "-c", input_json, "-o", "/dev/null"]

    for attempt in range(1, max_retries + 1):
        print(f"  Running config (attempt {attempt}/{max_retries}): {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

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
    return None


def run_scan_with_callback(input_json, scan_type, on_scan_started, max_retries=3):
    """
    Run scanConsole with a scan config. Monitors stdout for "Run Scan" —
    once detected, waits 5 seconds then calls on_scan_started().
    After the process finishes, checks for errors and retries if needed.

    Args:
        on_scan_started: callback function invoked 5s after "Run Scan" appears.
    """
    scan_config = os.path.join(SCAN_CONFIGS_DIR, SCAN_TYPE_TO_FILE[scan_type])
    cmd = [SCAN_CONSOLE, "-r", CONTROLLER_CONFIG, "-c", input_json,
           "-s", scan_config, "-o", "/dev/null"]

    for attempt in range(1, max_retries + 1):
        print(f"  Running {scan_type} scan (attempt {attempt}/{max_retries}): {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        callback_called = False
        output_lines = []

        for line in proc.stdout:
            output_lines.append(line)
            if not callback_called and "Run Scan" in line:
                print(f"  Scan started, waiting 5 seconds before Grafana query...")
                time.sleep(5)
                on_scan_started()
                callback_called = True

        proc.wait()
        output = "".join(output_lines)

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
            print(f"  {scan_type.capitalize()} scan completed successfully at {timestamp}.")
            return timestamp
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Measure vmux and/or imux register values for ITkPixV2 chips.",
        epilog="""
Examples:
  Single module - both vmux and imux:
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5,12 --imux 0,5,12

  Only vmux measurements:
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5,12

  Only imux measurements:
    python3 change_registers.py /configs/modules/20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --imux 0,5,12

  Multi-module (chip position 4 across all modules):
    python3 change_registers.py /configs/modules/SP_4_modules.json 4 --vmux 0,5,12 --imux 0,5,12

  With dedicated scan type (digital scan instead of simple config):
    python3 change_registers.py module.json 1,2 --vmux 0,5 --scan-type digital

  Available scan types: digital, analog, noise, random, selftrigger
        """
    )
    parser.add_argument("input_json", help="Path to connectivity JSON (single or multi-module)")
    parser.add_argument(
        "chip_numbers",
        help="Comma-separated chip positions to measure (1-4). Applied to each module.",
    )
    parser.add_argument(
        "--vmux",
        default=None,
        help="Comma-separated vmux values (0-63). Optional if --imux is specified."
    )
    parser.add_argument(
        "--imux",
        default=None,
        help="Comma-separated imux values (0-63). Optional if --vmux is specified."
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Output filename (default: registers_info_{datetime}.txt)",
    )
    parser.add_argument(
        "--scan-type",
        choices=["digital", "analog", "noise", "random", "selftrigger"],
        default=None,
        help="Optional scan type to run instead of simple configuration. "
             "Uses scan configs from /configs/yarr/scans/itkpixv2/",
    )
    parser.add_argument(
        "--grafana",
        default=None,
        help="Path to module mapping file (e.g. module_map.txt). "
             "Each line: <slot> <module_serial> (e.g. 'M1 20UPGM23211190'). "
             "When provided, Grafana is queried after each scan and the "
             "register value is appended to the output for the matching module.",
    )
    args = parser.parse_args()

    # Parse arguments
    chip_numbers = parse_csv_ints(args.chip_numbers)
    vmux_values = parse_csv_ints(args.vmux) if args.vmux else None
    imux_values = parse_csv_ints(args.imux) if args.imux else None

    # Validate that at least one of vmux or imux is specified
    if vmux_values is None and imux_values is None:
        sys.exit("Error: At least one of --vmux or --imux must be specified.")

    # Validate chip numbers
    for cn in chip_numbers:
        if cn not in CHIP_NUMBER_TO_ID:
            sys.exit(f"Error: chip number {cn} is invalid. Must be 1-4.")

    # Validate vmux/imux ranges
    if vmux_values:
        for v in vmux_values:
            if not 0 <= v <= 63:
                sys.exit(f"Error: vmux value {v} out of range (0-63).")
    if imux_values:
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

    # Load connectivity and all chips
    connectivity = load_json(input_json_path)
    all_chips = load_all_chips(connectivity["chips"], input_dir)

    # Find unique modules
    modules = sorted(set(c['module'] for c in all_chips))
    print(f"Found {len(modules)} module(s): {', '.join(modules)}")
    print(f"Total chips: {len(all_chips)}")

    # Validate that at least one requested chip position exists
    target_chips = [c for c in all_chips if c['chip_number'] in chip_numbers]
    if not target_chips:
        sys.exit(f"Error: No chips found at position(s) {chip_numbers}")

    print(f"Target chip positions: {chip_numbers}")
    for c in target_chips:
        print(f"  [{c['module']}] {c['chip_name']} (position {c['chip_number']})")

    # Load Grafana module map if provided
    module_to_slot = None
    if args.grafana:
        module_to_slot = load_module_map(args.grafana)
        print(f"\nGrafana module mapping loaded from {args.grafana}:")
        for mod, slot in sorted(module_to_slot.items(), key=lambda x: x[1]):
            print(f"  {slot} -> {mod}")

    if args.scan_type:
        print(f"\nScan type: {args.scan_type} (using {SCAN_TYPE_TO_FILE[args.scan_type]})")
        print("Running dedicated scan instead of simple configuration.")

    rows = []

    # in the same module simultaneously
    for chip_num in chip_numbers:
        # Find chips at this position across all modules
        chips_at_position = [c for c in all_chips if c['chip_number'] == chip_num]
        other_chips_for_position = [c for c in all_chips if c['chip_number'] != chip_num]

        if not chips_at_position:
            print(f"\nWarning: No chips found at position {chip_num}, skipping.")
            continue

        # --- vmux measurements for this chip position ---
        if vmux_values:
            for vmux in vmux_values:
                print(f"\n=== vmux={vmux} for chip position {chip_num} across all modules ===")

                # Set chips at this position: MonitorV=vmux, MonitorI=63
                for c in chips_at_position:
                    print(f"  [{c['module']}] Setting {c['chip_name']}: MonitorV={vmux}, MonitorI=63")
                    set_monitor(c['path'], vmux, 63)

                # Set all other chips: MonitorV=63, MonitorI=63
                for c in other_chips_for_position:
                    set_monitor(c['path'], 63, 63)

                # Run and query Grafana
                grafana_values = [None]  # mutable container for callback

                def query_grafana():
                    if module_to_slot:
                        result = fetch_register_values()
                        if result:
                            print(f"  [Grafana] values: {result}")
                            grafana_values[0] = result

                if args.scan_type:
                    # With scan: query Grafana 5s after "Run Scan" appears
                    timestamp = run_scan_with_callback(
                        args.input_json, args.scan_type, query_grafana)
                else:
                    # Config only: wait 10s after config completes, then query
                    timestamp = run_config(args.input_json)
                    print("  Waiting 10 seconds...")
                    time.sleep(10)
                    query_grafana()

                # Record entry for each chip at this position
                for c in chips_at_position:
                    gval = None
                    if grafana_values[0] and module_to_slot:
                        slot = module_to_slot.get(c['module'])
                        if slot:
                            gval = grafana_values[0].get(slot)
                    rows.append((c['module'], c['chip_name'], c['chip_number'], "vmux", vmux, timestamp, gval))

        # --- imux measurements for this chip position ---
        if imux_values:
            for imux in imux_values:
                print(f"\n=== imux={imux} for chip position {chip_num} across all modules ===")

                # Set chips at this position: MonitorV=1, MonitorI=imux
                for c in chips_at_position:
                    print(f"  [{c['module']}] Setting {c['chip_name']}: MonitorV=1, MonitorI={imux}")
                    set_monitor(c['path'], 1, imux)

                # Set all other chips: MonitorV=63, MonitorI=63
                for c in other_chips_for_position:
                    set_monitor(c['path'], 63, 63)

                # Run and query Grafana
                grafana_values = [None]

                def query_grafana():
                    if module_to_slot:
                        result = fetch_register_values()
                        if result:
                            print(f"  [Grafana] values: {result}")
                            grafana_values[0] = result

                if args.scan_type:
                    timestamp = run_scan_with_callback(
                        args.input_json, args.scan_type, query_grafana)
                else:
                    timestamp = run_config(args.input_json)
                    print("  Waiting 10 seconds...")
                    time.sleep(10)
                    query_grafana()

                # Record entry for each chip at this position
                for c in chips_at_position:
                    gval = None
                    if grafana_values[0] and module_to_slot:
                        slot = module_to_slot.get(c['module'])
                        if slot:
                            gval = grafana_values[0].get(slot)
                    rows.append((c['module'], c['chip_name'], c['chip_number'], "imux", imux, timestamp, gval))

    # Sort by module, chip number, reg type, value
    rows.sort(key=lambda x: (x[0], x[2], x[3], x[4]))

    # Write output table
    header = f"{'Module':<20} {'ChipName':<15} {'ChipNum':<8} {'RegType':<8} {'RegValue':<8} {'Timestamp':<20} {'GrafanaVal':<12}"
    sep = "-" * len(header)

    with open(output_file, "w") as f:
        f.write(header + "\n")
        f.write(sep + "\n")
        for module, name, cn, rtype, rval, ts, gval in rows:
            gval_str = str(gval) if gval is not None else "N/A"
            f.write(f"{module:<20} {name:<15} {cn:<8} {rtype:<8} {rval:<8} {ts:<20} {gval_str:<12}\n")

    print(f"\n{'='*60}")
    print(f"Results written to {output_file}")
    print(f"Total measurements: {len(rows)}")


if __name__ == "__main__":
    main()
