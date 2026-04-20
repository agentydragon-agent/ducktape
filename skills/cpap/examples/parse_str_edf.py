"""Parse a ResMed STR.EDF daily summary file and print a nightly report.

Stdlib-only — no external dependencies. Reads the EDF binary format directly.

Usage:
    python3 parse_str_edf.py /path/to/STR.EDF [--days N]
"""

import argparse
import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path

EPOCH = datetime(1970, 1, 1)


def read_str_edf(path: Path) -> tuple[list[str], list[dict[str, float]]]:
    """Parse STR.EDF and return (signal_labels, list_of_daily_records).

    Each record is a dict mapping signal label to its physical value.
    Multi-sample signals (like MaskOn/MaskOff with 20 samples) are stored
    as lists; single-sample signals as floats.
    """
    with path.open("rb") as f:
        hdr = f.read(256)
        num_records = int(hdr[236:244].decode().strip())
        num_signals = int(hdr[252:256].decode().strip())
        header_bytes = int(hdr[184:192].decode().strip())

        f.seek(256)
        labels = [f.read(16).decode().strip() for _ in range(num_signals)]
        for _ in range(num_signals):
            f.read(80)  # transducer
        for _ in range(num_signals):
            f.read(8)  # phys_dim
        phys_min = [float(f.read(8).decode().strip()) for _ in range(num_signals)]
        phys_max = [float(f.read(8).decode().strip()) for _ in range(num_signals)]
        dig_min = [int(f.read(8).decode().strip()) for _ in range(num_signals)]
        dig_max = [int(f.read(8).decode().strip()) for _ in range(num_signals)]
        for _ in range(num_signals):
            f.read(80)  # prefiltering
        samples_per_record = [int(f.read(8).decode().strip()) for _ in range(num_signals)]
        for _ in range(num_signals):
            f.read(32)  # reserved

        def scale(sig: int, digital: int) -> float:
            d_lo, d_hi = dig_min[sig], dig_max[sig]
            p_lo, p_hi = phys_min[sig], phys_max[sig]
            return p_lo + (digital - d_lo) * (p_hi - p_lo) / (d_hi - d_lo) if d_hi != d_lo else p_lo

        f.seek(header_bytes)
        records = []
        for _ in range(num_records):
            rec: dict = {}
            for sig in range(num_signals):
                n = samples_per_record[sig]
                data = struct.unpack(f"<{n}h", f.read(n * 2))
                if n == 1:
                    rec[labels[sig]] = scale(sig, data[0])
                else:
                    rec[labels[sig]] = [scale(sig, d) for d in data]
            records.append(rec)

    return labels, records


def report(records: list[dict], days: int) -> None:
    """Print a summary table for the last N days with usage."""
    used = [(EPOCH + timedelta(days=int(r["Date"])), r) for r in records if r.get("Duration", 0) > 0]
    used.sort(key=lambda x: x[0])
    last_n = used[-days:]

    if not last_n:
        print("No usage data found.")
        return

    print(
        f"{'Date':12s} {'Hours':>6s} {'AHI':>6s}  {'HI':>4s} {'OAI':>4s} {'CAI':>4s}"
        f"  {'P50':>5s} {'P95':>5s}  {'Lk50':>5s} {'Lk95':>5s}  {'RR':>5s}  {'TV':>5s}"
    )
    print("-" * 90)

    total_hours = 0.0
    ahis = []
    for date, rec in last_n:
        hours = rec["Duration"] / 60
        total_hours += hours
        ahi = rec["AHI"]
        ahis.append(ahi)
        lk50 = rec.get("Leak.50", 0) * 60
        lk95 = rec.get("Leak.95", 0) * 60

        dur_flag = " " if hours >= 4 else "!"
        print(
            f"{dur_flag}{date.strftime('%Y-%m-%d'):11s} {hours:5.1f}h {ahi:5.1f}"
            f"  {rec.get('HI', 0):4.1f} {rec.get('OAI', 0):4.1f} {rec.get('CAI', 0):4.1f}"
            f"  {rec.get('MaskPress.50', 0):5.1f} {rec.get('MaskPress.95', 0):5.1f}"
            f"  {lk50:5.1f} {lk95:5.1f}"
            f"  {rec.get('RespRate.50', 0):5.1f}  {rec.get('TidVol.50', 0):4.2f}L"
        )

    print("-" * 90)
    avg_ahi = sum(ahis) / len(ahis)
    avg_hours = total_hours / len(last_n)
    compliant = sum(1 for _, r in last_n if r["Duration"] >= 240)
    pct = compliant / len(last_n) * 100

    print(f"\nSummary ({len(last_n)} nights, {last_n[0][0]:%Y-%m-%d} to {last_n[-1][0]:%Y-%m-%d}):")
    print(f"  AHI:        {avg_ahi:.1f} avg  ({min(ahis):.1f}-{max(ahis):.1f})  {'OK' if avg_ahi < 5 else 'ELEVATED'}")
    print(f"  Usage:      {avg_hours:.1f} h/night avg  ({total_hours:.0f}h total)")
    print(f"  Compliance: {compliant}/{len(last_n)} nights >= 4h ({pct:.0f}%)  {'OK' if pct >= 70 else 'BELOW 70%'}")

    # Missing nights
    d = last_n[0][0]
    actual = {dt.strftime("%Y-%m-%d") for dt, _ in last_n}
    missing = []
    while d <= last_n[-1][0]:
        if d.strftime("%Y-%m-%d") not in actual:
            missing.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    if missing:
        print(f"  Missing:    {len(missing)} nights ({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    _, records = read_str_edf(args.file)
    report(records, args.days)


if __name__ == "__main__":
    sys.exit(main())
