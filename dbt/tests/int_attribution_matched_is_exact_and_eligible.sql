-- Singular data test: matched rows must reference a real PostHog session that
-- actually carries the attributed click identifier value, and the match must
-- be exact (full-string equality, case preserved). Every 'matched' conversion
-- must have its click_id equal to the identifier value of its attributed
-- session, where the compared column is determined by
-- attribution_identifier_type. The provenance is checked against the staged
-- PostHog session (the layer that owns identifier normalization), not the
-- candidate model, so emission and matching are independently verified.
--
-- The test also asserts the temporal-window contract: an attributed session
-- must never occur after the conversion date (no conversion time is invented;
-- a later-date session is never eligible).

with attributed as (
    select
        a.conversion_id,
        a.conversion_date,
        a.click_id,
        a.attribution_session_id,
        a.attribution_session_date,
        a.attribution_identifier_type
    from {{ ref('int_conversion_attribution') }} as a
    where a.attribution_status = 'matched'
),

raw_session as (
    select
        s.session_id,
        s.session_date,
        s.gclid,
        s.fbclid,
        s.click_id_from_url
    from {{ ref('stg_posthog_sessions') }} as s
)

select a.conversion_id
from attributed as a
left join raw_session as r
    on a.attribution_session_id = r.session_id
where r.session_id is null
   or a.click_id <> case a.attribution_identifier_type
          when 'gclid' then r.gclid
          when 'fbclid' then r.fbclid
          when 'click_id_from_url' then r.click_id_from_url
        end
   or a.attribution_session_date > a.conversion_date
