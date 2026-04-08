-- YouTube Growth Engine — Content generation tables
-- Run this in your BACKOFFICE Supabase SQL Editor

-- 1. SHORTS SCRIPTS
CREATE TABLE IF NOT EXISTS yt_shorts_scripts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    hook text NOT NULL,
    segment_start text,
    segment_end text,
    transcript_excerpt text,
    why_it_works text,
    suggested_cta text,
    source_video text NOT NULL,
    source_video_id text,
    source_views integer DEFAULT 0,
    status text DEFAULT 'new',  -- new / approved / recorded / published / rejected
    published_url text,
    created_at timestamptz DEFAULT now(),
    week_generated text          -- "2026-W14" format
);

-- 2. COMMUNITY POSTS
CREATE TABLE IF NOT EXISTS yt_community_posts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    day text NOT NULL,           -- Monday, Tuesday, etc.
    type text NOT NULL,          -- POLL / VALUE / WEBINAR / HOT_TAKE / SOCIAL_PROOF / QUESTION / BTS
    text text NOT NULL,
    poll_options jsonb,          -- ["option 1", "option 2", ...] for polls
    best_time text,              -- morning / afternoon / evening
    engagement_prediction text,  -- high / medium / low
    reasoning text,
    status text DEFAULT 'new',  -- new / approved / posted / rejected
    posted_at timestamptz,
    engagement_actual jsonb,     -- {"likes": 50, "comments": 12} after posting
    created_at timestamptz DEFAULT now(),
    week_generated text
);

-- 3. AD CANDIDATES (YouTube hooks → Meta ads)
CREATE TABLE IF NOT EXISTS yt_ad_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_video_title text NOT NULL,
    source_video_id text,
    source_views integer DEFAULT 0,
    engagement_rate decimal,
    ad_script_30s text,
    primary_text text,
    headline text,
    why_this_works text,
    priority text DEFAULT 'medium',  -- high / medium / low
    status text DEFAULT 'new',       -- new / approved / created / live / rejected
    meta_ad_id text,                 -- if deployed as a Meta ad
    meta_performance jsonb,          -- {spend, clicks, ctr, conversions} after running
    created_at timestamptz DEFAULT now(),
    week_generated text
);

-- INDEXES
CREATE INDEX IF NOT EXISTS idx_shorts_status ON yt_shorts_scripts(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shorts_week ON yt_shorts_scripts(week_generated);
CREATE INDEX IF NOT EXISTS idx_community_status ON yt_community_posts(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_week ON yt_community_posts(week_generated);
CREATE INDEX IF NOT EXISTS idx_ad_candidates_status ON yt_ad_candidates(status, priority);
CREATE INDEX IF NOT EXISTS idx_ad_candidates_week ON yt_ad_candidates(week_generated);

-- RLS
ALTER TABLE yt_shorts_scripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE yt_community_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE yt_ad_candidates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow authenticated read" ON yt_shorts_scripts FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated update" ON yt_shorts_scripts FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Service role full access" ON yt_shorts_scripts FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read" ON yt_community_posts FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated update" ON yt_community_posts FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Service role full access" ON yt_community_posts FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read" ON yt_ad_candidates FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated update" ON yt_ad_candidates FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Service role full access" ON yt_ad_candidates FOR ALL TO service_role USING (true);
