"""Reproducible warehouse bootstrap for the Streamlit app.

The app must start even when ``warehouse/pfm.duckdb`` does not exist yet (for
example on a fresh hosting environment). This module centralizes that
decision: when the warehouse file is missing or the required dbt relations are
absent, it runs the canonical pipeline first —

    python ingestion/load_excel.py
    dbt build

— and only then opens the warehouse read-only. Once the pipeline has run, the
connection is cached for the rest of the Streamlit session, so the same
execution never rebuilds the warehouse twice.

This module also owns the *required-relation contract*: the relations the
walkthrough pages read (the consumer marts plus the one narrow
``intermediate.int_unmatched_conversions`` diagnostic view documented in ADR
8). Startup fails with a readable ``PipelineError`` before any page renders
when the warehouse cannot satisfy that contract, so a custom
``PFM_DUCKDB_PATH`` warehouse that passes every check can never crash later at
render time with a missing-relation error.

This module is intentionally thin on analysis: it owns *starting* the
pipeline, never *re-implementing* attribution or business joins. All
attribution decisions stay in the dbt models; the app reads only the published
consumer relations.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import streamlit as st

# Project root as seen from this module (streamlit/warehouse_bootstrap.py).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "warehouse" / "pfm.duckdb"

MART_SCHEMA = "marts"
INTERMEDIATE_SCHEMA = "intermediate"
# Consumer-facing relations the app needs before it can render analytics.
EXPECTED_MARTS = (
    "fct_revenue_attribution",
    "fct_commission_daily_local",
    "mart_attribution_health",
)
# The narrow diagnostic view the analysis and methodology pages read for the
# unmatched-reason taxonomy (ADR 8: the only intermediate-layer read, an
# aggregate over its pre-computed unmatched_reason column — never a join).
# It is part of the same required-relation contract as the marts so a custom
# PFM_DUCKDB_PATH warehouse cannot pass bootstrap and then crash at render.
EXPECTED_INTERMEDIATE_VIEWS = (
    "int_unmatched_conversions",
)

# Every relation the walkthrough pages read, as (schema, table) pairs. Startup
# verifies this full contract before any page renders.
REQUIRED_RELATIONS: tuple[tuple[str, str], ...] = tuple(
    (MART_SCHEMA, mart) for mart in EXPECTED_MARTS
) + tuple(
    (INTERMEDIATE_SCHEMA, view) for view in EXPECTED_INTERMEDIATE_VIEWS
)


class PipelineError(RuntimeError):
    """Raised when the ingestion/dbt bootstrap fails with a readable cause."""


def _database_path_or_default(database_path: str | Path | None) -> Path:
    """Resolve the target warehouse path.

    An explicit ``database_path`` argument wins. Otherwise the
    ``PFM_DUCKDB_PATH`` environment variable is honored (documented override
    for reading an already-provisioned warehouse), falling back to the default
    project warehouse.
    """
    if database_path is not None:
        return Path(database_path).expanduser()
    configured = os.environ.get("PFM_DUCKDB_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATABASE_PATH


def _project_root_or_default(project_root: str | Path | None) -> Path:
    if project_root is None:
        return PROJECT_ROOT
    return Path(project_root).expanduser()


def _resolve_dbt_executable() -> str:
    """Return a dbt executable usable from the Python interpreter's venv.

    Prefers ``dbt`` on ``PATH``; falls back to the sibling ``dbt`` console
    script next to the running interpreter (the common layout when the app is
    launched from a virtualenv that installed dbt-core).
    """
    found = shutil.which("dbt")
    if found:
        return found
    sibling = Path(sys.executable).with_name("dbt")
    if sibling.is_file():
        return str(sibling)
    raise PipelineError(
        "dbt executable not found. Install the project with the pipeline "
        "dependencies (dbt-core and dbt-duckdb) and retry."
    )


def ensure_dbt_profile(project_root: str | Path | None = None) -> Path:
    """Create the project-local dbt profile from the checked-in example.

    ``dbt/profiles.yml`` is gitignored (it is a generated, machine-local file).
    A fresh checkout/hosting environment therefore needs it created before the
    first ``dbt build``. The app does that here so bootstrap stays
    reproducible. No credentials or absolute paths are required by the
    example, which targets ``../warehouse/pfm.duckdb`` relative to ``dbt/``.
    """
    root = _project_root_or_default(project_root)
    dbt_dir = root / "dbt"
    profile = dbt_dir / "profiles.yml"
    if profile.exists():
        return profile
    example = dbt_dir / "profiles.yml.example"
    if not example.is_file():
        raise PipelineError(
            f"dbt profile template not found: {example}. Refusing to guess a "
            "profile; create one from the repository example and retry."
        )
    shutil.copyfile(example, profile)
    return profile


def _run_command(cmd: list[str], cwd: Path, env: dict[str, str], label: str) -> None:
    """Run one pipeline command and surface a readable error on failure."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - interpreter launch failure
        raise PipelineError(f"Could not start {label}: {exc}") from exc

    if proc.returncode != 0:
        details = (proc.stdout or "")[-4000:]
        details += "\n" + (proc.stderr or "")[-2000:]
        raise PipelineError(
            f"{label} failed (exit code {proc.returncode}).\n\n"
            f"{details.strip()}"
        )


