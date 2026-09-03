-- Intermediate model: diagnostic dataset explaining why TrackNow conversions
-- were not attributed to a PostHog session.
--
-- Grain: one row per conversion whose decision in int_conversion_attribution
-- is not 'matched' (i.e. 'unmatched' or 'ambiguous'). This model is a strict
-- filtered projection of the attribution table (one output row per non-matched
-- input row, no fan-out), so row totals always reconcile with
-- int_conversion_attribution.
--
-- Materialized as a view (the project's intermediate default) so the
-- diagnostic always mirrors the latest attribution decision; the parent table
-- is cheap to re-scan.
--
-- Attribution is never re-decided here. Each row only EXPLAINS the
-- attribution_status already computed by int_conversion_attribution, using the
-- same inputs that model used: exact click_id equality against PostHog
-- identifier values and the session_date <= conversion_date eligibility
-- window. No fuzzy matching, no affiliate_session_id = session_id bridge, and
-- no tracknow_user_id = distinct_id inference are introduced.
--
-- unmatched_reason taxonomy (deterministic, first match wins):
--   missing_click_id                the conversion has no click_id; under
--                                   exact-only matching it can never be
--                                   attributed.
--   multiple_candidates             attribution_status = 'ambiguous': more
--                                   than one eligible session tied for first
--                                   under identifier priority + recency, so no
--                                   single session was chosen.
--   outside_posthog_sample_window   the PostHog sample cannot contain an
--                                   eligible session for this conversion: the
--                                   conversion predates the sample's first
--                                   session (conversion_date < first session
--                                   date) or the click_id is observed only on
--                                   sessions dated after the conversion.
--   click_id_not_found              the click_id equals no PostHog identifier
--                                   value anywhere in the sample (exact
--                                   equality, case preserved), while the
--                                   conversion date falls within the sample
--                                   window.
--   unknown                         residual: an exact match exists but none
--                                   of its sessions carries a usable
--                                   session_date, so temporal eligibility
--                                   cannot be established.

with conversions as (
    select
        conversion_id,
        conversion_date,
        click_id,
        affiliate_session_id,
        tracknow_user_id,
        has_click_id,
        has_affiliate_session_id,
        has_tracknow_user_id,
        attribution_status
    from {{ ref('int_conversion_attribution') }}
    where attribution_status <> 'matched'
),

posthog_window as (
    -- The earliest session date captured by the PostHog sample. Conversions
    -- dated before it cannot have any session on or before their date, so they
    -- fall outside the sample window by construction.
    select min(session_date) as first_session_date
    from {{ ref('stg_posthog_sessions') }}
),

-- Exact click_id -> PostHog identifier lookups for the non-matched
-- conversions. The join mirrors int_conversion_attribution's exact-match rule
-- (cv.click_id = pc.identifier_value, case preserved); session_date is
-- carried so the temporal eligibility rule can be re-expressed for diagnosis.
click_lookup as (
    select
        cv.conversion_id,
        count(pc.session_id) as exact_match_count,
        min(s.session_date) as first_matching_session_date
    from conversions as cv
    left join {{ ref('int_posthog_attribution_candidates') }} as pc
        on pc.identifier_value = cv.click_id
    left join {{ ref('stg_posthog_sessions') }} as s
        on s.session_id = pc.session_id
    group by cv.conversion_id
),

classified as (
    select
        cv.conversion_id,
        cv.conversion_date,
        cv.click_id,
        cv.affiliate_session_id,
        cv.tracknow_user_id,
        cv.has_click_id,
        cv.has_affiliate_session_id,
        cv.has_tracknow_user_id,
        cv.attribution_status,
        case
            when not cv.has_click_id then 'missing_click_id'
            when cv.attribution_status = 'ambiguous' then 'multiple_candidates'
            when cv.conversion_date < w.first_session_date then 'outside_posthog_sample_window'
            when cl.exact_match_count = 0 then 'click_id_not_found'
            when cl.first_matching_session_date > cv.conversion_date
                then 'outside_posthog_sample_window'
            else 'unknown'
        end as unmatched_reason
    from conversions as cv
    cross join posthog_window as w
    left join click_lookup as cl
        on cl.conversion_id = cv.conversion_id
)

select * from classified
