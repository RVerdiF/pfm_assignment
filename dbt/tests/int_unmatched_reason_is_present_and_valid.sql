-- Singular data test: every non-matched conversion carries a reason, and the
-- reason is one of the declared taxonomy values. This pins the acceptance
-- criterion that int_unmatched_conversions never leaves an unexplained row and
-- never invents a status outside the contract.

select conversion_id
from {{ ref('int_unmatched_conversions') }}
where unmatched_reason is null
   or unmatched_reason not in (
        'missing_click_id',
        'outside_posthog_sample_window',
        'multiple_candidates',
        'click_id_not_found',
        'unknown'
   )
