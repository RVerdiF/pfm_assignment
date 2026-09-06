"""Behavioral validation for the BigQuery commission anomalies asset.

Validates that sql/bigquery/commission_anomalies.sql conforms to the production
contract specified in the assignment by executing a DuckDB-shimmed copy:
- References authoritative analytics_core.f_commission_daily (not local proxy)

The test does not claim to execute BigQuery. It uses only small syntax
substitutions and a SAFE_DIVIDE macro for the DuckDB fixture.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re

import duckdb


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "sql" / "bigquery" / "commission_anomalies.sql"


def _sql() -> str:
    return ASSET.read_text()


def test_query_targets_authoritative_production_source() -> None:
    sql = _sql()
    assert "analytics_core.f_commission_daily" in sql
    # The local DuckDB proxy must never be used in the BigQuery production query
    assert "fct_commission_daily_local" not in sql


def _duckdb_sql(anchor: date, *, inspect_classified: bool = False) -> str:
    """Apply only the small syntax shims needed to run the BigQuery asset in DuckDB."""
    anchor_literal = anchor.isoformat()
    sql = _sql()
    sql = sql.replace(
        "`project_id.analytics_core.f_commission_daily`", "commission_daily"
    )
    sql = sql.replace("CURRENT_DATE()", f"DATE '{anchor_literal}'")
    sql = re.sub(
        rf"DATE_SUB\(DATE '{re.escape(anchor_literal)}', INTERVAL (\d+) DAY\)",
        rf"(DATE '{anchor_literal}' - INTERVAL \1 DAY)",
        sql,
    )
    sql = re.sub(
        r"UNIX_DATE\(([^()]*)\)",
        r"date_diff('day', DATE '1970-01-01', \1)",
        sql,
    )
    if inspect_classified:
        # Keep the CTEs and replace only the final anomaly-only projection so
        # unavailable rows can be checked without reimplementing the query.
        sql = sql.rsplit("\nSELECT", 1)[0] + (
            "\nSELECT * FROM classified ORDER BY commission_date, firm_id;"
        )
    return sql


def test_query_handles_threshold_history_zero_and_future_cases() -> None:
    """Execute the asset against a compact DuckDB fixture using dialect shims."""
    anchor = date(2025, 1, 31)
    rows: list[tuple[date, str, float | None]] = []

    # Each firm has a complete seven-day history at 100. The exact +/-40% cases
    # must remain normal because the threshold is strict; +/-41% must be anomalies.
    current_values = {
        "stable": 100,
        "plus_exact": 140,
        "plus_anomaly": 141,
        "minus_exact": 60,
        "minus_anomaly": 59,
        "high_impact": 200,
    }
    for firm_id, current_value in current_values.items():
        for offset in range(36, -1, -1):
            commission_date = anchor - timedelta(days=offset)
            amount = current_value if commission_date == anchor else 100
            rows.append((commission_date, firm_id, amount))

    # The zero baseline is unavailable, rather than a normal comparison.
    for offset in range(36, -1, -1):
        commission_date = anchor - timedelta(days=offset)
        rows.append((commission_date, "zero", 100 if commission_date == anchor else 0))

    # One missing prior day makes the baseline incomplete. A large current value
    # would be a false anomaly if the six available days were averaged anyway.
    for offset in range(36, -1, -1):
        commission_date = anchor - timedelta(days=offset)
        if commission_date != date(2025, 1, 28):
            rows.append((commission_date, "missing", 1_000 if commission_date == anchor else 100))

    # A null amount is also unusable history, even though its date is present.
    for offset in range(36, -1, -1):
        commission_date = anchor - timedelta(days=offset)
        amount = 1_000 if commission_date == anchor else 100
        if commission_date == date(2025, 1, 28):
            amount = None
        rows.append((commission_date, "null_history", amount))

    # The first report date still has the seven-day warmup from the 37-day scan.
    first_report_date = anchor - timedelta(days=29)
    for offset in range(36, -1, -1):
        commission_date = anchor - timedelta(days=offset)
        amount = 150 if commission_date == first_report_date else 100
        rows.append((commission_date, "first_report_day", amount))

    # A future row is outside the capped source range and cannot become an anomaly.
    for offset in range(36, -1, -1):
        commission_date = anchor - timedelta(days=offset)
        rows.append((commission_date, "future", 100))
    rows.append((date(2025, 2, 1), "future", 1_000))

    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE MACRO safe_divide(numerator, denominator) AS
                CASE WHEN denominator = 0 THEN NULL ELSE numerator / denominator END
            """
        )
        connection.execute(
            """
            CREATE TABLE commission_daily (
                commission_date DATE,
                firm_id VARCHAR,
                commission_amount DOUBLE
            )
            """
        )
        connection.executemany("INSERT INTO commission_daily VALUES (?, ?, ?)", rows)
        result = connection.execute(_duckdb_sql(anchor)).fetchall()
        classified = connection.execute(
            _duckdb_sql(anchor, inspect_classified=True)
        ).fetchall()
    finally:
        connection.close()

    assert {(row[1], row[0]) for row in result} == {
        ("first_report_day", first_report_date),
        ("high_impact", anchor),
        ("plus_anomaly", anchor),
        ("minus_anomaly", anchor),
    }
    assert {row[1]: row[4] for row in result} == {
        "first_report_day": 0.5,
        "high_impact": 1.0,
        "plus_anomaly": 0.41,
        "minus_anomaly": -0.41,
    }
    assert [row[5] for row in result] == sorted(
        (row[5] for row in result), reverse=True
    )
    assert min(row[0] for row in result) == first_report_date
    assert max(row[0] for row in result) == anchor

    classified_by_key = {(row[1], row[0]): row for row in classified}
    for firm_id in ("missing", "null_history", "zero"):
        assert classified_by_key[(firm_id, anchor)][-1] == "unavailable"
    assert all(row[0] <= anchor for row in classified)
