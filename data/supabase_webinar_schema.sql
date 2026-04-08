-- Webinar Email Tracking — tracks which emails each registrant received
-- Run this in your MAIN BuildLoop Supabase SQL Editor (not backoffice)

-- Add tracking columns to existing webinar_registrations table
ALTER TABLE webinar_registrations
ADD COLUMN IF NOT EXISTS welcome_email_sent_at timestamptz,
ADD COLUMN IF NOT EXISTS reminder_1_sent_at timestamptz,    -- day before
ADD COLUMN IF NOT EXISTS reminder_2_sent_at timestamptz,    -- 2 hours before
ADD COLUMN IF NOT EXISTS reminder_3_sent_at timestamptz,    -- at start
ADD COLUMN IF NOT EXISTS reminder_4_sent_at timestamptz,    -- 30 min in
ADD COLUMN IF NOT EXISTS post_1_sent_at timestamptz,        -- 1h after (replay + offer)
ADD COLUMN IF NOT EXISTS post_2_sent_at timestamptz,        -- day 2 (social proof)
ADD COLUMN IF NOT EXISTS post_3_sent_at timestamptz,        -- day 4 (objection handling)
ADD COLUMN IF NOT EXISTS post_4_sent_at timestamptz,        -- day 7 (the math)
ADD COLUMN IF NOT EXISTS post_5_sent_at timestamptz,        -- day 10 (downsell)
ADD COLUMN IF NOT EXISTS post_6_sent_at timestamptz,        -- day 12 (new webinar)
ADD COLUMN IF NOT EXISTS post_7_sent_at timestamptz,        -- day 14 (final)
ADD COLUMN IF NOT EXISTS attended boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS purchased boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS unsubscribed boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS utm_source text,
ADD COLUMN IF NOT EXISTS utm_medium text,
ADD COLUMN IF NOT EXISTS utm_campaign text;

-- Allow service_role to write (for the email system)
-- These policies may already exist, so use IF NOT EXISTS pattern
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role full access' AND tablename = 'webinar_registrations') THEN
        CREATE POLICY "Service role full access" ON webinar_registrations FOR ALL TO service_role USING (true);
    END IF;
END $$;
