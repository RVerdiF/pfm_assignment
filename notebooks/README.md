# Notebooks

## 01_data_exploration.ipynb

Pre-modeling exploratory data analysis (EDA) of the two source datasets:
TrackNow checkouts and PostHog sessions. It answers, before any dbt layer is
built: how clean is the data, which identifiers are available to join on, and
how likely is an exact match.

## How to run

From the repository root with the virtual environment active:

```bash
jupyter notebook notebooks/01_data_exploration.ipynb
```

The notebook reads the bundled sample workbook with Polars
(`pl.read_excel(...)`, `sheet_id=0` returns all sheets). Its source path is
relative to the checkout, whether Jupyter starts from the repository root or
`notebooks/`.

## What the exploration found

### Sample and identifiers

- Sample scale: TrackNow has 100 rows, PostHog has 200 rows; dates fall inside
  a limited window (May-June 2026).
- TrackNow carries **only** `click_id` among the considered match identifiers;
  `gclid` and `fbclid` exist solely on the PostHog side, plus
  `click_id_from_url`.
- Identifier coverage is partial on both sides. Comparing the available click
  fields tests a candidate relationship; it does not establish a shared namespace.

### Matching potential

- Matching is evaluated with **exact equality only** (no fuzzy matching),
  comparing `TrackNow.click_id` against PostHog `gclid`, `fbclid`, and
  `click_id_from_url`.
- Headline exact-match and fan-out metrics are computed on a deduplicated
  `(tracknow_order_id, session_id)` grain because one PostHog row can expose
  the same logical identifier through more than one column.
- There are zero exact cross-system matches in this sample, so neither
  direction of match fan-out is observed. Multiple candidate sessions are
  covered by synthetic dbt tests; several orders may legitimately share a session.

### Temporal coverage

- TrackNow `created_date` and PostHog `session_date` are compared; unmatched
  orders are checked against the PostHog sample window.
- A temporal constraint (session on or before conversion) is a candidate
  eligibility rule for attribution.

### Unmatched analysis

Two unmatched segments are profiled (presence of `click_id`, `status`,
`firm_id`, date distribution):

1. orders with no `click_id` at all (cannot be matched by design);
2. orders that carry a `click_id` with no PostHog counterpart in the sample.

## How the conclusions guided dbt

The EDA hypotheses became explicit pipeline decisions:

- `click_id` equality is evaluated as a diagnostic, not a proven shared key.
- Each PostHog identifier type (`gclid`, `fbclid`, `click_id_from_url`) is
  evaluated separately, and conversions missing `click_id` are classified
  separately (they cannot be exact-matched; tracked as
  `missing_click_id`).
- A temporal eligibility window (`session_date <= conversion_date`) is applied
  in `int_conversion_attribution`.
- Fan-out is resolved deterministically: typed identifiers outrank
  `click_id_from_url`, then the most recent eligible session wins; ties are
  flagged `ambiguous`.
- Unmatched conversions are not dropped - they are explained by
  `int_unmatched_conversions` with a deterministic `unmatched_reason`
  (`missing_click_id`, `outside_posthog_sample_window`,
  `multiple_candidates`, `click_id_not_found`, `unknown`).

These decisions are recorded in `docs/decisions.md`.