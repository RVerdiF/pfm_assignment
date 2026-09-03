{{ config(materialized='table') }}

-- Mart: attribution health / monitoring.
-- Grain: one row per (conversion_date, utm_source). The optional utm_source
-- dimension is the source of the MATCHED session only; unmatched and ambiguous
-- conversions have no attributed session and therefore fall into the NULL
-- utm_source group (no source was deterministically attributable to them).
--
-- Population: every conversion the attribution engine decided over
-- (int_conversion_attribution keeps all TrackNow conversions, including
-- denied - excluding denied is a revenue-layer decision, not an audit one).
-- Health monitors the attribution machinery itself, so it counts the full
-- decided population rather than the revenue-valid subset; the revenue view is
-- fct_revenue_attribution.
--
-- Metrics (all counts are conversions):
--   total_conversions    conversions decided that date / utm_source group
--   matched_conversions  attribution_status = 'matched'
--   unmatched_conversions attribution_status = 'unmatched'
--   ambiguous_conversions attribution_status = 'ambiguous'
--   match_rate           matched / total   (0..1, NULL when total = 0)
--   unmatched_rate       unmatched / total (0..1, NULL when total = 0)
--   gclid_exact_matches      matched via attribution_identifier_type = 'gclid'
--   fbclid_exact_matches     matched via attribution_identifier_type = 'fbclid'
--   url_click_exact_matches  matched via attribution_identifier_type =
--                            'click_id_from_url'
--
-- This mart is the primary source for the Streamlit monitoring section; it
-- must be consumable without re-implementing any attribution logic.

with attribution as (
    select
        conversion_id,
        conversion_date,
        attribution_status,
        attribution_session_id,
        attribution_identifier_type
    from {{ ref('int_conversion_attribution') }}
),

sessions as (
    select
        session_id,
        utm_source
    from {{ ref('stg_posthog_sessions') }}
),

joined as (
    select
        a.conversion_id,
        a.conversion_date,
        a.attribution_status,
        a.attribution_identifier_type,
        s.utm_source
    from attribution as a
    left join sessions as s
        on s.session_id = a.attribution_session_id
),

grouped as (
    select
        conversion_date,
        utm_source,
        count(*) as total_conversions,
        count(*) filter (where attribution_status = 'matched') as matched_conversions,
        count(*) filter (where attribution_status = 'unmatched') as unmatched_conversions,
        count(*) filter (where attribution_status = 'ambiguous') as ambiguous_conversions,
        count(*) filter (
            where attribution_status = 'matched'
              and attribution_identifier_type = 'gclid'
        ) as gclid_exact_matches,
        count(*) filter (
            where attribution_status = 'matched'
              and attribution_identifier_type = 'fbclid'
        ) as fbclid_exact_matches,
        count(*) filter (
            where attribution_status = 'matched'
              and attribution_identifier_type = 'click_id_from_url'
        ) as url_click_exact_matches
    from joined
    group by conversion_date, utm_source
)

select
    conversion_date,
    utm_source,
    total_conversions,
    matched_conversions,
    unmatched_conversions,
    ambiguous_conversions,
    -- multiply by 1.0 to force floating-point division on every engine;
    -- NULLIF keeps the rate NULL (not an error) for empty groups.
    matched_conversions * 1.0 / nullif(total_conversions, 0) as match_rate,
    unmatched_conversions * 1.0 / nullif(total_conversions, 0) as unmatched_rate,
    gclid_exact_matches,
    fbclid_exact_matches,
    url_click_exact_matches
from grouped
