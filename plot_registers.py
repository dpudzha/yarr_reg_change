#!/usr/bin/env python3
"""
Plot calibrated register values across x-ray tube currents.

Reads multiple output files from change_registers.py (each taken at a different
x-ray current), extracts CalibratedVal for specified registers, and generates
plots showing how values change with x-ray current.

Usage:
    python3 plot_registers.py registers_info_0uA.txt registers_info_40uA.txt ...
    python3 plot_registers.py registers_info_*uA*.txt
    python3 plot_registers.py --reg-type vmux --reg-values 30,31 registers_info_*.txt
    python3 plot_registers.py --output-dir plots/ registers_info_*.txt
"""

import argparse
import os
import re
import sys
from collections import defaultdict

import matplotlib.pyplot as plt


def extract_current_from_filename(filepath):
    """Extract x-ray tube current (in uA) from filename. Returns int or None."""
    basename = os.path.basename(filepath)
    match = re.search(r'(\d+)\s*uA', basename, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def parse_output_file(filepath):
    """Parse a change_registers.py output file into a list of row dicts."""
    rows = []
    with open(filepath) as f:
        lines = f.readlines()

    if len(lines) < 2:
        return rows

    # Skip header and separator lines
    for line in lines[2:]:
        line = line.rstrip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        try:
            module = parts[0]
            chip_name = parts[1]
            chip_num = int(parts[2])
            reg_type = parts[3]
            reg_value = int(parts[4])
            # RegName can contain spaces, so parse from the right.
            # Last 3 fields: Timestamp, GrafanaVal, CalibratedVal
            # Timestamp matches ISO format; scan from right to find it.
            cal_str = parts[-1]
            gval_str = parts[-2]
            # Find timestamp (ISO-like pattern) scanning from the right
            ts_idx = None
            for i in range(len(parts) - 3, 4, -1):
                if re.match(r'\d{4}-\d{2}-\d{2}', parts[i]):
                    ts_idx = i
                    break
            if ts_idx is None:
                ts_idx = len(parts) - 3
            timestamp = parts[ts_idx]
            # RegName is everything between reg_value and timestamp
            reg_name = " ".join(parts[5:ts_idx])

            cal_val = None
            if cal_str != "N/A":
                cal_val = float(cal_str)

            rows.append({
                'module': module,
                'chip_name': chip_name,
                'chip_num': chip_num,
                'reg_type': reg_type,
                'reg_value': reg_value,
                'reg_name': reg_name,
                'timestamp': timestamp,
                'calibrated_val': cal_val,
            })
        except (ValueError, IndexError):
            continue

    return rows


def parse_register_name(raw_name):
    """Parse register name, extracting optional multiplier from '/NNNNN' suffix.

    Returns (clean_name, multiplier) where multiplier is None if not present.
    E.g. 'Dig. input current/21000' -> ('Dig. input current', 21000)
    """
    match = re.match(r'^(.+?)/(\d+)$', raw_name)
    if match:
        return match.group(1).strip(), int(match.group(2))
    return raw_name, None


def main():
    parser = argparse.ArgumentParser(
        description="Plot calibrated register values across x-ray tube currents."
    )
    parser.add_argument(
        'files', nargs='+',
        help="Output files from change_registers.py (current extracted from filename, e.g. 'registers_info_40uA.txt')"
    )
    parser.add_argument(
        '--reg-type', default='imux',
        help="Register type to plot (default: imux)"
    )
    parser.add_argument(
        '--reg-values', default='30,31',
        help="Comma-separated register values to plot (default: 30,31)"
    )
    parser.add_argument(
        '--output-dir', default='.',
        help="Directory to save plot PNGs (default: current directory)"
    )
    parser.add_argument(
        '--show', action='store_true',
        help="Display plots interactively"
    )
    args = parser.parse_args()

    reg_values = [int(v) for v in args.reg_values.split(',')]
    if len(reg_values) != 2:
        print("Error: exactly 2 register values required for difference plot", file=sys.stderr)
        sys.exit(1)

    reg_lo, reg_hi = sorted(reg_values)

    # Parse all files and associate with x-ray current
    # Key: (module, chip_num, reg_type, reg_value) -> list of (current_uA, calibrated_val)
    data = defaultdict(list)
    files_parsed = 0

    for filepath in args.files:
        current_uA = extract_current_from_filename(filepath)
        if current_uA is None:
            print(f"Warning: could not extract current from '{filepath}', skipping", file=sys.stderr)
            continue

        rows = parse_output_file(filepath)
        if not rows:
            print(f"Warning: no data in '{filepath}', skipping", file=sys.stderr)
            continue

        files_parsed += 1
        for row in rows:
            if row['reg_type'] != args.reg_type:
                continue
            if row['reg_value'] not in reg_values:
                continue
            if row['calibrated_val'] is None:
                continue

            key = (row['module'], row['chip_num'], row['reg_type'], row['reg_value'])
            data[key].append((current_uA, row['calibrated_val']))

    if files_parsed == 0:
        print("Error: no files could be parsed. Check filenames contain a current like '40uA'.", file=sys.stderr)
        sys.exit(1)

    if not data:
        print(f"Error: no {args.reg_type} register {reg_values} data found in files.", file=sys.stderr)
        sys.exit(1)

    # Group by (module, chip_num) to produce one plot each
    # Also collect register names for labeling
    chips = set()
    reg_names = {}  # (module, chip_num, reg_type, reg_value) -> reg_name
    for (module, chip_num, reg_type, reg_value) in data:
        chips.add((module, chip_num))

    # Extract register names from the original parsed data
    for filepath in args.files:
        current_uA = extract_current_from_filename(filepath)
        if current_uA is None:
            continue
        rows = parse_output_file(filepath)
        for row in rows:
            if row['reg_type'] == args.reg_type and row['reg_value'] in reg_values:
                key = (row['module'], row['chip_num'], row['reg_type'], row['reg_value'])
                if key not in reg_names and row['reg_name']:
                    reg_names[key] = row['reg_name']

    os.makedirs(args.output_dir, exist_ok=True)

    y_unit = "mA" if args.reg_type == "imux" else "V"

    for module, chip_num in sorted(chips):
        key_lo = (module, chip_num, args.reg_type, reg_lo)
        key_hi = (module, chip_num, args.reg_type, reg_hi)

        vals_lo = sorted(data.get(key_lo, []))
        vals_hi = sorted(data.get(key_hi, []))

        if not vals_lo and not vals_hi:
            continue

        fig, axes = plt.subplots(1, 3, figsize=(16, 5))
        fig.suptitle(f"{module} — Chip {chip_num}", fontsize=14)

        # Get register names and parse multipliers
        raw_name_lo = reg_names.get(key_lo, f"{args.reg_type}={reg_lo}")
        raw_name_hi = reg_names.get(key_hi, f"{args.reg_type}={reg_hi}")
        name_lo, mult_lo = parse_register_name(raw_name_lo)
        name_hi, mult_hi = parse_register_name(raw_name_hi)

        # Apply multipliers to calibrated values if present
        if mult_lo:
            vals_lo = [(c, v * mult_lo) for c, v in vals_lo]
        if mult_hi:
            vals_hi = [(c, v * mult_hi) for c, v in vals_hi]

        # Plot reg_lo
        if vals_lo:
            currents, cals = zip(*vals_lo)
            axes[0].plot(currents, cals, 'o-', color='tab:blue')
        axes[0].set_title(f"{name_lo}\n({args.reg_type}={reg_lo})")
        axes[0].set_xlabel("X-ray tube current (uA)")
        axes[0].set_ylabel(f"CalibratedVal ({y_unit})")
        axes[0].grid(True, alpha=0.3)

        # Plot reg_hi
        if vals_hi:
            currents, cals = zip(*vals_hi)
            axes[1].plot(currents, cals, 'o-', color='tab:orange')
        axes[1].set_title(f"{name_hi}\n({args.reg_type}={reg_hi})")
        axes[1].set_xlabel("X-ray tube current (uA)")
        axes[1].set_ylabel(f"CalibratedVal ({y_unit})")
        axes[1].grid(True, alpha=0.3)

        # Difference plot (reg_lo - reg_hi)
        lo_dict = dict(vals_lo)
        hi_dict = dict(vals_hi)
        common_currents = sorted(set(lo_dict) & set(hi_dict))
        if common_currents:
            diffs = [lo_dict[c] - hi_dict[c] for c in common_currents]
            axes[2].plot(common_currents, diffs, 's-', color='tab:green')
        axes[2].set_title(f"{name_lo} − {name_hi}\n({args.reg_type}={reg_lo} − {args.reg_type}={reg_hi})")
        axes[2].set_xlabel("X-ray tube current (uA)")
        axes[2].set_ylabel(f"Difference ({y_unit})")
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()

        out_name = f"{module}_Chip{chip_num}_{args.reg_type}_{reg_lo}_{reg_hi}.png"
        out_path = os.path.join(args.output_dir, out_name)
        fig.savefig(out_path, dpi=150)
        print(f"Saved: {out_path}")

        if args.show:
            plt.show()
        else:
            plt.close(fig)

    print(f"\nDone. Parsed {files_parsed} files, generated plots for {len(chips)} chip(s).")


if __name__ == "__main__":
    main()
