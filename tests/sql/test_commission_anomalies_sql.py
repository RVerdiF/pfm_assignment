"""Static contract validation for the BigQuery commission anomalies asset.

Validates that sql/bigquery/commission_anomalies.sql conforms to the production
contract specified in the assignment without executing against BigQuery:
- References authoritative analytics_core.f_commission_daily (not local proxy)
- Employs a 7-day trailing calendar window excluding current day
- Uses SAFE_DIVIDE for zero-baseline safety
- Classifies rows with CASE as 'anomaly' vs 'normal' based on 40% threshold
- Evaluates strictly 30 days and scans at least 37 days from origin
- Filters to return anomalies only (WHERE anomaly = 'anomaly')
- Orders by absolute revenue impact descending
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "sql" / "bigquery" / "commission_anomalies.sql"


def _sql() -> str:
    return ASSET.read_text()


def test_asset_exists() -> None:
    assert ASSET.is_file(), f"Asset not found at {ASSET}"


def test_query_targets_authoritative_production_source() -> None:
    sql = _sql()
    assert "analytics_core.f_commission_daily" in sql
    # The local DuckDB proxy must never be used in the BigQuery production query
    assert "fct_commission_daily_local" not in sql


def test_trailing_calendar_window_excludes_current_day() -> None:
    sql = _sql().lower()
    # 7-day calendar window with current day excluded
    assert "range between 7 preceding and 1 preceding" in sql
    assert "unix_date" in sql


def test_source_scans_at_least_37_days_and_scores_30_days() -> None:
    sql = _sql().lower()
    # 36 day lookback = 37 discrete calendar dates; 29 day lookback = 30 discrete dates
    assert "36 day" in sql or "37 day" in sql
    assert "29 day" in sql or "30 day" in sql


def test_safe_divide_protects_zero_baseline() -> None:
    sql = _sql().lower()
    assert "safe_divide" in sql


def test_forty_percent_threshold_applied() -> None:
    sql = _sql()
    assert "0.40" in sql


def test_classifies_anomaly_and_normal() -> None:
    sql = _sql().lower()
    assert "'anomaly'" in sql
    assert "'normal'" in sql


def test_filters_anomalies_only() -> None:
    sql = _sql().lower()
    assert "where anomaly = 'anomaly'" in sql


def test_orders_by_absolute_revenue_impact() -> None:
    sql = _sql().lower()
    assert "absolute_revenue_impact" in sql
    assert "order by absolute_revenue_impact desc" in sql
