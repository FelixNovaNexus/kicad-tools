# DatasheetVend — KiCad Symbol Generator

> Generate KiCad v6+ schematic symbols directly from PDF datasheets.

A self-contained Python CLI tool that queries the **[DatasheetVend](https://app.datasheetvend.com) Pinout API** and outputs a production-ready `.kicad_sym` file — with zero external dependencies.

---

## Requirements

- Python 3.8 or higher
- A completed DatasheetVend extraction job (status: `COMPLETED`)
- Your job ID and session token (see [Authentication](#authentication))

No `pip install` required. This script uses only the Python standard library.

---

## Quick Start

```bash
python pdf_to_symbol.py \
  --job-id YOUR_JOB_ID \
  --session-id YOUR_SESSION_TOKEN \
  --output STM32H743ZIT6.kicad_sym \
  --verbose
```

The script will:
1. Fetch the extraction result from the DatasheetVend API
2. Print a human-readable summary and any extraction warnings to `stderr`
3. Write the `.kicad_sym` file, ready to load directly in KiCad 6 or 7

---

## Authentication

DatasheetVend uses a **session ID (bypass token)** for programmatic API access.

**Where to find it:**

After your extraction completes, your result page URL contains the token:

```
https://app.datasheetvend.com/result?session_id=eyJhbGciOi...
```

Copy the value after `session_id=` and pass it to `--session-id`.

> The session token is scoped to your job ID. It cannot be used to access other users’ jobs.

---

## All Options

| Flag | Description |
|---|---|
| `--job-id JOB_ID` | DatasheetVend job ID |
| `--session-id TOKEN` | Session ID from your result page URL |
| `--pinout-file PATH` | Use a local pinout JSON file (offline mode) |
| `--host URL` | API host (default: `https://app.datasheetvend.com`) |
| `--output FILE` | Output file path (default: `<part_number>.kicad_sym`) |
| `--strict` | Abort (exit 2) if the data is not flagged as CAD-safe |
| `--dry-run` | Print symbol to stdout instead of writing a file |
| `--verbose` | Print extraction summary and warnings report |
| `--version` | Print version and exit |

---

## The `safe_for_cad_symbol_seed` Flag

Every DatasheetVend pinout payload includes a machine-use safety flag:

```json
"machine_use": {
  "safe_for_cad_symbol_seed": true
}
```

This flag is set by the extraction engine based on confidence scores, warning counts, and review decisions. The CLI behavior:

| Flag Value | `--strict` mode | Default mode |
|---|---|---|
| `true` | Proceeds normally | Proceeds normally |
| `false` | **Aborts with exit code 2** | Prints warning, continues |

**Recommended for automated CI/CD pipelines:** always use `--strict` to prevent a symbol with unresolved extraction ambiguities from entering your library.

---

## Offline / Dev Mode

You can test the script without making an API call by pointing it at a local JSON file.

```bash
# Download a pinout payload from the API once
curl "https://app.datasheetvend.com/api/v1/jobs/JOB_ID/pinout?session_id=TOKEN" \
  > payload.json

# Run the script against the local file
python pdf_to_symbol.py \
  --pinout-file payload.json \
  --dry-run
```

The `--pinout-file` flag accepts both:
- The full API response (`{ "data": { ... } }`)
- A raw `PinoutApiPayload` object directly

---

## Example Output

```
(kicad_symbol_lib (version 20220914) (generator datasheetvend_pdf_to_symbol)
  (symbol "STM32H743ZIT6" (in_bom yes) (on_board yes)
    ; Package: LQFP-144
    (pin_names (offset 1.016) hide)
    (symbol "STM32H743ZIT6_0_1"
      (rectangle (start -5.080 185.420) (end 5.080 -185.420)
        (stroke (width 0) (type default))
        (fill (type background))
      )
      (pin power_in line (at -10.160 184.150 0) (length 5.080)
        (name "VDD" (effects (font (size 1.016 1.016))))
        (number "1" (effects (font (size 1.016 1.016))))
      )
      ...
    )
  )
)
```

Load in KiCad via **File → Add Library** or place it in your project `libs/` folder.

---

## Pin Type Mapping

| DatasheetVend `pin_type` | KiCad Electrical Type |
|---|---|
| `POWER` | `power_in` |
| `GROUND` | `power_in` |
| `INPUT` | `input` |
| `OUTPUT` | `output` |
| `BIDIRECTIONAL` / `IO` | `bidirectional` |
| `RESET` | `input` |
| `CLOCK` | `input` |
| `ANALOG` | `passive` |
| `NC` / `RESERVED` | `no_connect` |
| Unknown / missing | `bidirectional` (with name-based heuristic) |

When `pin_type` is absent, the script infers the type from the pin name (e.g., `VDD` → `power_in`, `GND` → `power_in`, `NC` → `no_connect`).

---

## Important Notes

1. **This script generates a seed symbol.** Always review the output in KiCad before committing it to your library.
2. **Extraction warnings are surfaced to stderr.** Any warnings emitted by the DatasheetVend engine are printed before the symbol is generated. Read them.
3. **BGA and grid-array packages** use alphanumeric pin designators (`A1`, `B2`). KiCad supports these natively.
4. **The script never invents data.** If a field is absent in the API payload, it defaults safely.

---

## Integration with CI/CD

```bash
#!/bin/bash
set -e

python pdf_to_symbol.py \
  --job-id "$DATASHEETVEND_JOB_ID" \
  --session-id "$DATASHEETVEND_SESSION_ID" \
  --output "libs/${PART_NUMBER}.kicad_sym" \
  --strict \
  --verbose

echo "Symbol generated. Running KiCad DRC..."
```

---

## API Reference

This script consumes `GET /api/v1/jobs/[id]/pinout`.

Full API documentation: [https://app.datasheetvend.com/api/v1/openapi](https://app.datasheetvend.com/api/v1/openapi)

---

## License

MIT
