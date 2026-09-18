#!/usr/bin/env python3
"""Create a cleaned, long-format SPX options CSV from OptionsDX downloads.

The OptionsDX files contain one row per quote/strike/expiration with call and
put fields side by side.  This script writes one row per option instead.

Example:
    python scripts/clean_optionsdx.py
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, TextIO


OUTPUT_COLUMNS = [
    "quote_unixtime",
    "quote_readtime",
    "quote_date",
    "quote_time_hours",
    "underlying_last",
    "expire_date",
    "expire_unixtime",
    "dte",
    "option_type",
    "strike",
    "bid",
    "ask",
    "mid",
    "spread_pct",
    "last",
    "iv",
    "volume",
    "delta",
    "gamma",
    "vega",
    "theta",
    "rho",
    "strike_distance",
    "strike_distance_pct",
]

NUMERIC_COLUMNS = {
    "quote_unixtime", "quote_time_hours", "underlying_last", "expire_unixtime",
    "dte", "strike", "bid", "ask", "last", "iv", "volume", "delta",
    "gamma", "vega", "theta", "rho", "strike_distance", "strike_distance_pct",
}


def archive_members(archive: Path) -> list[str]:
    """Return data-file members in a 7z archive."""
    result = subprocess.run(
        ["7z", "l", "-slt", str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )
    members = []
    for line in result.stdout.splitlines():
        if line.startswith("Path = "):
            member = line[7:].strip()
            if member.lower().endswith((".txt", ".csv")):
                members.append(member)
    return members


def input_streams(input_dir: Path) -> Iterable[tuple[str, TextIO]]:
    """Yield (source name, text stream) for raw CSV/TXT files in archives."""
    seven_zip = shutil.which("7z")
    paths = sorted(input_dir.glob("*"))
    for path in paths:
        if path.suffix.lower() in {".txt", ".csv"}:
            yield path.name, path.open("r", newline="", encoding="utf-8-sig")
        elif path.suffix.lower() == ".7z":
            if not seven_zip:
                raise RuntimeError("7z is required to read .7z files. Install it with: brew install p7zip")
            for member in archive_members(path):
                process = subprocess.Popen(
                    [seven_zip, "x", "-so", str(path), member],
                    stdout=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert process.stdout is not None
                yield f"{path.name}:{member}", process.stdout
                process.stdout.close()
                if process.wait() != 0:
                    raise RuntimeError(f"Could not read {member} from {path}")


def clean_header(header: str) -> str:
    return re.sub(r"[\[\]]", "", header).strip().lower()


def number(value: str | None) -> str:
    """Normalize numeric values while keeping missing values blank."""
    if value is None or not value.strip():
        return ""
    try:
        return format(float(value.strip()), ".12g")
    except ValueError:
        return ""


def text(value: str | None) -> str:
    return "" if value is None else value.strip()


def transform(row: dict[str, str], option_type: str) -> dict[str, str]:
    prefix = "c_" if option_type == "call" else "p_"
    out = {
        "quote_unixtime": text(row.get("quote_unixtime")),
        "quote_readtime": text(row.get("quote_readtime")),
        "quote_date": text(row.get("quote_date")),
        "quote_time_hours": text(row.get("quote_time_hours")),
        "underlying_last": text(row.get("underlying_last")),
        "expire_date": text(row.get("expire_date")),
        "expire_unixtime": text(row.get("expire_unix")),
        "dte": text(row.get("dte")),
        "option_type": option_type,
        "strike": text(row.get("strike")),
        "bid": text(row.get(f"{prefix}bid")),
        "ask": text(row.get(f"{prefix}ask")),
        "last": text(row.get(f"{prefix}last")),
        "iv": text(row.get(f"{prefix}iv")),
        "volume": text(row.get(f"{prefix}volume")),
        "delta": text(row.get(f"{prefix}delta")),
        "gamma": text(row.get(f"{prefix}gamma")),
        "vega": text(row.get(f"{prefix}vega")),
        "theta": text(row.get(f"{prefix}theta")),
        "rho": text(row.get(f"{prefix}rho")),
        "strike_distance": text(row.get("strike_distance")),
        "strike_distance_pct": text(row.get("strike_distance_pct")),
    }
    for key in NUMERIC_COLUMNS:
        out[key] = number(out[key])
    try:
        bid = float(out["bid"])
        ask = float(out["ask"])
        mid = (bid + ask) / 2
        out["mid"] = number(str(mid))
        out["spread_pct"] = number(str((ask - bid) / mid)) if mid > 0 else ""
    except (TypeError, ValueError, ZeroDivisionError):
        out["mid"] = ""
        out["spread_pct"] = ""
    return out


def passes_starter_filter(row: dict[str, str], min_dte: float) -> bool:
    """Apply the initial quality, maturity, moneyness, and delta filters."""
    try:
        return (
            min_dte <= float(row["dte"]) <= 365
            and float(row["strike"]) > 0
            and float(row["underlying_last"]) > 0
            and 0.03 <= float(row["iv"]) <= 2.00
            and float(row["bid"]) > 0
            and float(row["ask"]) > 0
            and float(row["ask"]) >= float(row["bid"])
            and float(row["spread_pct"]) <= 0.50
            and float(row["strike_distance_pct"]) <= 0.20
            and 0.05 <= abs(float(row["delta"])) <= 0.95
        )
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/cleaned/spx_options_2023_filtered.csv"))
    parser.add_argument("--min-dte", type=float, default=3.0, help="Minimum days to expiration (default: 3)")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    total = written = skipped = 0
    with args.output.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for source_name, stream in input_streams(args.input_dir):
            try:
                reader = csv.DictReader(stream)
                reader.fieldnames = [clean_header(h) for h in (reader.fieldnames or [])]
                for source_row in reader:
                    total += 1
                    for option_type in ("call", "put"):
                        cleaned = transform(source_row, option_type)
                        try:
                            dte = float(cleaned["dte"])
                            strike = float(cleaned["strike"])
                        except (TypeError, ValueError):
                            skipped += 1
                            continue
                        if dte <= 0 or strike <= 0:
                            skipped += 1
                            continue
                        if not passes_starter_filter(cleaned, args.min_dte):
                            skipped += 1
                            continue
                        writer.writerow(cleaned)
                        written += 1
            finally:
                stream.close()
            print(f"Processed {source_name}", file=sys.stderr)

    print(f"Wrote {written:,} option rows to {args.output} (source rows: {total:,}; skipped: {skipped:,})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
