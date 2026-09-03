"""Step 1 - Excel -> DuckDB raw ingestion (Polars).

Reads analytical sheets from an .xlsx file and persists each one as a table in
the `raw` schema of a local DuckDB database. The only transformation applied is
normalizing column names to snake_case; values, nulls, and identifiers are
preserved intact.

Polars is used as the ingestion library: sheets are read with
`polars.read_excel(..., drop_empty_rows=False)` and registered into DuckDB.
`drop_empty_rows=False` keeps fully null rows that live inside a worksheet's
extent, matching the extent contract of the source workbook (no records are
filtered during ingestion).
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import polars as pl

# Mapping: sheet name -> target table in the raw schema.
SHEET_TO_TABLE = {
    "Sample TrackNow Checkouts": "tracknow_checkouts",
    "Sample PostHog Sessions": "posthog_sessions",
}


def to_snake_case(name: str) -> str:
    """Normalize a column name to snake_case.

    Applied rules (without altering identifiers that are already in snake_case):
    - convert to lowercase;
    - split camelCase / PascalCase boundaries;
    - convert spaces and punctuation (parentheses, hyphens, slashes) to underscores;
    - collapse repeated underscores and strip leading/trailing underscores.
    """
    s = name.strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"[\s\-/()\[\].,:;+]+", "_", s)
    s = s.lower()
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def sheet_to_table(sheet_name: str) -> str:
    """Return the target table name for an Excel sheet."""
    try:
        return SHEET_TO_TABLE[sheet_name]
    except KeyError:
        raise ValueError(f"Sheet not mapped for ingestion: {sheet_name!r}") from None


def _read_sheet(excel_path: str, sheet_name: str) -> pl.DataFrame:
    """Read an Excel sheet and normalize column names to snake_case.

    The extent read by polars.read_excel is the source contract: no rows are
    filtered - including completely null rows that exist within the spreadsheet.
    ``drop_empty_rows=False`` preserves such interior fully-null rows instead of
    collapsing them like the calamine default would.
    """
    df = pl.read_excel(excel_path, sheet_name=sheet_name, drop_empty_rows=False)
    df = df.rename({c: to_snake_case(str(c)) for c in df.columns})
    return df


def _dataframe_to_duckdb(con: duckdb.DuckDBPyConnection, table_name: str, df: pl.DataFrame) -> None:
    """Create/replace `raw.<table_name>` from a Polars DataFrame."""
    con.register("df_view", df.to_arrow())
    try:
        con.execute(f"DROP TABLE IF EXISTS raw.{table_name}")
        con.execute(f"CREATE TABLE raw.{table_name} AS SELECT * FROM df_view")
    finally:
        con.unregister("df_view")


def load_excel_into_duckdb(excel_path: str, duckdb_path: str) -> list[str]:
    """Create/load `duckdb_path` and save mapped sheets as tables in the `raw` schema.

    Returns the list of created table names.
    """
    db_path = Path(duckdb_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        created = []
        for sheet_name, table_name in SHEET_TO_TABLE.items():
            df = _read_sheet(excel_path, sheet_name)
            _dataframe_to_duckdb(con, table_name, df)
            created.append(table_name)
        return created
    finally:
        con.close()


def _excel_expected(excel_path: str) -> dict[str, dict]:
    """Return actual count of rows/columns and column names per sheet (Excel reference)."""
    expected = {}
    for sheet_name, table_name in SHEET_TO_TABLE.items():
        df = _read_sheet(excel_path, sheet_name)
        expected[table_name] = {
            "rows": df.height,
            "cols": df.width,
            "columns": list(df.columns),
        }
    return expected


def validate(excel_path: str, duckdb_path: str) -> dict:
    """Reconcile DuckDB raw tables against corresponding Excel sheets.

    Compares: table existence, row count, column count, and column names
    (all normalized to snake_case on the Excel side). Returns a report dictionary
    with metrics and an `all_ok` flag.
    """
    expected = _excel_expected(excel_path)
    con = duckdb.connect(str(duckdb_path))
    try:
        existing = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='raw'"
            ).fetchall()
        }
    finally:
        con.close()

    tables = {}
    all_ok = True
    for table_name in SHEET_TO_TABLE.values():
        exp = expected[table_name]
        if table_name not in existing:
            tables[table_name] = {
                "exists": False,
                "rows": None,
                "cols": None,
                "columns": None,
                "ok": False,
            }
            all_ok = False
            continue

        con = duckdb.connect(str(duckdb_path))
        try:
            row = con.execute(f"SELECT count(*) FROM raw.{table_name}").fetchone()
            rows = row[0] if row is not None else 0
            cols_desc = con.execute(f"DESCRIBE raw.{table_name}").fetchall()
            columns = [r[0] for r in cols_desc]
        finally:
            con.close()

        ok = (
            rows == exp["rows"]
            and len(columns) == exp["cols"]
            and columns == exp["columns"]
        )
        all_ok = all_ok and ok
        tables[table_name] = {
            "exists": True,
            "rows": rows,
            "cols": len(columns),
            "columns": columns,
            "ok": ok,
        }

    return {"all_ok": all_ok, "tables": tables}


def main() -> None:
    import json

    root = Path(__file__).resolve().parent.parent
    excel_path = root / "data" / "source.xlsx"
    duckdb_path = root / "warehouse" / "pfm.duckdb"

    print(f"Loading {excel_path.name} into {duckdb_path} ...")
    created = load_excel_into_duckdb(str(excel_path), str(duckdb_path))
    print("Created tables:", ", ".join(f"raw.{t}" for t in created))

    report = validate(str(excel_path), str(duckdb_path))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["all_ok"]:
        raise SystemExit("Reconciliation failed: Excel and DuckDB diverge.")


if __name__ == "__main__":
    main()
