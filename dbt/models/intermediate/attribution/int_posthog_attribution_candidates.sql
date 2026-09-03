-- Intermediate model: PostHog-side attribution candidates.
--
-- PostHog sessions carry click identifiers in three separate columns:
--   gclid            - Google click id (Ads click parameter)
--   fbclid           - Meta/Facebook click id (Ads click parameter)
--   click_id_from_url - raw click id extracted from the landing URL
--                        (in this dataset it duplicates gclid or fbclid)
--
-- The card asks for one candidate row per EXISTING identifier value: a UNION
-- ALL over the three identifier columns yields one row per (session, column,
-- value) where that column is present. A session contributes:
--   - one gclid candidate            when gclid is present,
--   - one fbclid candidate           when fbclid is present,
--   - one click_id_from_url candidate when click_id_from_url is present.
-- Sessions without any identifier simply contribute no candidate rows here.
--
-- Attribution is NOT decided in this layer: no exact match against TrackNow
-- happens yet, no priority ordering is applied, and no fallback is assumed.
-- This model only makes each existing identifier observable as a candidate
-- that a later exact-match layer can consume.

with sessions as (
    select
        session_id,
        gclid,
        fbclid,
        click_id_from_url
    from {{ ref('stg_posthog_sessions') }}
),

unnested as (
    select session_id, gclid as identifier_value, 'gclid' as identifier_type
    from sessions
    where gclid is not null

    union all

    select session_id, fbclid as identifier_value, 'fbclid' as identifier_type
    from sessions
    where fbclid is not null

    union all

    select session_id, click_id_from_url as identifier_value, 'click_id_from_url' as identifier_type
    from sessions
    where click_id_from_url is not null
)

select
    session_id,
    identifier_type,
    identifier_value
from unnested
