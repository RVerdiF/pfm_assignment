-- Singular data test: the PostHog candidates model must emit at least one
-- candidate for every session that carries any click identifier in the staging
-- model. This is the card's "each existing identifier generates a candidate"
-- contract. A session whose gclid, fbclid, or click_id_from_url is non-null
-- but produces zero candidate rows means an identifier was dropped.
--
-- (UNION ALL is used in the model, so a session can legitimately appear
-- multiple times when it carries several identifiers; the anti-join below only
-- checks that no identifier-carrying session is missing entirely.)

select ph.session_id
from {{ ref('stg_posthog_sessions') }} ph
left join {{ ref('int_posthog_attribution_candidates') }} cand
    on ph.session_id = cand.session_id
where
    (
        ph.gclid is not null
        or ph.fbclid is not null
        or ph.click_id_from_url is not null
    )
    and cand.session_id is null
