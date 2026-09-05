"""QuickBooks reconciliation page for the PFM walkthrough.

A pure-prose design page answering Area 2 (Investigation, Integration &
Monitoring): how QuickBooks invoices would be reconciled against TrackNow
commission daily in production. Like the "What I'd do next" page, it reads
no warehouse relation and renders no chart - there is nothing in the
delivered repo to measure - and it never presents the design as implemented.

The full contract (raw fields, model SQL sketch, DQ checks, orchestration)
lives in ``docs/quickbooks_reconciliation_design.md``; the page presents the
short version: architecture, layer grains, the firm mapping strategy, the
reconciliation model and its status taxonomy, the alert output, the DQ
checks, and the boundary statement.
"""
from __future__ import annotations

import streamlit as st

# What the page is: a design answer, not an implementation. Stated once at
# the top so no section can be read as a shipped integration.
DESIGN_INTRO = (
    "**Design only - nothing here is implemented.** This page outlines the daily "
    "automated reconciliation between QuickBooks invoices and TrackNow commission. "
    "The full technical specification (raw schema, SQL sketches, data quality checks, "
    "and orchestration) is documented in `docs/quickbooks_reconciliation_design.md`; "
    "this view summarizes the operational flow."
)

# The two-sided architecture converging on the reconciliation model.
RECONCILIATION_MERMAID = """\
flowchart TD
    subgraph QuickBooks["QuickBooks"]
        qbo["QuickBooks Online"]
        airbyte["Airbyte source<br/>(QuickBooks Online connector, daily incremental)"]
        raw_qb["BigQuery raw_quickbooks.invoices"]
        stg_qb["dbt stg_quickbooks_invoices<br/>(one row per current invoice)"]
        qbo --> airbyte --> raw_qb --> stg_qb
    end

    subgraph TrackNow["TrackNow"]
        raw_tn["raw.tracknow_checkouts"]
        stg_tn["dbt stg_tracknow_checkouts"]
        fct_comm["dbt fct_commission_daily<br/>(one row per commission_date, firm_id)"]
        raw_tn --> stg_tn --> fct_comm
    end

    stg_qb --> recon["dbt int_quickbooks_tracknow_reconciliation<br/>(one row per invoice x firm)"]
    fct_comm --> recon
    recon --> alert_mart["dbt mart_finance_reconciliation_alerts<br/>(active failures)"]
    alert_mart --> notify["Slack / PagerDuty / email"]
"""

# layer, relation, grain, purpose
LAYER_TABLE = (
    (
        "Airbyte / raw",
        "raw_quickbooks.invoices",
        "One row per raw invoice record/version as delivered by Airbyte",
        "Source-shaped landing with Airbyte metadata retained for freshness",
    ),
    (
        "Mapping",
        "dim_firm_accounting_mapping",
        "One row per (firm_id, valid_from) - SCD-style temporal versions",
        "Curated seed bridging QuickBooks customer -> PFM firm; never a name join",
    ),
    (
        "Staging",
        "stg_quickbooks_invoices",
        "One row per current invoice",
        "Dedup by invoice_id (latest updated_at), typed, status derived; no reconciliation logic",
    ),
    (
        "TrackNow",
        "fct_commission_daily",
        "One row per (commission_date, firm_id)",
        "Production daily commission aggregate the invoice is compared against",
    ),
    (
        "Intermediate",
        "int_quickbooks_tracknow_reconciliation",
        "One row per (invoice_id, firm_id) with period_start/period_end",
        "Join both sides over the period, compute deltas, classify the status",
    ),
    (
        "Mart",
        "mart_finance_reconciliation_alerts",
        "One row per active reconciliation failure",
        "Single output contract consumed by the notifier",
    ),
)

# The firm-mapping strategy, stated as the core decision of the design.
MAPPING_STRATEGY = (
    "The key architectural decision is mapping to ``firm_id`` **without "
    "assuming QuickBooks uses the same IDs and without joining on firm name**. "
    "A curated bridge dimension, ``dim_firm_accounting_mapping`` (dbt seed, "
    "one row per (firm_id, valid_from) reviewed by Finance with SCD-style dates), "
    "maps ``quickbooks_customer_id -> firm_id``. Firm name appears only as display "
    "metadata; it is never a join key."
)

# status -> rule, in evaluation order (first match wins).
STATUS_RULES = (
    (
        "currency_mismatch",
        "Invoice currency is not GBP and no conversion contract is defined.",
    ),
    (
        "unmapped_firm",
        "quickbooks_customer_id has no row in the mapping dimension.",
    ),
    (
        "missing_tracknow",
        "tracknow_row_count = 0 - invoice whose period contains no TrackNow commission rows (distinguishes no rows from rows summing to zero).",
    ),
    (
        "missing_quickbooks",
        "Commission period with no covering invoice (inverse-direction rows in the same model).",
    ),
    (
        "matched",
        "absolute delta <= £5 OR pct delta <= 1% - example tolerance, to validate with Finance (dbt var, never hard-coded).",
    ),
    ("variance", "Difference above tolerance."),
)

DQ_CHECKS = (
    # (layer, checks)
    (
        "Airbyte / raw",
        "source freshness; invoice_id not null; schema-drift notification on critical fields.",
    ),
    (
        "Staging",
        "invoice_id unique; numeric/currency validity; customer mapping coverage reported (unmapped is an alert state, never a silent drop).",
    ),
    (
        "Reconciliation",
        "join coverage (every invoice ends in exactly one classified row); amount variance obeys the status rule; both missing sides present.",
    ),
    (
        "Alert mart",
        "alert freshness (detected_at within one run of now).",
    ),
)

ORCHESTRATION_NOTE = (
    "I would run dbt only after the Airbyte sync completes successfully - a "
    "scheduler dependency, never a fixed clock time - then build the staging "
    "-> reconciliation -> alert chain with its tests "
    "(``dbt build --select stg_quickbooks_invoices+``), and let the "
    "notification step read only ``mart_finance_reconciliation_alerts``."
)

# Closing boundary, mirroring the convention of the other prose pages.
NOT_IMPLEMENTED_NOTE = (
    "Nothing in this design is implemented in this repository: there is no "
    "QuickBooks connection, no Airbyte workspace, no BigQuery dataset, and "
    "none of the dbt models above exist. The repo's executable pipeline "
    "remains the local DuckDB sample; this page and the design doc describe "
    "the production answer only."
)


def render() -> None:
    st.header("QuickBooks reconciliation pipeline")
    st.write(DESIGN_INTRO)

    st.subheader("Architecture")
    st.mermaid_chart(RECONCILIATION_MERMAID, width="stretch")

    st.subheader("Layers, relations, and grains")
    st.table(
        {
            "Layer": [row[0] for row in LAYER_TABLE],
            "Relation": [row[1] for row in LAYER_TABLE],
            "Grain": [row[2] for row in LAYER_TABLE],
            "Purpose": [row[3] for row in LAYER_TABLE],
        }
    )

    st.subheader("Firm mapping strategy")
    st.write(MAPPING_STRATEGY)

    st.subheader("Reconciliation statuses")
    for status, rule in STATUS_RULES:
        st.markdown(f"- **`{status}`** - {rule}")

    st.subheader("Data quality checks")
    for layer, checks in DQ_CHECKS:
        st.markdown(f"- **{layer}** - {checks}")

    st.subheader("Orchestration")
    st.write(ORCHESTRATION_NOTE)

    st.caption(NOT_IMPLEMENTED_NOTE)
