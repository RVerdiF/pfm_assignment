"""Unit tests for the Streamlit warehouse bootstrap module.

Scope: verify the *decision logic* that drives when the app rebuilds the
warehouse and how it opens it read-only. Subprocess execution (real ingestion
and dbt) is exercised separately by the project's functional/AppTest checks,
not mocked here, so the test stays meaningful against the real pipeline.

The module is importable because it only imports ``streamlit`` lazily-safe
packages at module scope; tests do not need a running Streamlit server.
"""
from __future__ import annotations

import duckdb
import pytest

import sys
from pathlib import Path

_STREAMLIT_DIR = Path(__file__).resolve().parents[1] / "streamlit"
sys.path.insert(0, str(_STREAMLIT_DIR))

import warehouse_bootstrap as wb  # noqa: E402


@pytest.fixture()
def temp_database(tmp_path: Path) -> Path:
    """A database path that is NOT the project default."""
    return tmp_path / "custom" / "pfm.duckdb"


def test_default_database_points_into_project_warehouse() -> None:
    assert wb.DEFAULT_DATABASE_PATH.name == "pfm.duckdb"
    assert wb.DEFAULT_DATABASE_PATH.parent.name == "warehouse"
    assert wb.DEFAULT_DATABASE_PATH.parents[1] == wb.PROJECT_ROOT


def test_expected_marts_are_the_consumer_contract() -> None:
    assert "fct_revenue_attribution" in wb.EXPECTED_MARTS
    assert "mart_attribution_health" in wb.EXPECTED_MARTS
    assert "fct_commission_daily_local" in wb.EXPECTED_MARTS


def test_warehouse_needs_build_when_file_missing(tmp_path: Path) -> None:
    # A path that does not exist must always require a build, regardless of
    # whether the project's own generated warehouse is currently present.
    missing = tmp_path / "warehouse" / "pfm.duckdb"
    assert wb.warehouse_needs_build(missing) is True


def test_database_path_override_honors_env_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "elsewhere" / "pfm.duckdb"
    monkeypatch.setenv("PFM_DUCKDB_PATH", str(custom))
    resolved = wb._database_path_or_default(None)
    assert resolved == custom


def test_database_path_override_argument_wins_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_db = tmp_path / "from_env.duckdb"
    arg_db = tmp_path / "from_arg.duckdb"
    monkeypatch.setenv("PFM_DUCKDB_PATH", str(env_db))
    resolved = wb._database_path_or_default(str(arg_db))
    assert resolved == arg_db


def test_warehouse_needs_build_when_marts_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "pfm.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create schema raw")
    con.execute("create table raw.tracknow_checkouts (x int)")
    con.close()

    assert db_path.is_file()
    assert wb.warehouse_needs_build(db_path) is True


def test_required_relations_present_after_full_population(tmp_path: Path) -> None:
    db_path = tmp_path / "pfm.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create schema marts")
    con.execute("create schema intermediate")
    for schema, table in wb.REQUIRED_RELATIONS:
        columns = ", ".join(f'"{name}" int' for name in wb.REQUIRED_COLUMNS[(schema, table)])
        con.execute(f'create table "{schema}"."{table}" ({columns})')
    con.close()

    assert wb.required_relations_present(db_path) is True
    assert wb.warehouse_needs_build(db_path) is False


def test_required_relations_present_false_when_one_mart_missing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pfm.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create schema marts")
    con.execute("create schema intermediate")
    # Create every required relation except mart_attribution_health.
    for mart in wb.EXPECTED_MARTS:
        if mart == "mart_attribution_health":
            continue
        columns = ", ".join(f'"{name}" int' for name in wb.REQUIRED_COLUMNS[("marts", mart)])
        con.execute(f'create table marts."{mart}" ({columns})')
    con.execute(
        "create table intermediate.int_unmatched_conversions (unmatched_reason varchar)"
    )
    con.close()

    assert wb.required_relations_present(db_path) is False
    assert wb.warehouse_needs_build(db_path) is True


def test_required_relations_present_false_when_diagnostic_view_missing(
    tmp_path: Path,
) -> None:
    """Regression: marts alone must not satisfy the required-relation contract.

    A custom PFM_DUCKDB_PATH warehouse that provides only the three marts
    (which the old readiness check validated) would still crash at render time
    because the analysis and methodology pages read the ADR-8 diagnostic
    view. The readiness check must treat that warehouse as not ready so the
    bootstrap layer surfaces the readable PipelineError before any page
    renders.
    """
    db_path = tmp_path / "pfm.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create schema marts")
    con.execute("create schema intermediate")
    for mart in wb.EXPECTED_MARTS:
        columns = ", ".join(f'"{name}" int' for name in wb.REQUIRED_COLUMNS[("marts", mart)])
        con.execute(f'create table marts."{mart}" ({columns})')
    con.close()

    assert (db_path).is_file()
    assert wb.required_relations_present(db_path) is False
    assert wb.warehouse_needs_build(db_path) is True
    assert wb._missing_relations(db_path) == [
        "intermediate.int_unmatched_conversions"
    ]


