-- Intermediate model: TrackNow-side attribution candidates.
-- Grain: one row per TrackNow conversion (conversion_id).
--
-- This model prepares the TrackNow side of matching WITHOUT deciding
-- attribution. Every conversion from stg_tracknow_checkouts is preserved
-- (denied rows are kept for audit; they are excluded only in later revenue
-- layers). For each conversion the model carries the identifiers that COULD
-- link it to a PostHog session, plus three explicit presence flags:
--
--   has_click_id             - click_id is present after staging normalization
--   has_affiliate_session_id - affiliate_session_id is present
--   has_tracknow_user_id     - tracknow_user_id is present
--
-- No identifier is treated as a join key in this layer. In particular,
-- affiliate_session_id is never assumed to equal a PostHog session_id (no such
-- bridge exists in the provided data), and no fuzzy matching, priority, or
-- implicit fallback is applied. The flags only document identifier presence so
-- downstream attribution can reason about which links are even possible.

with conversions as (
    select
        conversion_id,
        conversion_date,
        click_id,
        affiliate_session_id,
        tracknow_user_id
    from {{ ref('stg_tracknow_checkouts') }}
)

select
    conversion_id,
    conversion_date,
    click_id,
    affiliate_session_id,
    tracknow_user_id,
    click_id is not null as has_click_id,
    affiliate_session_id is not null as has_affiliate_session_id,
    tracknow_user_id is not null as has_tracknow_user_id
from conversions
