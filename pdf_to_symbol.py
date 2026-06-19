#!/usr/bin/env python3
"""
pdf_to_symbol.py — DatasheetVend KiCad Symbol Generator CLI
Version: 1.0.0

Queries the DatasheetVend Pinout API for a completed extraction job
and generates a KiCad v6+ .kicad_sym schematic symbol file.

Requires: Python 3.8+ — no external dependencies (stdlib only).

Usage:
    python pdf_to_symbol.py --job-id JOB_ID --session-id SESSION_TOKEN [options]
    python pdf_to_symbol.py --pinout-file payload.json [options]

See README.md for full documentation.
"""

import argparse
import json
import sys
from http.client import HTTPSConnection, HTTPConnection
from urllib.parse import urlparse

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Pin Type Mapping
# ---------------------------------------------------------------------------
# Maps DatasheetVend pin_type strings to KiCad v6 electrical type keywords.

PIN_TYPE_MAP: dict[str, str] = {
    "POWER":         "power_in",
    "GROUND":        "power_in",
    "INPUT":         "input",
    "OUTPUT":        "output",
    "BIDIRECTIONAL": "bidirectional",
    "IO":            "bidirectional",
    "RESET":         "input",
    "CLOCK":         "input",
    "ANALOG":        "passive",
    "NC":            "no_connect",
    "RESERVED":      "no_connect",
    "UNKNOWN":       "bidirectional",
}

# Heuristic patterns used to infer type when pin_type is missing or null.
_POWER_PREFIXES  = ("VDD", "VCC", "VBAT", "VDDA", "VDDB", "VREF", "AVCC",
                    "PVDD", "VIO", "VCORE", "VBUS", "VIN", "VSUP", "VCAP")
_GROUND_PREFIXES = ("GND", "VSS", "AGND", "DGND", "PGND", "AVSS", "EP",
                    "PAD")
_NC_EXACT        = {"NC", "N/C", "N.C.", "DNC"}


def _infer_kicad_type_from_name(name: str) -> str:
    """Infer KiCad pin type from pin name when pin_type is absent."""
    u = name.upper().strip()
    if u in _NC_EXACT:
        return "no_connect"
    if any(u == p or u.startswith(p) for p in _POWER_PREFIXES):
        return "power_in"
    if any(u == p or u.startswith(p) for p in _GROUND_PREFIXES):
        return "power_in"
    return "bidirectional"


def _resolve_kicad_type(pin: dict) -> str:
    """Return the KiCad electrical type for a DatasheetVend pin object."""
    raw = pin.get("pin_type") or pin.get("type") or ""
    normalized = str(raw).upper().strip()
    if normalized in PIN_TYPE_MAP:
        return PIN_TYPE_MAP[normalized]
    name = str(pin.get("name") or pin.get("pin_name") or "")
    return _infer_kicad_type_from_name(name)


def _pin_number(pin: dict) -> str:
    return str(pin.get("number") or pin.get("pin_number") or "?")


def _pin_name(pin: dict) -> str:
    return str(pin.get("name") or pin.get("pin_name") or "~")


