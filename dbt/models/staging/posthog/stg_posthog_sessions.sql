-- Staging model for PostHog web sessions.
-- Grain: one row per PostHog session (session_id).
-- Clean, stable interface over the raw PostHog data. Attribution is NOT
-- performed in this layer. Click IDs keep their original case.

with source as (
    select * from {{ source('raw', 'posthog_sessions') }}
),

cleaned as (
    select
        -- identifiers and marketing params: trim then empty string -> NULL;
        -- case is preserved (click IDs can be case-sensitive).
        nullif(trim(posthog_distinct_id), '') as distinct_id,
        -- session_id is the declared grain key; trim it like every other
        -- string key so the cleaned interface never exposes whitespace
        -- padding, and whitespace-only values become NULL (which the
        -- not_null + unique schema tests would then catch).
        nullif(trim(session_id), '') as session_id,
        cast(session_date as date) as session_date,
        -- Raw values are UTC (+00:00); cast to timestamptz keeps the timezone.
        cast(session_start_at as timestamptz) as session_start_at,
        session_duration_seconds,
        nullif(trim(click_id_from_url), '') as click_id_from_url,
        nullif(trim(gclid), '') as gclid,
        nullif(trim(fbclid), '') as fbclid,
        nullif(trim(utm_source), '') as utm_source,
        nullif(trim(utm_medium), '') as utm_medium,
        nullif(trim(utm_campaign), '') as utm_campaign,
        nullif(trim(utm_content), '') as utm_content,
        nullif(trim(country_code), '') as country_code,
        nullif(trim(session_entry_pathname), '') as session_entry_pathname,
        cast(has_checkout_started as boolean) as has_checkout_started,
        cast(has_tracknow_conversion as boolean) as has_tracknow_conversion,
        events_in_session
    from source
)

select * from cleaned
