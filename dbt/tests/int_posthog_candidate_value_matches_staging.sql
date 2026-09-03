-- Singular data test: every PostHog candidate identifier_value must match the
-- non-null value published by the source staging row for its identifier_type.
-- Guards against the UNION ALL branches selecting the wrong column or applying
-- an unintended transformation (e.g. lowercasing or coercing one identifier
-- type into another), which would break later exact matching.

select cand.session_id, cand.identifier_type, cand.identifier_value
from {{ ref('int_posthog_attribution_candidates') }} cand
left join {{ ref('stg_posthog_sessions') }} ph
    on cand.session_id = ph.session_id
where
    (cand.identifier_type = 'gclid' and cand.identifier_value is distinct from ph.gclid)
    or (cand.identifier_type = 'fbclid' and cand.identifier_value is distinct from ph.fbclid)
    or (cand.identifier_type = 'click_id_from_url' and cand.identifier_value is distinct from ph.click_id_from_url)
