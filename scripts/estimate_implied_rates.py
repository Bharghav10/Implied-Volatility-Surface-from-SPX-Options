#!/usr/bin/env python3
"""Estimate SPX option-implied rates using put-call parity regressions.

For each quote date and expiration, this script regresses:

    call_mid - put_mid = intercept + slope * strike

The estimated discount factor is -slope and the continuously compounded
annualized rate is -log(discount_factor) / T, where T = DTE / 365.

Examples:
    python3 scripts/estimate_implied_rates.py
    python3 scripts/estimate_implied_rates.py --quote-date 2023-01-04
"""

from __future__ import annotations

import argparse
import csv
import html
import math
from collections import defaultdict
from pathlib import Path


def to_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def estimate_group(pairs, min_pairs: int, min_r2: float) -> dict:
    """Estimate OLS coefficients from (strike, call_mid, put_mid) tuples."""
    usable = [
        (strike, call, put)
        for strike, call, put in pairs
        if call > 0 and put > 0
    ]
    n = len(usable)
    result = {
        "n_pairs": n,
        "intercept": math.nan,
        "slope": math.nan,
        "discount_factor": math.nan,
        "forward": math.nan,
        "implied_rate": math.nan,
        "implied_rate_pct": math.nan,
        "r_squared": math.nan,
        "accepted": False,
    }
    if n < min_pairs:
        return result

    xs = [strike for strike, _, _ in usable]
    ys = [call - put for _, call, put in usable]
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_yy = sum(y * y for y in ys)
    denominator = n * sum_xx - sum_x * sum_x
    if denominator <= 0:
        return result

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    ss_tot = sum_yy - sum_y * sum_y / n
    ss_res = sum(
        (y - (intercept + slope * x)) ** 2
        for x, y in zip(xs, ys)
    )
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else math.nan
    discount_factor = -slope

    result.update({
        "intercept": intercept,
        "slope": slope,
        "discount_factor": discount_factor,
        "r_squared": r_squared,
    })
    return result


def write_svg_plot(group, estimates: dict, output: Path, quote_date: str, expire_date: str) -> None:
    """Write a dependency-free SVG diagnostic plot for one regression."""
    usable = [
        (strike, call - put)
        for strike, call, put in group["pairs"]
        if call > 0 and put > 0
    ]
    if not usable:
        raise ValueError("The requested plot group has no usable call-put pairs.")

    width, height = 960, 620
    left, right, top, bottom = 90, 35, 75, 85
    plot_width = width - left - right
    plot_height = height - top - bottom
    xs = [point[0] for point in usable]
    ys = [point[1] for point in usable]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_pad = max((x_max - x_min) * 0.05, 1.0)
    y_pad = max((y_max - y_min) * 0.08, 1.0)
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    def sx(value):
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def sy(value):
        return top + (y_max - value) / (y_max - y_min) * plot_height

    def fmt(value):
        return f"{value:.2f}"

    slope = estimates["slope"]
    intercept = estimates["intercept"]
    line_points = [
        (sx(x_min), sy(intercept + slope * x_min)),
        (sx(x_max), sy(intercept + slope * x_max)),
    ]
    points = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in usable)
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in line_points)
    title = html.escape(f"SPX put-call parity regression: {quote_date} to {expire_date}")
    rate = estimates["implied_rate_pct"]
    r_squared = estimates["r_squared"]
    annotation = html.escape(
        f"C - P = {intercept:.2f} {slope:+.6f}K | "
        f"implied rate = {rate:.2f}% | R² = {r_squared:.4f} | "
        f"matched pairs = {len(usable)}"
    )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{width / 2:.0f}" y="32" text-anchor="middle" font-family="Arial, sans-serif" font-size="20" font-weight="bold">{title}</text>
