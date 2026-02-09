# YARR Register Measurement Tool

## Usage

```bash
python3 change_registers.py <input_json> <chip_numbers> [--vmux <values>] [--imux <values>] [--scan-type TYPE] [output_file]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `input_json` | Path to connectivity JSON (single-module or multi-module) |
| `chip_numbers` | Comma-separated chip positions to measure (1-4) |
| `--vmux` | Comma-separated vmux values (0-63). Optional if `--imux` is specified |
| `--imux` | Comma-separated imux values (0-63). Optional if `--vmux` is specified |
| `--scan-type` | Optional scan type: `digital`, `analog`, `noise`, `random`, `selftrigger` |
| `--grafana` | Path to module mapping file for Grafana readback (e.g., `module_map.txt`) |
| `output_file` | Optional output filename (default: `registers_info_<timestamp>.txt`) |

At least one of `--vmux` or `--imux` must be specified.

### Single Module Examples

Measure chips 1 and 2 with both vmux and imux:
```bash
python3 change_registers.py 20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5,12 --imux 0,5,12
```

Only vmux measurements:
```bash
python3 change_registers.py 20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 --vmux 0,5,12
```

### Multi-Module Examples

When using a multi-module connectivity file (e.g., `SP_4_modules.json`), the specified chip position is configured across **all** modules simultaneously, and one scan is run per register value.

Measure chip position 4 across all modules:
```bash
python3 change_registers.py SP_4_modules.json 4 --vmux 0,5,12 --imux 0,5,12
```

Measure chip positions 1 and 2 across all modules with custom output:
```bash
python3 change_registers.py SP_4_modules.json 1,2 --vmux 10 --imux 20 my_output.txt
```

### Running Scans

By default, the tool runs a simple configuration via `scanConsole`. Use `--scan-type` to run a dedicated scan instead:

```bash
# Run a digital scan after each register configuration
python3 change_registers.py module.json 1,2 --vmux 0,5 --scan-type digital

# Run a self-trigger scan
python3 change_registers.py module.json 1 --imux 10 --scan-type selftrigger
```

Available scan types: `digital`, `analog`, `noise`, `random`, `selftrigger`.

## Output

Results are written to a tab-formatted text file containing:
- Module name
- Chip name
- Chip number
- Register type (vmux/imux)
- Register value
- Register name (human-readable description from `register_map.json`)
- Timestamp
- Grafana value (when `--grafana` is used, otherwise N/A)
- Calibrated value (when `--grafana` is used, otherwise N/A)
