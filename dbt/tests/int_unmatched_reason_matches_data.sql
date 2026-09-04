-- Singular data test: each unmatched_reason is used only where the underlying
-- data supports it. Guards the deterministic classification contract:
--
--   missing_click_id               -> conversion has no click_id (and the
--                                     parent therefore said 'unmatched').
--   multiple_candidates            -> parent said 'ambiguous'.
--   click_id_not_found             -> has a click_id, its date is inside the
--                                     sample window (>= first session date),
--                                     and no exact identifier value match
--                                     exists anywhere in the sample.
--   outside_posthog_sample_window  -> has a click_id but no exact match is
--                                     eligible on or before the conversion
--                                     date (conversion predates the sample or
--                                     the id only appears on later sessions).
--   unknown                        -> has a click_id and exact matches exist,
--                                     but none carries a usable session_date.
--
-- Rows that contradict their reason (e.g. a click_id_not_found row that
-- actually has an exact match) are reported as failures.

with sample_window as (
    select min(session_date) as first_session_date
    from {{ ref('stg_posthog_sessions') }}
),

exact_match_dates as (
    select
        pc.identifier_value,
        min(s.session_date) as earliest_matching_session_date,
        count(s.session_date) as dated_matching_sessions,
        count(*) as matching_sessions_total
    from {{ ref('int_posthog_attribution_candidates') }} as pc
    left join {{ ref('stg_posthog_sessions') }} as s
        on s.session_id = pc.session_id
    group by pc.identifier_value
),

violations as (
    select u.conversion_id
    from {{ ref('int_unmatched_conversions') }} as u
    cross join sample_window as w
    left join exact_match_dates as em
        on em.identifier_value = u.click_id
    where
        -- missing_click_id requires no click id and an unmatched parent
        (
            u.unmatched_reason = 'missing_click_id'
            and (u.has_click_id or u.attribution_status <> 'unmatched')
        )
        -- multiple_candidates requires an ambiguous parent
        or (
            u.unmatched_reason = 'multiple_candidates'
            and u.attribution_status <> 'ambiguous'
        )
        -- click_id_not_found requires a click id inside the sample window
        -- with no exact match anywhere
        or (
            u.unmatched_reason = 'click_id_not_found'
            and (
                not u.has_click_id
                or u.conversion_date < w.first_session_date
                or em.matching_sessions_total > 0
            )
        )
        -- outside_posthog_sample_window requires a click id whose every exact
        -- match (if any) is dated strictly after the conversion or undated
        or (
            u.unmatched_reason = 'outside_posthog_sample_window'
            and (
                not u.has_click_id
                or em.matching_sessions_total = 0
                or em.earliest_matching_session_date <= u.conversion_date
            )
        )
        -- unknown requires a click id with exact matches but no dated match
        or (
            u.unmatched_reason = 'unknown'
            and (
                not u.has_click_id
                or em.matching_sessions_total = 0
                or em.dated_matching_sessions > 0
            )
        )
)

select conversion_id
from violations
