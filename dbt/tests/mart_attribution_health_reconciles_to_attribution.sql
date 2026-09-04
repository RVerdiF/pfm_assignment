-- Singular data test: mart_attribution_health must reconcile to the decided
-- population and expose internally coherent components and rates.
--
-- mart_attribution_health groups every conversion the attribution engine
-- decided over (int_conversion_attribution, which keeps denied conversions
-- too: health monitors the machinery) by (conversion_date, utm_source).
-- Because each conversion maps to exactly one output row, the mart's sums
-- must equal the global population counts regardless of the utm_source
-- grouping.
--
-- Enforced contracts:
--   1. Grain uniqueness: at most one row per (conversion_date, utm_source).
--   2. Population reconciliation: the mart's sums equal the decided
--      population counts in int_conversion_attribution - total and per
--      status (matched / unmatched / ambiguous), plus the exact-match
--      identifier counters. Scalar subqueries make the check non-vacuous:
--      an EMPTY mart fails here.
--   3. Component additivity: matched + unmatched + ambiguous = total per row.
--   4. Rate coherence: match_rate = matched / total and
--      unmatched_rate = unmatched / total on every row (tolerance 1e-9);
--      a rate outside [0, 1] fails.
--   5. Identifier-tool reconciliation: the exact-match counters (gclid,
--      fbclid, url click) never exceed the matched count on their row.

with mart as (
    select
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
    from {{ ref('mart_attribution_health') }}
),
decided as (
    select
        count(*) as total_population,
        count(*) filter (where attribution_status = 'matched') as matched_population,
        count(*) filter (where attribution_status = 'unmatched') as unmatched_population,
        count(*) filter (where attribution_status = 'ambiguous') as ambiguous_population,
        count(*) filter (
            where attribution_status = 'matched' and attribution_identifier_type = 'gclid'
        ) as gclid_population,
        count(*) filter (
            where attribution_status = 'matched' and attribution_identifier_type = 'fbclid'
        ) as fbclid_population,
        count(*) filter (
            where attribution_status = 'matched' and attribution_identifier_type = 'click_id_from_url'
        ) as url_population
    from {{ ref('int_conversion_attribution') }}
)

-- 1. duplicated grain
select 'duplicate (conversion_date, utm_source)' as check_name, null::date as conversion_date, null::varchar as detail
from mart
group by conversion_date, utm_source
having count(*) > 1

union all

-- 2. population reconciliation (totals, status components, identifier tools).
--    scalar subqueries over the mart keep this non-vacuous for an empty mart.
select 'population mismatch' as check_name, null::date as conversion_date, null::varchar as detail
from decided
where coalesce((select sum(total_conversions) from mart), 0) <> total_population
   or coalesce((select sum(matched_conversions) from mart), 0) <> matched_population
   or coalesce((select sum(unmatched_conversions) from mart), 0) <> unmatched_population
   or coalesce((select sum(ambiguous_conversions) from mart), 0) <> ambiguous_population
   or coalesce((select sum(gclid_exact_matches) from mart), 0) <> gclid_population
   or coalesce((select sum(fbclid_exact_matches) from mart), 0) <> fbclid_population
   or coalesce((select sum(url_click_exact_matches) from mart), 0) <> url_population

union all

-- 3. components add up to the row total
select 'component sum mismatch' as check_name, conversion_date, utm_source::varchar as detail
from mart
where matched_conversions + unmatched_conversions + ambiguous_conversions <> total_conversions

union all

-- 4. rates are exact quotients (and therefore within [0, 1])
select 'rate mismatch' as check_name, conversion_date, utm_source::varchar as detail
from mart
where total_conversions > 0
  and (
        abs(match_rate - (matched_conversions * 1.0 / total_conversions)) > 1e-9
     or abs(unmatched_rate - (unmatched_conversions * 1.0 / total_conversions)) > 1e-9
  )

union all

-- 5. identifier counters never exceed the matched count on their row
select 'identifier counter exceeds matched' as check_name, conversion_date, utm_source::varchar as detail
from mart
where gclid_exact_matches + fbclid_exact_matches + url_click_exact_matches > matched_conversions
