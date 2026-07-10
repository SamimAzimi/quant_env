from datetime import date

import pytest

from server.rate_table import RateTableError, parse_rate_table

TABLE = """
| Meeting Date | 325-350 | 350-375 | 375-400 |
| ------------ | ------- | ------- | ------- |
| 29/04/2026   | 0.0%    | 93.8%   | 6.2%    |
| 17/06/2026   | 0.0%    | 82.8%   | 17.2%   |
"""


def test_parses_meetings_buckets_and_probs():
    rows = parse_rate_table(TABLE)
    assert len(rows) == 6
    assert rows[0] == (date(2026, 4, 29), 325, 350, 0.0)
    assert rows[1] == (date(2026, 4, 29), 350, 375, 93.8)
    assert rows[5] == (date(2026, 6, 17), 375, 400, 17.2)


def test_percent_sign_is_optional():
    rows = parse_rate_table(
        "| Meeting Date | 350-375 |\n|---|---|\n| 29/04/2026 | 93.8 |")
    assert rows == [(date(2026, 4, 29), 350, 375, 93.8)]


def test_rejects_bad_header():
    with pytest.raises(RateTableError):
        parse_rate_table("| Date | banana |\n| 29/04/2026 | 1% |")


def test_rejects_ragged_row():
    with pytest.raises(RateTableError):
        parse_rate_table(
            "| Meeting Date | 350-375 | 375-400 |\n| 29/04/2026 | 93.8% |")


def test_rejects_empty():
    with pytest.raises(RateTableError):
        parse_rate_table("   \n  ")
