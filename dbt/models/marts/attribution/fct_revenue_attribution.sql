{{ config(materialized='table') }}

-- Mart: revenue attribution fact.
-- Grain: one row per VALID TrackNow conversion (conversion_id).
--
-- Population rule (revenue layer decision):
--   valid conversion = staging is_valid_conversion = true, i.e. the normalized
--   status is neither 'denied' nor NULL (unknown). 'denied' conversions are
--   excluded here - that is a revenue decision, not an audit one (the audit
--   table int_conversion_attribution keeps them). 'refunded' conversions are
--   KEPT with their status explicit: no business rule was provided to zero or
--   remove commission on refunds, so the mart does not invent one.
--
-- Commission rule:
--   commission_gbp always comes from stg_tracknow_checkouts.commission_gbp,
--   which is the staging alias of the raw referral_bonus_gbp column - the Data
--   Dictionary identifies it as the correct per-order PFM commission metric.
--
-- Attribution fields are carried from int_conversion_attribution (the single
-- decision maker) and enriched with the matched PostHog session's marketing
-- parameters. Nothing is re-decided here and no join inside Streamlit is
-- required: the attribution decision, the matched session identifiers, and the
-- session's UTM parameters are all exposed on this one row per conversion.
--
-- Column naming contract for downstream consumers:
--   match_status        = attribution_status (matched/unmatched/ambiguous)
--   matched_session_id  = attribution_session_id (NULL unless matched)
--   matched_distinct_id = PostHog distinct_id of the matched session
--   match_method        = how the exact match was made:
--                         'gclid_exact' | 'fbclid_exact' | 'url_click_exact'
--                         (NULL unless matched)
--   channel             = acquiring marketing channel (from utm_source; NULL unless matched)
--   campaign            = marketing campaign (from utm_campaign; NULL unless matched)
--   ad_id               = ad identifier (from utm_content, carrying Meta ad_id where applicable; NULL unless matched)
--   utm_*               = raw UTM parameters of the MATCHED session only. An
--                         unmatched/ambiguous conversion has no attributed
--                         session, therefore no UTM is invented.

with conversions as (
    -- One row per conversion with the deterministic attribution decision.
    select
        conversion_id,
        conversion_date,
        attribution_status,
        attribution_session_id,
        attribution_identifier_type
    from {{ ref('int_conversion_attribution') }}
),

orders as (
    -- Revenue facts from the clean staging interface. Only valid conversions
    -- (status <> 'denied', status not NULL/unknown) enter the revenue mart.
    select
        conversion_id,
        firm_id,
        status,
        commission_gbp
    from {{ ref('stg_tracknow_checkouts') }}
    where is_valid_conversion
),

matched_sessions as (
    -- Session-level context for MATCHED conversions only. The left join below
    -- keyed on attribution_session_id keeps unmatched/ambiguous rows NULL.
    select
        session_id,
        distinct_id,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_content
    from {{ ref('stg_posthog_sessions') }}
)

select
    cv.conversion_id,
    cv.conversion_date,
    od.firm_id,
    od.status,
    od.commission_gbp,
    -- attribution decision, renamed for the consumption layer
    cv.attribution_status as match_status,
    cv.attribution_session_id as matched_session_id,
    ms.distinct_id as matched_distinct_id,
    -- match_method maps the identifier that produced the exact match into a
    -- stable controlled vocabulary; NULL unless the conversion is matched.
    case
        when cv.attribution_status = 'matched' and cv.attribution_identifier_type = 'gclid'
            then 'gclid_exact'
        when cv.attribution_status = 'matched' and cv.attribution_identifier_type = 'fbclid'
            then 'fbclid_exact'
        when cv.attribution_status = 'matched' and cv.attribution_identifier_type = 'click_id_from_url'
            then 'url_click_exact'
        else null
    end as match_method,
    -- Explicit marketing attribution dimensions required by the assignment
    -- (channel, campaign, ad / ad_id, session, firm, commission per conversion):
    ms.utm_source as channel,
    ms.utm_campaign as campaign,
    -- utm_content carries the ad identifier (e.g. Meta ad_id) where applicable
    ms.utm_content as ad_id,
    -- Raw UTM parameters preserved for technical consumers
    ms.utm_source,
    ms.utm_medium,
    ms.utm_campaign,
    ms.utm_content
from conversions as cv
inner join orders as od
    on od.conversion_id = cv.conversion_id
left join matched_sessions as ms
    on ms.session_id = cv.attribution_session_id
