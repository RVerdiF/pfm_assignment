from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "sql" / "bigquery" / "commission_anomalies.sql"


def _sql() -> str:
    return ASSET.read_text()


def test_asset_exists() -> None:
    assert ASSET.is_file()


def test_query_targets_authoritative_source() -> None:
    sql = _sql()
    assert "analytics_core.f_commission_daily" in sql
    # The local proxy must not appear in the anomaly query.
    assert "fct_commission_daily_local" not in sql


def test_rolling_average_excludes_current_row() -> None:
    sql = _sql()
    # The required frame: 7 rows preceding, current row excluded (1 preceding).
    assert "rows between 7 preceding and 1 preceding" in sql.lower()


def test_forty_percent_threshold_is_applied() -> None:
    sql = _sql()
    # The threshold constant must appear literally in the query.
    assert "0.40" in sql


def test_only_anomalies_are_returned() -> None:
    sql = _sql().lower()
    # The WHERE clause filters on the threshold; rows below it are dropped.
    assert "> 0.40" in sql
    # A sane query labels anomalies explicitly.
    assert "'anomaly'" in sql


def test_ordering_is_by_absolute_revenue_impact() -> None:
    sql = _sql().lower()
    assert "absolute_revenue_impact" in sql
    assert "order by absolute_revenue_impact" in sql


def test_baseline_zero_behavior_is_documented() -> None:
    sql = _sql().lower()
    # SAFE_DIVIDE must be used (or equivalent) to handle a zero baseline
    # without a runtime error.
    assert "safe_divide" in sql