def test_get_warehouse_connection_raises_readable_error_when_diagnostic_view_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A custom override missing only the diagnostic view fails at bootstrap.

    The warehouse file exists and has all three declared marts (the old
    contract), but lacks intermediate.int_unmatched_conversions. get_warehouse_connection
    must raise the readable PipelineError naming the missing relation, never
    return a connection that crashes at render time.
    """
    custom = tmp_path / "pfm.duckdb"
    con = duckdb.connect(str(custom))
    con.execute("create schema marts")
    con.execute("create schema intermediate")
    for mart in wb.EXPECTED_MARTS:
        columns = ", ".join(f'"{name}" int' for name in wb.REQUIRED_COLUMNS[("marts", mart)])
        con.execute(f'create table marts."{mart}" ({columns})')
    con.close()

    monkeypatch.setenv("PFM_DUCKDB_PATH", str(custom))
    wb.get_warehouse_connection.clear()
    try:
        with pytest.raises(
            wb.PipelineError,
            match="intermediate.int_unmatched_conversions",
        ):
            wb.get_warehouse_connection()
    finally:
        wb.get_warehouse_connection.clear()


def test_check_target_rejects_custom_missing_diagnostic_view(
    temp_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A marts-only custom override is rejected with the missing view named."""
    temp_database.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(temp_database))
    con.execute("create schema marts")
    con.execute("create schema intermediate")
    for mart in wb.EXPECTED_MARTS:
        columns = ", ".join(f'"{name}" int' for name in wb.REQUIRED_COLUMNS[("marts", mart)])
        con.execute(f'create table marts."{mart}" ({columns})')
    con.close()

    monkeypatch.setenv("PFM_DUCKDB_PATH", str(temp_database))
    with pytest.raises(wb.PipelineError, match="intermediate.int_unmatched_conversions"):
        wb._check_target_within_project(temp_database)


def test_relation_is_compatible_false_on_broken_file(tmp_path: Path) -> None:
    db_path = tmp_path / "broken.duckdb"
    db_path.write_bytes(b"this is not a duckdb database file")
    assert wb._relation_is_compatible(db_path, "marts", "fct_revenue_attribution") is False


def test_check_target_rejects_custom_missing_path(
    temp_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A custom PFM_DUCKDB_PATH that does not exist cannot be auto-rebuilt,
    # because the pipeline writes the default project warehouse.
    monkeypatch.setenv("PFM_DUCKDB_PATH", str(temp_database))
    with pytest.raises(wb.PipelineError, match="not the default"):
        wb._check_target_within_project(temp_database)


def test_check_target_accepts_default_path() -> None:
    # No exception means the default warehouse is the managed target.
    wb._check_target_within_project(wb.DEFAULT_DATABASE_PATH)


def test_check_target_accepts_default_when_env_set_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When PFM_DUCKDB_PATH points exactly at the project default, the path is
    # still the managed target and must not be rejected.
    monkeypatch.setenv("PFM_DUCKDB_PATH", str(wb.DEFAULT_DATABASE_PATH))
    wb._check_target_within_project(wb.DEFAULT_DATABASE_PATH)


def test_existing_mart_without_channel_is_rejected_before_render(tmp_path: Path) -> None:
    db_path = tmp_path / "old.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema marts")
        con.execute("create schema intermediate")
        for (schema, table), required in wb.REQUIRED_COLUMNS.items():
            columns = ", ".join(f'"{name}" int' for name in required)
            con.execute(f'create table "{schema}"."{table}" ({columns})')
        con.execute("alter table marts.fct_revenue_attribution drop column channel")

    assert wb.warehouse_needs_build(db_path)
    assert wb._missing_relations(db_path) == ["marts.fct_revenue_attribution"]
    wb.get_warehouse_connection.clear()
    try:
        with pytest.raises(wb.PipelineError, match="required columns.*fct_revenue_attribution"):
            wb.get_warehouse_connection(database_path=db_path)
    finally:
        wb.get_warehouse_connection.clear()
