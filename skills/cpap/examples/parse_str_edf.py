"""Parse a ResMed STR.EDF daily summary file.

Stdlib-only — no external dependencies. Reads the EDF binary format directly.

Usage:
    python3 parse_str_edf.py /path/to/STR.EDF [--days N]
"""

import argparse
import json
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
    """Print a JSON summary for the last N days with usage."""
    used = [(EPOCH + timedelta(days=int(r["Date"])), r) for r in records if r.get("Duration", 0) > 0]
    used.sort(key=lambda x: x[0])
    last_n = used[-days:]

    if not last_n:
        print("No usage data found.")
        return

    nights = []
    for date, rec in last_n:
        nights.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "hours": round(rec["Duration"] / 60, 1),
                "ahi": round(rec["AHI"], 1),
                "hi": round(rec.get("HI", 0), 1),
                "oai": round(rec.get("OAI", 0), 1),
                "cai": round(rec.get("CAI", 0), 1),
                "pressure_50": round(rec.get("MaskPress.50", 0), 1),
                "pressure_95": round(rec.get("MaskPress.95", 0), 1),
                "leak_50_lpm": round(rec.get("Leak.50", 0) * 60, 1),
                "leak_95_lpm": round(rec.get("Leak.95", 0) * 60, 1),
                "resp_rate": round(rec.get("RespRate.50", 0), 1),
                "tidal_volume": round(rec.get("TidVol.50", 0), 2),
            }
        )

    ahis = [n["ahi"] for n in nights]
    compliant = sum(1 for n in nights if n["hours"] >= 4)

    # Missing nights in the date range
    first = datetime.strptime(nights[0]["date"], "%Y-%m-%d")
    last = datetime.strptime(nights[-1]["date"], "%Y-%m-%d")
    actual = {n["date"] for n in nights}
    missing = []
    d = first
    while d <= last:
        ds = d.strftime("%Y-%m-%d")
        if ds not in actual:
            missing.append(ds)
        d += timedelta(days=1)

    summary = {
        "nights": nights,
        "summary": {
            "count": len(nights),
            "range": f"{nights[0]['date']} to {nights[-1]['date']}",
            "ahi_mean": round(sum(ahis) / len(ahis), 1),
            "ahi_min": min(ahis),
            "ahi_max": max(ahis),
            "avg_hours": round(sum(n["hours"] for n in nights) / len(nights), 1),
            "compliance": f"{compliant}/{len(nights)} nights >= 4h ({round(compliant / len(nights) * 100)}%)",
            "missing_nights": missing,
        },
    }
    print(json.dumps(summary, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    _, records = read_str_edf(args.file)
    report(records, args.days)


if __name__ == "__main__":
    sys.exit(main())
