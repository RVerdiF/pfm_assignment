from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dbt_adapter_is_declared_in_the_project_manifest() -> None:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = manifest["project"]["dependencies"]

    assert any(dependency.startswith("dbt-core") for dependency in dependencies)
    assert any(dependency.startswith("dbt-duckdb") for dependency in dependencies)


def test_bigquery_anomaly_asset_is_checked_in() -> None:
    asset = ROOT / "sql" / "bigquery" / "commission_anomalies.sql"

    assert asset.is_file()
    sql = asset.read_text()
    assert "analytics_core.f_commission_daily" in sql
    assert "rows between 7 preceding and 1 preceding" in sql
    assert "0.40" in sql
    assert "absolute_revenue_impact" in sql
    assert "anomaly" in sql


def test_bigquery_optional_attribution_health_asset_is_checked_in() -> None:
    asset = ROOT / "sql" / "bigquery" / "optional_attribution_health.sql"

    assert asset.is_file()
    sql = asset.read_text()
    assert "marts.mart_attribution_health" in sql


def test_readme_points_to_anomaly_query_not_local_proxy() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "commission_anomalies.sql" in readme
    assert "analytics_core.f_commission_daily" in readme
    # The local proxy must never be called the authoritative source.
    assert "fct_commission_daily_local" in readme
    assert "Not the authoritative production commission source" in readme or "Not the authoritative production commission" in readme
