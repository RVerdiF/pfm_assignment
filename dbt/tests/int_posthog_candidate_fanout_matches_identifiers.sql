-- Singular data test: total PostHog candidate rows must equal the sum of
-- non-null identifier values across the source staging columns (per row each
-- gclid/fbclid/click_id_from_url is counted once). This pins the UNION ALL
-- fan-out exactly: no identifier is dropped and none is duplicated.
-- Equivalently: candidate count = count(non-null gclid) + count(non-null
-- fbclid) + count(non-null click_id_from_url) over stg_posthog_sessions.

with expected as (
    select
        count(*) filter (where gclid is not null) as n_gclid,
        count(*) filter (where fbclid is not null) as n_fbclid,
        count(*) filter (where click_id_from_url is not null) as n_url
    from {{ ref('stg_posthog_sessions') }}
),

actual as (
    select
        count(*) filter (where identifier_type = 'gclid') as n_gclid,
        count(*) filter (where identifier_type = 'fbclid') as n_fbclid,
        count(*) filter (where identifier_type = 'click_id_from_url') as n_url
    from {{ ref('int_posthog_attribution_candidates') }}
)

select 1 as check_failed
from expected, actual
where
    expected.n_gclid <> actual.n_gclid
    or expected.n_fbclid <> actual.n_fbclid
    or expected.n_url <> actual.n_url