def run_ingestion(project_root: str | Path | None = None) -> None:
    """Run the Excel -> DuckDB raw loader as a subprocess."""
    root = _project_root_or_default(project_root)
    excel_loader = root / "ingestion" / "load_excel.py"
    if not excel_loader.is_file():
        raise PipelineError(f"Ingestion script not found: {excel_loader}")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    _run_command(
        [sys.executable, str(excel_loader)],
        cwd=root,
        env=env,
        label="Ingestion (load_excel.py)",
    )


def run_dbt_build(project_root: str | Path | None = None) -> None:
    """Run ``dbt build`` with the project-local profile.

    dbt is executed from ``dbt/`` (the documented working directory) with
    ``DBT_PROFILES_DIR`` pointing at the project's own profile directory, so a
    machine-global ``~/.dbt`` configuration is never touched.
    """
    root = _project_root_or_default(project_root)
    dbt_dir = root / "dbt"
    ensure_dbt_profile(root)
    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(dbt_dir)
    _run_command(
        [_resolve_dbt_executable(), "build"],
        cwd=dbt_dir,
        env=env,
        label="dbt build",
    )


def _relation_exists(
    database_path: str | Path, schema: str, table: str
) -> bool:
    """Return whether a relation exists in the local DuckDB warehouse."""
    db_path = Path(database_path)
    if not db_path.is_file():
        return False
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error:
        return False
    try:
        row = con.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = ? and table_name = ?",
            [schema, table],
        ).fetchone()
        return bool(row and row[0] > 0)
    except duckdb.Error:
        return False
    finally:
        con.close()


def required_relations_present(database_path: str | Path | None = None) -> bool:
    """Check that every relation the analytics UI reads is materialized.

    The contract is the consumer marts plus the narrow
    ``intermediate.int_unmatched_conversions`` diagnostic view (ADR 8): both
    the analysis page and the methodology page query that view, so a warehouse
    that satisfies only the marts would crash at render time.
    """
    db_path = _database_path_or_default(database_path)
    return all(
        _relation_exists(db_path, schema, table)
        for schema, table in REQUIRED_RELATIONS
    )


def warehouse_needs_build(database_path: str | Path | None = None) -> bool:
    """Return True when the pipeline must run before the app can read marts.

    Two situations require a rebuild:
    - the warehouse file does not exist at all, or
    - the file exists but the required relations are missing/stale (e.g. only
      raw tables were loaded, or a previous dbt run did not finish).
    """
    db_path = _database_path_or_default(database_path)
    if not db_path.is_file():
        return True
    return not required_relations_present(db_path)


