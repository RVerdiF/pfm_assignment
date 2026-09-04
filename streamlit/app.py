"""PFM Streamlit walkthrough entrypoint.

The app is a thin read-only consumer of the dbt-published relations: the
marts plus the single ADR-8 diagnostic view (`intermediate.int_unmatched_conversions`).
On startup it ensures the local warehouse exists and satisfies that
required-relation contract: if ``warehouse/pfm.duckdb`` is missing or any
required relation is absent, it runs the canonical pipeline (ingestion then
``dbt build``) once, cached for the Streamlit session, and opens the warehouse
read-only. All attribution decisions and business joins live in dbt; the
Streamlit code never re-implements them.

Launch from the repository root:

    streamlit run streamlit/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Allow absolute imports of sibling modules (sections.*, warehouse_bootstrap)
# regardless of how the script is launched.
STREAMLIT_DIR = Path(__file__).resolve().parent
if str(STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_DIR))

from sections import analysis, methodology, overview  # noqa: E402


def main() -> None:
    st.set_page_config(
        page_title="PFM Conversion Attribution",
        page_icon=":bar_chart:",
        layout="wide",
    )

    pages = [
        st.Page(
            overview.render,
            title="Overview",
            url_path="overview",
            default=True,
        ),
        st.Page(
            analysis.render,
            title="Attribution analysis",
            url_path="analysis",
        ),
        st.Page(
            methodology.render,
            title="Methodology and limitations",
            url_path="methodology",
        ),
    ]
    navigation = st.navigation(pages)
    navigation.run()


if __name__ == "__main__":
    main()