def _esc(s: str) -> str:
    """Escape a string for KiCad s-expression double-quoted values."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# KiCad .kicad_sym Generator
# ---------------------------------------------------------------------------

def generate_kicad_sym(part_name: str, package_info: str, pins: list) -> str:
    """
    Generate a KiCad v6+ .kicad_sym s-expression string.

    Layout strategy:
    - Even-indexed pins → left side  (angle=0,   pointing rightward into body)
    - Odd-indexed pins  → right side (angle=180, pointing leftward into body)
    - Pins are spaced 2.54 mm apart vertically
    - A bounding rectangle is drawn for the body
    """
    left_pins  = [p for i, p in enumerate(pins) if i % 2 == 0]
    right_pins = [p for i, p in enumerate(pins) if i % 2 == 1]

    n_rows     = max(len(left_pins), len(right_pins), 1)
    body_h     = n_rows * 2.54 + 2.54
    body_w     = 10.16
    half_h     = body_h / 2.0
    half_w     = body_w / 2.0
    pin_len    = 5.08
    x_L        = -(half_w + pin_len)
    x_R        =  (half_w + pin_len)
    y_start    = half_h - 1.27

    name_esc    = _esc(part_name)
    pkg_comment = f"  ; Package: {package_info}" if package_info else ""

    lines: list[str] = []
    lines.append("(kicad_symbol_lib (version 20220914) (generator datasheetvend_pdf_to_symbol)")
    lines.append(f'  (symbol "{name_esc}" (in_bom yes) (on_board yes)')
    if pkg_comment:
        lines.append(pkg_comment)
    lines.append("    (pin_names (offset 1.016) hide)")
    lines.append(f'    (symbol "{name_esc}_0_1"')

    lines.append(f"      (rectangle (start {-half_w:.3f} {half_h:.3f}) (end {half_w:.3f} {-half_h:.3f})")
    lines.append( "        (stroke (width 0) (type default))")
    lines.append( "        (fill (type background))")
    lines.append( "      )")

    def emit_pin(pin: dict, x: float, angle: int, row_index: int) -> None:
        y = y_start - row_index * 2.54
        ktype = _resolve_kicad_type(pin)
        pname = _esc(_pin_name(pin))
        pnum  = _esc(_pin_number(pin))
        lines.append(f'      (pin {ktype} line (at {x:.3f} {y:.3f} {angle}) (length {pin_len:.3f})')
        lines.append(f'        (name "{pname}" (effects (font (size 1.016 1.016))))')
        lines.append(f'        (number "{pnum}" (effects (font (size 1.016 1.016))))')
        lines.append( '      )')

    for i, pin in enumerate(left_pins):
        emit_pin(pin, x_L, 0, i)

    for i, pin in enumerate(right_pins):
        emit_pin(pin, x_R, 180, i)

    lines.append("    )")
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# API / File I/O
# ---------------------------------------------------------------------------

def _http_get_json(host: str, path: str) -> dict:
    """Perform a GET request and return parsed JSON. Exits on any error."""
    parsed   = urlparse(host)
    scheme   = parsed.scheme or "https"
    hostname = parsed.netloc or parsed.path

    try:
        if scheme == "http":
            conn = HTTPConnection(hostname, timeout=30)
        else:
            conn = HTTPSConnection(hostname, timeout=30)

        conn.request(
            "GET", path,
            headers={
                "Accept":     "application/json",
                "User-Agent": f"datasheetvend-pdf-to-symbol/{__version__}",
            },
        )
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
    except Exception as exc:
        _die(f"Connection failed to {host}: {exc}")

    if resp.status != 200:
        _err(f"API returned HTTP {resp.status}:")
        try:
            _err(json.dumps(json.loads(body), indent=2))
        except Exception:
            _err(body)
        sys.exit(1)

    try:
        return json.loads(body)
    except Exception as exc:
        _die(f"Could not parse API response as JSON: {exc}")


def fetch_pinout(host: str, job_id: str, session_id: str) -> dict:
    path = f"/api/v1/jobs/{job_id}/pinout?session_id={session_id}"
    return _http_get_json(host, path)


def load_local_file(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        _die(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON in {path}: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _die(msg: str) -> None:
    _err(f"[ERROR] {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pdf_to_symbol.py",
        description=(
            "DatasheetVend KiCad Symbol Generator\n\n"
            "Queries the DatasheetVend Pinout API for a completed extraction job\n"
            "and generates a KiCad v6+ .kicad_sym schematic symbol file.\n\n"
            "Requires Python 3.8+ with no external dependencies."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Fetch from API and write to file\n"
            "  python pdf_to_symbol.py \\\n"
            "      --job-id abc123 \\\n"
            "      --session-id eyJhb... \\\n"
            "      --output STM32H743ZIT6.kicad_sym \\\n"
            "      --verbose\n\n"
            "  # Offline mode: use a downloaded pinout JSON\n"
            "  python pdf_to_symbol.py --pinout-file payload.json --dry-run\n\n"
            "  # Strict mode: abort if data is not flagged CAD-safe\n"
            "  python pdf_to_symbol.py --job-id abc123 --session-id eyJhb... --strict\n"
        ),
    )

    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--job-id",
        metavar="JOB_ID",
        help="DatasheetVend job ID (from your result page URL or dashboard)",
    )
    src.add_argument(
        "--pinout-file",
        metavar="PATH",
        help="Path to a local pinout JSON file (offline mode, skips API call)",
    )

    parser.add_argument(
        "--session-id",
        metavar="TOKEN",
        help=(
            "Session ID (bypass token). Found in your result page URL:\n"
            "  https://app.datasheetvend.com/result?session_id=<TOKEN>\n"
            "Required when using --job-id."
        ),
    )
    parser.add_argument(
        "--host",
        default="https://app.datasheetvend.com",
        metavar="URL",
        help="API host base URL (default: https://app.datasheetvend.com)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Output .kicad_sym file path (default: <part_number>.kicad_sym)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Abort with exit code 2 if the extraction is NOT flagged as\n"
            "safe_for_cad_symbol_seed. Recommended for automated pipelines."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated .kicad_sym content to stdout; do not write a file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print a human-readable extraction report to stderr.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    if args.job_id and not args.session_id:
        parser.error("--session-id is required when using --job-id.")
    if not args.job_id and not args.pinout_file:
        parser.error("Provide either --job-id + --session-id, or --pinout-file.")

    # Load payload
    if args.pinout_file:
        if args.verbose:
            _err(f"[INFO] Loading local file: {args.pinout_file}")
        raw = load_local_file(args.pinout_file)
    else:
        if args.verbose:
            _err(f"[INFO] Fetching pinout for job {args.job_id} from {args.host} …")
        raw = fetch_pinout(args.host, args.job_id, args.session_id)

    # Unwrap payload: detect PinoutApiPayload vs live API envelope
    if not isinstance(raw, dict):
        _die("Unexpected payload structure. Expected a JSON object.")
    if raw.get("file_kind") == "pinout.api_payload":
        payload: dict = raw
    elif isinstance(raw.get("data"), dict):
        payload: dict = raw["data"]
    else:
        _die(
            "Could not identify payload type. Expected either a PinoutApiPayload\n"
            '  (with "file_kind": "pinout.api_payload") or the live API envelope\n'
            '  (with a "data" key containing the payload).'
        )

    # Safety gate
    machine_use     = payload.get("machine_use") or {}
    safe_for_cad    = machine_use.get("safe_for_cad_symbol_seed", False)
    status_block    = payload.get("status") or {}
    delivery_status = status_block.get("delivery_status", "unknown")
    human_review    = status_block.get("human_review_required", False)

    if not safe_for_cad:
        _err(
            "[WARNING] safe_for_cad_symbol_seed is FALSE.\n"
            "          This extraction may contain unresolved warnings or ambiguities.\n"
            "          Review all warnings below before using this symbol in production.\n"
            f"          delivery_status={delivery_status!r}  "
            f"human_review_required={human_review}"
        )
        if args.strict:
            _err("[ABORT] --strict mode: refusing to generate symbol.")
            sys.exit(2)

    # Surface extraction warnings
    data_block: dict = payload.get("data") or {}
    warnings: list   = data_block.get("warnings") or []
    if warnings:
        _err("\n[Extraction Warnings]")
        for w in warnings:
            _err(f"  ⚠  {w}")
        _err("")

    # Extract identity, package, and pins
    identity  = payload.get("identity") or {}
    component = identity.get("component") or {}
    package   = identity.get("package")   or {}
    flat      = payload.get("flat_parameters") or {}

    part_name = (
        (component.get("manufacturer_part_number") if isinstance(component, dict) else None)
        or "UNKNOWN_PART"
    )
    pkg_variant = (
        flat.get("package_variant")
        or (package.get("variant") if isinstance(package, dict) else None)
        or flat.get("package_family")
        or (package.get("family") if isinstance(package, dict) else None)
        or ""
    )

    pins: list = data_block.get("pins") or []

    # Verbose report
    if args.verbose:
        _err("── DatasheetVend Extraction Report ─────────────────────────")
        _err(f"  Part Number  : {part_name}")
        _err(f"  Package      : {pkg_variant or 'unknown'}")
        _err(f"  Total Pins   : {flat.get('total_pins', len(pins))}")
        _err(f"  Power Pins   : {flat.get('power_pins_count', '?')}")
        _err(f"  Ground Pins  : {flat.get('ground_pins_count', '?')}")
        _err(f"  I/O Pins     : {flat.get('io_pins_count', '?')}")
        _err(f"  Analog Pins  : {flat.get('analog_pins_count', '?')}")
        _err(f"  Status       : {delivery_status}")
        _err(f"  CAD-Safe     : {safe_for_cad}")
        _err(f"  Review Req.  : {human_review}")
        _err("────────────────────────────────────────────────────────────")
        _err("")

    if not pins:
        _die("No pins found in the pinout payload. Cannot generate a symbol.")

    sym_content = generate_kicad_sym(part_name, pkg_variant, pins)

    if args.dry_run:
        print(sym_content, end="")
        return

    output_path = args.output or f"{part_name}.kicad_sym"
    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(sym_content)
    except IOError as exc:
        _die(f"Failed to write {output_path}: {exc}")

    _err(f"[OK] Symbol written → {output_path}  ({len(pins)} pins)")
    if human_review:
        _err("[NOTE] Human review is recommended before using this symbol in production.")


if __name__ == "__main__":
    main()