def _missing_relations(database_path: str | Path | None = None) -> list[str]:
    db_path = _database_path_or_default(database_path)
    return [
        f"{schema}.{table}"
        for schema, table in REQUIRED_RELATIONS
        if not _relation_exists(db_path, schema, table)
    ]


def _check_target_within_project(db_path: Path) -> None:
    """Raise when the configured database path is not the default project one.

    The bootstrap pipeline (``load_excel.py`` main and the checked-in dbt
    profile) is hard-wired to ``<project>/warehouse/pfm.duckdb``. A custom
    ``PFM_DUCKDB_PATH`` may point at an *already provisioned* warehouse to
    read, but the app cannot auto-rebuild an arbitrary path without changing
    the pipeline configuration. Failing loudly beats silently rebuilding the
    wrong file — and when the custom warehouse is missing required relations
    the readable error names them, so a marts-only override cannot pass
    bootstrap and then crash at render time.
    """
    if db_path.resolve() != DEFAULT_DATABASE_PATH.resolve():
        missing = _missing_relations(db_path) if db_path.is_file() else []
        detail = ""
        if missing:
            detail = (
                " The warehouse is missing required relation(s): "
                + ", ".join(missing)
                + "."
            )
        raise PipelineError(
            f"The configured database path {db_path} is not the default "
            f"project warehouse {DEFAULT_DATABASE_PATH}. Automatic bootstrap "
            "only manages the default warehouse. Either unset PFM_DUCKDB_PATH "
            "or point it at an existing warehouse with the required "
            f"relations.{detail}"
        )


@st.cache_resource(show_spinner=False)
def get_warehouse_connection(
    database_path: str | Path | None = None,
    project_root: str | Path | None = None,
) -> duckdb.DuckDBPyConnection:
    """Return a read-only DuckDB connection, bootstrapping when needed.

    Because this function is decorated with ``st.cache_resource``, the whole
    ingestion + dbt build (when required) runs at most once per Streamlit
    session; subsequent calls reuse the connection.
    """
    db_path = _database_path_or_default(database_path)
    project = _project_root_or_default(project_root)

    if warehouse_needs_build(db_path):
        _check_target_within_project(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with st.spinner("Warehouse not ready. Running ingestion and dbt build ..."):
            run_ingestion(project)
            run_dbt_build(project)

    missing = _missing_relations(db_path)
    if missing:
        raise PipelineError(
            "The warehouse exists but the required relations are missing: "
            f"{', '.join(missing)}. The pipeline finished without creating "
            "them; inspect the dbt build output above."
        )

    try:
        connection = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error as exc:
        raise PipelineError(
            f"Could not open the warehouse read-only at {db_path}. "
            f"If another process is writing to it, close it and retry.\n{exc}"
        ) from exc
    return connection


def connection_for_app(
    database_path: str | Path | None = None,
    project_root: str | Path | None = None,
) -> duckdb.DuckDBPyConnection | None:
    """Streamlit-friendly accessor: renders a readable error instead of raising.

    Pages call this to obtain the shared read-only connection; on bootstrap
    failure the message is shown in the UI and the page stops cleanly.
    """
    try:
        return get_warehouse_connection(database_path, project_root)
    except PipelineError as exc:
        st.error("The warehouse could not be prepared.")
        st.code(str(exc))
        st.info(
            "Fix the reported error (or run the pipeline manually with "
            "`python ingestion/load_excel.py` and `dbt build`), then "
            "reload the app."
        )
        return None


def read_relation(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    schema: str = MART_SCHEMA,
):
    """Read one published consumer relation as an Arrow table.

    The app may read only the required consumer relations through this helper:
    the ``marts.*`` relations and the single ``intermediate`` diagnostic view
    (``int_unmatched_conversions``) allowed by ADR 8. It never reads raw or
    staging relations and never re-implements business joins.
    """
    return connection.execute(
        f'select * from "{schema}"."{table_name}"'
    ).fetch_arrow_table()
