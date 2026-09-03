-- Singular data test: unmatched investigation totals reconcile with the
-- attribution output. int_unmatched_conversions is a strict filtered
-- projection of int_conversion_attribution, so every 'unmatched' or
-- 'ambiguous' conversion must appear exactly once and no 'matched' conversion
-- may leak into the diagnostic. Row parity between the two models follows
-- from these two conditions combined with the parent's own no-fanout test.

with parent_non_matched as (
    select conversion_id
    from {{ ref('int_conversion_attribution') }}
    where attribution_status <> 'matched'
),

investigated as (
    select conversion_id
    from {{ ref('int_unmatched_conversions') }}
),

-- Every conversion the parent reports as non-matched must be present exactly
-- once in the investigation output.
missing_from_investigation as (
    select p.conversion_id
    from parent_non_matched as p
    left join investigated as i
        on i.conversion_id = p.conversion_id
    where i.conversion_id is null
),

-- No conversion outside the parent's non-matched set may appear.
extra_in_investigation as (
    select i.conversion_id
    from investigated as i
    left join parent_non_matched as p
        on p.conversion_id = i.conversion_id
    where p.conversion_id is null
),

-- Grain: one row per conversion (no fan-out in the diagnostic).
duplicated_investigation as (
    select conversion_id
    from investigated
    group by conversion_id
    having count(*) > 1
)

select conversion_id
from missing_from_investigation

union all

select conversion_id
from extra_in_investigation

union all

select conversion_id
from duplicated_investigation
