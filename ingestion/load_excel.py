"""Etapa 1 — Ingestão Excel -> DuckDB raw.

Lê as abas analíticas de um arquivo .xlsx e persiste cada uma como tabela no
schema `raw` de um DuckDB local. A única transformação aplicada é a
normalização dos nomes de colunas para snake_case; valores, nulos e
identificadores são preservados intactos.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

# Mapeamento aba -> tabela alvo no schema raw.
SHEET_TO_TABLE = {
    "Sample TrackNow Checkouts": "tracknow_checkouts",
    "Sample PostHog Sessions": "posthog_sessions",
}


def to_snake_case(name: str) -> str:
    """Normaliza um nome de coluna para snake_case.

    Regras aplicadas (sem alterar identificadores que já estão em snake_case):
    - converte para minúsculas;
    - quebra limites camelCase / PascalCase;
    - converte espaços e pontuação (parênteses, hífens, barras) em underscore;
    - colapsa underscores repetidos e remove underscores nas bordas.
    """
    s = name.strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"[\s\-/()\[\].,:;+]+", "_", s)
    s = s.lower()
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def sheet_to_table(sheet_name: str) -> str:
    """Nome da tabela alvo para uma aba do Excel."""
    try:
        return SHEET_TO_TABLE[sheet_name]
    except KeyError:
        raise ValueError(f"aba não mapeada para ingestão: {sheet_name!r}") from None


def _read_sheet(excel_path: str, sheet_name: str) -> pd.DataFrame:
    """Lê uma aba e aplica snake_case nos nomes das colunas.

    O extent lido pelo pandas.read_excel é o contrato da fonte: nenhuma linha é
    filtrada — inclusive linhas totalmente nulas que existam dentro da planilha.
    """
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    df.columns = [to_snake_case(str(c)) for c in df.columns]
    return df


def load_excel_into_duckdb(excel_path: str, duckdb_path: str) -> list[str]:
    """Cria/carrega `duckdb_path` e grava as abas mapeadas como tabelas no
    schema `raw`. Retorna a lista das tabelas criadas."""
    db_path = Path(duckdb_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        created = []
        for sheet_name, table_name in SHEET_TO_TABLE.items():
            df = _read_sheet(excel_path, sheet_name)
            con.register("df_view", df)
            con.execute(f"DROP TABLE IF EXISTS raw.{table_name}")
            con.execute(f"CREATE TABLE raw.{table_name} AS SELECT * FROM df_view")
            con.unregister("df_view")
            created.append(table_name)
        return created
    finally:
        con.close()


def _excel_expected(excel_path: str) -> dict[str, dict]:
    """Contagem real de linhas/colunas/nomes por aba (referência do Excel)."""
    expected = {}
    for sheet_name, table_name in SHEET_TO_TABLE.items():
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        df.columns = [to_snake_case(str(c)) for c in df.columns]
        expected[table_name] = {
            "rows": len(df),
            "cols": len(df.columns),
            "columns": list(df.columns),
        }
    return expected


def validate(excel_path: str, duckdb_path: str) -> dict:
    """Reconcilia as tabelas raw do DuckDB com as abas correspondentes do Excel.

    Compara: existência das tabelas, nº de linhas, nº de colunas e nomes de
    colunas (todos normalizados para snake_case no lado Excel). Retorna um
    relatório com os números e a flag `all_ok`.
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
            tables[table_name] = {"exists": False, "rows": None, "cols": None,
                                  "columns": None, "ok": False}
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

    print(f"Carregando {excel_path.name} em {duckdb_path} ...")
    created = load_excel_into_duckdb(str(excel_path), str(duckdb_path))
    print("Tabelas criadas:", ", ".join(f"raw.{t}" for t in created))

    report = validate(str(excel_path), str(duckdb_path))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["all_ok"]:
        raise SystemExit("Reconciliação falhou: Excel e DuckDB divergem.")


if __name__ == "__main__":
    main()
