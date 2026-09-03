-- Singular data test: fct_revenue_attribution must contain EXACTLY the valid
-- TrackNow conversions - one row each - with denied conversions excluded and
-- refunded conversions retained.
--
-- Enforced contracts:
--   1. Row parity with the authoritative valid population:
--        every staging row with is_valid_conversion = true appears in the
--        mart, and every mart row is a valid staging conversion. A missing
--        valid conversion (e.g. a denied filter wrongly widened, or a refund
--        dropped) fails here; a denied conversion leaking in also fails.
--   2. One row per conversion (grain conversion_id): duplicates fail.
--   3. Only the statuses a revenue mart may expose appear ('active',
--      'refunded'); 'denied' is excluded by the revenue-layer decision.

with mart as (
    select conversion_id, status
    from {{ ref('fct_revenue_attribution') }}
),
valid_staging as (
    -- The revenue population definition, taken verbatim from the model:
    -- staging rows whose is_valid_conversion flag is true (status <> 'denied'
    -- and status not NULL/unknown).
    select conversion_id, status
    from {{ ref('stg_tracknow_checkouts') }}
    where is_valid_conversion
)

-- 1a. valid staging conversions missing from the mart (dropped / filtered out)
select 'missing valid conversion' as check_name, s.conversion_id
from valid_staging as s
left join mart as m
    on s.conversion_id = m.conversion_id
where m.conversion_id is null

union all

-- 1b. mart conversions that are not valid staging conversions (denied leaked
--     in, or a fabricated identifier)
select 'non-valid conversion present' as check_name, m.conversion_id
from mart as m
left join valid_staging as s
    on m.conversion_id = s.conversion_id
where s.conversion_id is null

union all

-- 2. duplicated grain: one row per conversion
select 'duplicate conversion_id' as check_name, conversion_id
from mart
group by conversion_id
having count(*) > 1

union all

-- 3. forbidden status in the revenue mart
select 'denied status present' as check_name, conversion_id
from mart
where status = 'denied'
