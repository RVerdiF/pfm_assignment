from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dbt_adapter_is_declared_in_the_project_manifest() -> None:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = manifest["project"]["dependencies"]

    assert any(dependency.startswith("dbt-core") for dependency in dependencies)
    assert any(dependency.startswith("dbt-duckdb") for dependency in dependencies)


def test_bigquery_consumption_asset_is_checked_in() -> None:
    asset = ROOT / "sql" / "bigquery" / "attribution_health.sql"

    assert asset.is_file()
    sql = asset.read_text()
    assert "marts.mart_attribution_health" in sql
