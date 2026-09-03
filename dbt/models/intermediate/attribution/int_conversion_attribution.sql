{{ config(materialized='table') }}

-- Intermediate model: deterministic conversion-to-session attribution.
-- Grain: one row per TrackNow conversion (conversion_id). Every conversion in
-- int_tracknow_attribution_candidates appears exactly once (denied conversions
-- are kept: excluding them is a revenue-layer decision, not an audit one).
--
-- Attribution is decided ONLY through an EXACT equality of the TrackNow
-- click_id and a PostHog click identifier value (gclid, fbclid, or
-- click_id_from_url) emitted by int_posthog_attribution_candidates. No fuzzy
-- matching, no invented conversion time, and no affiliate_session_id =
-- session_id bridge is used. The decision is fully deterministic and is
-- described by four ordered rules:
--
--   1. Exact match       a conversion is attributable only when its click_id
--                        equals a PostHog identifier value. Conversions
--                        without a click_id can never be attributed
--                        ('unmatched').
--   2. Temporal window   among matching sessions, only sessions whose
--                        session_date does not occur after the conversion
--                        date are eligible (session_date <= conversion_date).
--                        TrackNow exposes only created_date - a DATE, never a
--                        time - so no conversion time is invented: every
--                        session on the conversion date itself is eligible
--                        and sessions on later dates are excluded. Sessions
--                        with an unknown session_date cannot be proven
--                        eligible and are excluded.
--   3. Identifier        among eligible sessions, typed identifiers (gclid,
--       priority         fbclid) outrank the generic click_id_from_url.
--   4. Recency           among eligible sessions of the winning priority, the
--                        most recent session (largest session_start_at) is
--                        chosen. A session whose start time is unknown is
--                        treated as least recent (sorted last); when every
--                        tied candidate has an unknown start time no recency
--                        decision is deterministically resolvable.
--
-- Decision status ('attribution_status'):
--   matched   exactly one eligible session survives rules 2-4
--   ambiguous more than one eligible session ties for first under rules 3-4
--             (identical priority and identical most-recent start time, or
--             identical priority with every tied start time unknown)
--   unmatched no exact eligible match exists (no click_id, no value match,
--             or only sessions after the conversion date)
--
-- Columns attribution_session_id / _date / _start_at / _identifier_type are
-- populated only for 'matched' rows; 'unmatched' and 'ambiguous' rows carry
-- NULL for all of them.

with conversions as (
    select
        conversion_id,
        conversion_date,
        click_id,
        affiliate_session_id,
        tracknow_user_id,
        has_click_id,
        has_affiliate_session_id,
        has_tracknow_user_id
    from {{ ref('int_tracknow_attribution_candidates') }}
),

-- PostHog identifier candidates enriched with the session occurrence date and
-- start time (needed for the temporal window and recency rules). The candidate
-- model remains the single source of identifier emission; joining staging for
-- session timing adds context only.
candidate_sessions as (
    select
        c.session_id,
        c.identifier_type,
        c.identifier_value,
        s.session_date,
        s.session_start_at,
        -- 0 = typed (gclid/fbclid), 1 = generic click id from URL
        case when c.identifier_type in ('gclid', 'fbclid') then 0 else 1 end as identifier_priority
    from {{ ref('int_posthog_attribution_candidates') }} as c
    left join {{ ref('stg_posthog_sessions') }} as s
        on c.session_id = s.session_id
),

exact_matches as (
    -- Rule 1: exact equality between the TrackNow click id and a PostHog
    -- identifier value. A conversion without a click id can never match.
    select
        cv.conversion_id,
        cv.conversion_date,
        cs.session_id,
        cs.session_date,
        cs.session_start_at,
        cs.identifier_type,
        cs.identifier_priority
    from conversions as cv
    join candidate_sessions as cs
        on cv.click_id = cs.identifier_value
    where cv.has_click_id
),

eligible_matches as (
    -- Rule 2: temporal eligibility. See the header comment for why the date
    -- grain is the only deterministic boundary available.
    select *
    from exact_matches
    where session_date is not null
      and session_date <= conversion_date
),

session_matches as (
    -- Collapse to one row per (conversion, session): a session matching a
    -- conversion through both a typed and the generic click identifier is
    -- still ONE session. identifier_priority keeps the best (lowest) priority
    -- present; the reported identifier_type is a typed value whenever one
    -- matched (if a session ever carried both gclid and fbclid for the same
    -- value - pathological - the lexicographically smallest typed value is
    -- reported; the priority class is identical either way), otherwise
    -- click_id_from_url.
    select
        conversion_id,
        conversion_date,
        session_id,
        session_date,
        session_start_at,
        min(identifier_priority) as identifier_priority,
        coalesce(
            min(identifier_type) filter (where identifier_priority = 0),
            min(identifier_type)
        ) as identifier_type
    from eligible_matches
    group by conversion_id, conversion_date, session_id, session_date, session_start_at
),

ranked as (
    -- Rules 3-4 in one ordering: better (lower) priority first, then more
    -- recent session_start_at first. NULL start times sort last (least
    -- recent). RANK keeps ties visible so ambiguity is detectable.
    select
        conversion_id,
        session_id,
        session_date,
        session_start_at,
        identifier_type,
        rank() over (
            partition by conversion_id
            order by identifier_priority asc, session_start_at desc nulls last
        ) as match_rank
    from session_matches
),

finalists as (
    select *
    from ranked
    where match_rank = 1
),

decision as (
    select
        conversion_id,
        count(*) as candidate_session_count,
        min(session_id) as decision_session_id,
        min(session_date) as decision_session_date,
        min(session_start_at) as decision_session_start_at,
        min(identifier_type) as decision_identifier_type
    from finalists
    group by conversion_id
),

attributed as (
    select
        cv.conversion_id,
        cv.conversion_date,
        cv.click_id,
        cv.affiliate_session_id,
        cv.tracknow_user_id,
        cv.has_click_id,
        cv.has_affiliate_session_id,
        cv.has_tracknow_user_id,
        case
            when d.candidate_session_count = 1 then 'matched'
            when d.candidate_session_count > 1 then 'ambiguous'
            else 'unmatched'
        end as attribution_status,
        case when d.candidate_session_count = 1 then d.decision_session_id end as attribution_session_id,
        case when d.candidate_session_count = 1 then d.decision_session_date end as attribution_session_date,
        case when d.candidate_session_count = 1 then d.decision_session_start_at end as attribution_session_start_at,
        case when d.candidate_session_count = 1 then d.decision_identifier_type end as attribution_identifier_type
    from conversions as cv
    left join decision as d
        on cv.conversion_id = d.conversion_id
)

select * from attributed
