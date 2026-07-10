"""Parser for FedWatch-style rate-probability tables.

Accepts the markdown table the user pastes into the Record → FOMC tab:

    | Meeting Date | 225-250 | 250-275 | ... | 425-450 |
    | ------------ | ------- | ------- | ... | ------- |
    | 29/04/2026   | 0.0%    | 0.0%    | ... | 0.0%    |

Dates are DD/MM/YYYY; bucket headers are basis-point ranges; cells are
percentages (the trailing % is optional). Returns a list of
(meeting_date, bucket_low, bucket_high, probability) rows.
"""
from __future__ import annotations

import re
from datetime import date, datetime

_BUCKET_RE = re.compile(r"^(\d{2,3})\s*-\s*(\d{2,3})$")
_SEPARATOR_RE = re.compile(r"^[\s|:\-]+$")


class RateTableError(ValueError):
    pass


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _parse_date(text: str) -> date:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RateTableError(f"Unrecognised meeting date: {text!r}")


def parse_rate_table(text: str) -> list[tuple[date, int, int, float]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise RateTableError("Empty table")

    header = _split_row(lines[0])
    if not header or "meeting" not in header[0].lower():
        raise RateTableError("First column of the header must be 'Meeting Date'")

    buckets: list[tuple[int, int]] = []
    for cell in header[1:]:
        m = _BUCKET_RE.match(cell)
        if not m:
            raise RateTableError(f"Bad bucket header: {cell!r} (expected e.g. 350-375)")
        buckets.append((int(m.group(1)), int(m.group(2))))
    if not buckets:
        raise RateTableError("No probability buckets found in the header")

    rows: list[tuple[date, int, int, float]] = []
    for line in lines[1:]:
        if _SEPARATOR_RE.match(line):
            continue
        cells = _split_row(line)
        if len(cells) != len(buckets) + 1:
            raise RateTableError(
                f"Row has {len(cells)} cells, expected {len(buckets) + 1}: {line!r}"
            )
        meeting = _parse_date(cells[0])
        for (low, high), cell in zip(buckets, cells[1:]):
            try:
                prob = float(cell.rstrip("%").strip())
            except ValueError:
                raise RateTableError(f"Bad probability {cell!r} for {meeting}")
            rows.append((meeting, low, high, prob))

    if not rows:
        raise RateTableError("Table has a header but no data rows")
    return rows
