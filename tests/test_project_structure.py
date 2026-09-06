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


def test_bigquery_commission_anomalies_asset_is_checked_in() -> None:
    asset = ROOT / "sql" / "bigquery" / "commission_anomalies.sql"

    assert asset.is_file()
    sql = asset.read_text()
    assert "analytics_core.f_commission_daily" in sql


def test_no_em_dashes_in_source_or_docs() -> None:
    """Ensure no Unicode em-dashes exist in tracked source, docs, or SQL files."""
    for ext in ("*.py", "*.sql", "*.md", "*.yml", "*.yaml", "*.toml"):
        for path in ROOT.rglob(ext):
            if any(part.startswith(".") or part in ("target", "venv", ".venv") for part in path.relative_to(ROOT).parts):
                continue
            content = path.read_text(encoding="utf-8")
            assert "\u2014" not in content, f"Found forbidden em-dash in {path}"
