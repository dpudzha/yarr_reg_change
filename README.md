# YARR Register Measurement Tool

## Usage

```bash
python3 change_registers.py <input_json> <chip_numbers> <vmux_values> <imux_values> [output_file]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `input_json` | Path to the connectivity JSON file |
| `chip_numbers` | Comma-separated chip numbers (1-4) |
| `vmux_values` | Comma-separated vmux values (0-63) |
| `imux_values` | Comma-separated imux values (0-63) |
| `output_file` | Optional output filename (default: `registers_info_<timestamp>.txt`) |

### Examples

Measure chips 1 and 2 with multiple vmux/imux values:
```bash
python3 change_registers.py 20UPGM23211190/20UPGM23211190_L2_warm.json 1,2 0,5,12 0,5,12
```

Single chip with specific register values:
```bash
python3 change_registers.py config/module.json 3 10 20 output.txt
```

## Output

Results are written to a tab-formatted text file containing:
- Module name
- Chip ID
- Chip number
- Register type (vmux/imux)
- Register value