<text x="{width / 2:.0f}" y="57" text-anchor="middle" font-family="Arial, sans-serif" font-size="13">{annotation}</text>
<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#333"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#333"/>
<polyline points="{line}" fill="none" stroke="#d62728" stroke-width="2.5"/>
<polyline points="{points}" fill="none" stroke="none"/>
{''.join(f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="3" fill="#1f77b4" fill-opacity="0.65"/>' for x, y in usable)}
<text x="{left + plot_width / 2:.0f}" y="{height - 28}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14">Strike price (K)</text>
<text x="22" y="{top + plot_height / 2:.0f}" text-anchor="middle" transform="rotate(-90 22 {top + plot_height / 2:.0f})" font-family="Arial, sans-serif" font-size="14">Call midpoint - put midpoint</text>
<text x="{left}" y="{top + plot_height + 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11">{fmt(x_min + x_pad)}</text>
<text x="{left + plot_width}" y="{top + plot_height + 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11">{fmt(x_max - x_pad)}</text>
<text x="{left - 10}" y="{sy(y_max) + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="11">{fmt(y_max)}</text>
<text x="{left - 10}" y="{sy(y_min) + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="11">{fmt(y_min)}</text>
<circle cx="{width - 185}" cy="{height - 42}" r="4" fill="#1f77b4"/>
<text x="{width - 175}" y="{height - 38}" font-family="Arial, sans-serif" font-size="12">Observed pairs</text>
<line x1="{width - 185}" y1="{height - 20}" x2="{width - 177}" y2="{height - 20}" stroke="#d62728" stroke-width="2.5"/>
<text x="{width - 170}" y="{height - 16}" font-family="Arial, sans-serif" font-size="12">OLS fit</text>
</svg>
'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/cleaned/spx_options_2023_filtered.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/cleaned/spx_implied_rates_2023.csv"),
    )
    parser.add_argument(
        "--quote-date",
        help="Process one YYYY-MM-DD snapshot; omit to process all available dates.",
    )
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=20,
        help="Minimum matched call-put pairs per regression (default: 20).",
    )
    parser.add_argument(
        "--min-r2",
        type=float,
        default=0.95,
        help="R-squared threshold for accepted estimates (default: 0.95).",
    )
    parser.add_argument(
        "--plot-date",
        help="Quote date for the regression plot (default: 2023-08-15, or --quote-date).",
    )
    parser.add_argument(
        "--plot-expire-date",
        help="Expiration date for the regression plot (default: 2023-12-29).",
    )
    parser.add_argument(
        "--plot-output",
        type=Path,
        default=Path("data/cleaned/implied_rate_regression_q3.svg"),
        help="SVG path for the example regression plot.",
    )
    args = parser.parse_args()

    # A pair is keyed by quote timestamp, expiration, and strike.
    # Values are [call_mid, put_mid, underlying_last].
    pairs = {}
    required = {
        "quote_unixtime", "quote_readtime", "quote_date", "expire_date",
        "dte", "option_type", "strike", "mid", "underlying_last",
    }

    with args.input.open(newline="", encoding="utf-8-sig") as input_file:
        reader = csv.DictReader(input_file)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Input is missing required columns: {sorted(missing)}")

        for row in reader:
            if args.quote_date and row["quote_date"] != args.quote_date:
                continue
            option_type = row["option_type"]
            if option_type not in {"call", "put"}:
                continue
            mid = to_float(row["mid"])
            strike = to_float(row["strike"])
            dte = to_float(row["dte"])
            underlying = to_float(row["underlying_last"])
            if mid is None or strike is None or dte is None:
                continue

            key = (
                row["quote_unixtime"], row["quote_readtime"], row["quote_date"],
                row["expire_date"], row["dte"], row["strike"],
            )
            if key not in pairs:
                pairs[key] = [None, None, underlying]
            pairs[key][0 if option_type == "call" else 1] = mid

    groups = defaultdict(lambda: {"pairs": [], "underlyings": []})
    for key, values in pairs.items():
        call_mid, put_mid, underlying = values
        if call_mid is None or put_mid is None:
            continue
        quote_unixtime, quote_readtime, quote_date, expire_date, dte, strike = key
        group_key = (
            quote_unixtime, quote_readtime, quote_date, expire_date, dte
        )
        groups[group_key]["pairs"].append((float(strike), call_mid, put_mid))
        if underlying is not None:
            groups[group_key]["underlyings"].append(underlying)

    output_columns = [
        "quote_unixtime", "quote_readtime", "quote_date", "expire_date", "dte",
        "underlying_last", "n_pairs", "intercept", "slope", "discount_factor",
        "forward", "implied_rate", "implied_rate_pct", "r_squared", "accepted",
    ]
    results = []
    for group_key, group in groups.items():
        quote_unixtime, quote_readtime, quote_date, expire_date, dte_text = group_key
        estimates = estimate_group(group["pairs"], args.min_pairs, args.min_r2)
        dte = float(dte_text)
        years = dte / 365.0
        discount_factor = estimates["discount_factor"]
        if discount_factor > 0 and years > 0:
            rate = -math.log(discount_factor) / years
            estimates["implied_rate"] = rate
            estimates["implied_rate_pct"] = 100 * rate
            estimates["forward"] = estimates["intercept"] / discount_factor
            estimates["accepted"] = bool(
                math.isfinite(rate)
                and math.isfinite(estimates["r_squared"])
                and estimates["r_squared"] >= args.min_r2
            )

        underlyings = group["underlyings"]
        results.append({
            "quote_unixtime": quote_unixtime,
            "quote_readtime": quote_readtime,
            "quote_date": quote_date,
            "expire_date": expire_date,
            "dte": dte_text,
            "underlying_last": (
                sum(underlyings) / len(underlyings) if underlyings else ""
            ),
            **estimates,
        })

    results.sort(key=lambda row: (row["quote_date"], float(row["dte"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=output_columns)
        writer.writeheader()
        writer.writerows(results)

    plot_date = args.plot_date or args.quote_date or "2023-08-15"
    plot_expire_date = args.plot_expire_date
    if plot_expire_date is None:
        date_candidates = [
            (key, group)
            for key, group in groups.items()
            if key[2] == plot_date
        ]
        if not date_candidates:
            raise ValueError(f"No regression groups found for plot date {plot_date}")
        plot_expire_date = max(
            date_candidates,
            key=lambda item: len(item[1]["pairs"]),
        )[0][3]

    plot_candidates = [
        (key, group)
        for key, group in groups.items()
        if key[2] == plot_date and key[3] == plot_expire_date
    ]
    if not plot_candidates:
        raise ValueError(
            f"No regression group found for plot date {plot_date} "
            f"and expiration {plot_expire_date}"
        )
    plot_key, plot_group = max(
        plot_candidates,
        key=lambda item: len(item[1]["pairs"]),
    )
    plot_estimates = estimate_group(
        plot_group["pairs"], args.min_pairs, args.min_r2
    )
    plot_years = float(plot_key[4]) / 365.0
    plot_discount_factor = plot_estimates["discount_factor"]
    if plot_discount_factor > 0 and plot_years > 0:
        plot_rate = -math.log(plot_discount_factor) / plot_years
        plot_estimates["implied_rate"] = plot_rate
        plot_estimates["implied_rate_pct"] = 100 * plot_rate
    write_svg_plot(
        plot_group,
        plot_estimates,
        args.plot_output,
        plot_key[2],
        plot_key[3],
    )

    accepted = sum(bool(row["accepted"]) for row in results)
    print(
        f"Wrote {len(results):,} expiration estimates to {args.output} "
        f"({accepted:,} accepted at R² >= {args.min_r2:.2f})"
    )
    print(f"Wrote example regression plot to {args.plot_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
