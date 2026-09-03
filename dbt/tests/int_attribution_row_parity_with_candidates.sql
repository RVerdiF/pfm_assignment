-- Singular data test: row parity with the TrackNow candidate layer. The
-- attribution model must preserve every conversion exactly once (no drop, no
-- duplication). This pins the acceptance criterion that the attribution
-- output matches the upstream candidate count.

with expected as (
    select count(*) as n from {{ ref('int_tracknow_attribution_candidates') }}
),
actual as (
    select count(*) as n from {{ ref('int_conversion_attribution') }}
)

select 1 as check_failed
from expected, actual
where expected.n <> actual.n
