"""PFM Streamlit walkthrough entrypoint.

The app is a thin read-only consumer of the dbt-published relations: the
marts plus the single ADR-8 diagnostic view (`intermediate.int_unmatched_conversions`).
On startup it ensures the local warehouse exists and satisfies that
required-relation contract: if ``warehouse/pfm.duckdb`` is missing or any
required relation is absent, it runs the canonical pipeline (ingestion then
``dbt build``) once, cached for the Streamlit session, and opens the warehouse
read-only. All attribution decisions and business joins live in dbt; the
Streamlit code never re-implements them.

Pages follow the two assignment areas:

- **Area 1 — Attribution & Data Modeling**: Overview, Attribution analysis,
  Methodology and limitations.
- **Area 2 — Investigation, Integration & Monitoring**: Data quality
  monitoring design, QuickBooks reconciliation pipeline (both pure-prose,
  design-only pages that read no warehouse relation), closing with the
  "What I'd do next" production-evolution outline (also pure prose).

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

from sections import (  # noqa: E402
    analysis,
    methodology,
    monitoring_design,
    next_steps,
    overview,
    quickbooks_reconciliation,
)


def main() -> None:
    st.set_page_config(
        page_title="PFM Conversion Attribution",
        page_icon=":bar_chart:",
        layout="wide",
    )

    pages = {
        "Area 1 — Attribution & data modeling": [
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
        ],
        "Area 2 — Investigation, integration & monitoring": [
            st.Page(
                monitoring_design.render,
                title="Data quality monitoring",
                url_path="monitoring-design",
            ),
            st.Page(
                quickbooks_reconciliation.render,
                title="QuickBooks reconciliation",
                url_path="quickbooks-reconciliation",
            ),
            st.Page(
                next_steps.render,
                title="What I'd do next",
                url_path="next-steps",
            ),
        ],
    }
    navigation = st.navigation(pages)
    navigation.run()


if __name__ == "__main__":
    main()
