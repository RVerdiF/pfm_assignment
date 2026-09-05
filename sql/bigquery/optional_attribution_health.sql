-- BigQuery consumption asset for the dbt marts.mart_attribution_health table.
-- Replace `project_id` with the target GCP project before execution.
-- The dbt project remains the transformation owner; this query only exposes
-- the published monitoring mart for a BigQuery consumer.
SELECT
  conversion_date,
  utm_source,
  total_conversions,
  matched_conversions,
  unmatched_conversions,
  ambiguous_conversions,
  match_rate,
  unmatched_rate,
  gclid_exact_matches,
  fbclid_exact_matches,
  url_click_exact_matches
FROM `project_id.marts.mart_attribution_health`
ORDER BY conversion_date, utm_source;
