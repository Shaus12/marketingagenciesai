-- ============================================================
-- BuildLoop Ads Command Center — Supabase Schema
-- Run this in your Supabase SQL Editor
-- ============================================================

-- 1. DASHBOARD SNAPSHOT (single row, updated every hour)
-- "At a glance" — what's happening RIGHT NOW
CREATE TABLE IF NOT EXISTS ads_dashboard (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Today
    today_spend decimal DEFAULT 0,
    today_impressions integer DEFAULT 0,
    today_clicks integer DEFAULT 0,
    today_conversions integer DEFAULT 0,
    today_cpa decimal DEFAULT 0,
    today_roas decimal DEFAULT 0,
    today_ctr decimal DEFAULT 0,

    -- vs Yesterday
    yesterday_spend decimal DEFAULT 0,
    yesterday_conversions integer DEFAULT 0,
    yesterday_cpa decimal DEFAULT 0,
    yesterday_roas decimal DEFAULT 0,
    spend_vs_yesterday_pct decimal DEFAULT 0,  -- +12% or -5%

    -- This Week
    week_spend decimal DEFAULT 0,
    week_conversions integer DEFAULT 0,
    week_cpa decimal DEFAULT 0,
    week_roas decimal DEFAULT 0,

    -- This Month
    month_spend decimal DEFAULT 0,
    month_conversions integer DEFAULT 0,
    month_revenue decimal DEFAULT 0,
    month_roas decimal DEFAULT 0,

    -- Health
    overall_status text DEFAULT 'no_data', -- healthy / needs_attention / critical / no_data
    status_reason text,                     -- "CPA is 20% above target"
    active_ads_count integer DEFAULT 0,
    paused_ads_count integer DEFAULT 0,

    last_updated_at timestamptz DEFAULT now()
);

-- 2. CAMPAIGN STATUS (one row per campaign, updated daily)
CREATE TABLE IF NOT EXISTS ads_campaign_status (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id text UNIQUE NOT NULL,
    campaign_name text NOT NULL,
    campaign_type text NOT NULL,  -- scale / iterate / test / retarget

    status text DEFAULT 'PAUSED',  -- ACTIVE / PAUSED
    daily_budget decimal DEFAULT 0,

    -- Performance (rolling)
    spend_today decimal DEFAULT 0,
    spend_7d decimal DEFAULT 0,
    spend_30d decimal DEFAULT 0,
    conversions_today integer DEFAULT 0,
    conversions_7d integer DEFAULT 0,
    conversions_30d integer DEFAULT 0,
    cpa_7d decimal,
    roas_7d decimal,
    ctr_7d decimal,

    -- Health
    health_status text DEFAULT 'neutral',  -- green / yellow / red / neutral
    health_reason text,

    -- Budget allocation
    budget_pct_actual decimal,  -- what % of total spend this campaign uses
    budget_pct_target decimal, -- what % it SHOULD use (70/20/10)

    last_updated_at timestamptz DEFAULT now()
);

-- 3. AD PERFORMANCE (one row per ad per day — the detailed log)
CREATE TABLE IF NOT EXISTS ads_daily_performance (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    date date NOT NULL,

    -- Identity
    ad_id text NOT NULL,
    ad_name text,
    adset_id text,
    adset_name text,
    campaign_id text,
    campaign_type text,  -- scale / iterate / test / retarget

    -- Core metrics
    spend decimal DEFAULT 0,
    impressions integer DEFAULT 0,
    reach integer DEFAULT 0,
    frequency decimal DEFAULT 0,
    clicks integer DEFAULT 0,
    ctr decimal DEFAULT 0,
    cpc decimal DEFAULT 0,
    cpm decimal DEFAULT 0,

    -- Conversion metrics
    conversions integer DEFAULT 0,
    cpa decimal,
    revenue decimal DEFAULT 0,
    roas decimal DEFAULT 0,

    -- Creative metrics
    hook_rate decimal,       -- 3-sec views / impressions
    hold_rate decimal,       -- 15-sec views / 3-sec views
    video_views_3s integer DEFAULT 0,
    video_views_15s integer DEFAULT 0,

    -- Status
    status_emoji text,  -- 🟢 🟡 🔴 ⚪
    status_note text,   -- "Outperforming by 30%" or "CPA too high"

    created_at timestamptz DEFAULT now(),

    UNIQUE(ad_id, date)
);

-- 4. TODOS (action items — system-generated and manual)
CREATE TABLE IF NOT EXISTS ads_todos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    title text NOT NULL,
    description text,
    category text NOT NULL,  -- creative / scaling / kill / fix / research / setup
    priority text DEFAULT 'medium',  -- critical / high / medium / low
    status text DEFAULT 'pending',   -- pending / in_progress / done / dismissed

    -- Context
    source text DEFAULT 'system',  -- system / manual / community
    related_ad_id text,
    related_campaign text,
    related_metric text,           -- "CPA was €85 vs target €50"

    -- Timing
    due_date date,
    created_at timestamptz DEFAULT now(),
    completed_at timestamptz,

    -- For creative todos: what to film/create
    creative_brief text,           -- detailed brief if this is a creative task
    hook_suggestions jsonb,        -- ["hook 1", "hook 2", ...]
    reference_ads jsonb            -- [{"ad_id": "...", "reason": "this hook worked"}]
);

-- 5. CREATIVE PIPELINE (what's being created, what's live, what died)
CREATE TABLE IF NOT EXISTS ads_creative_pipeline (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    title text NOT NULL,
    concept text,              -- what's the idea
    angle text,                -- which angle (builder's problem, 3 paths, proof, etc.)
    hook text,                 -- the specific hook line

    format text NOT NULL,      -- video / static / carousel / ugc / screen_recording
    status text DEFAULT 'idea', -- idea / brief_ready / in_production / ready / live / paused / killed

    -- Source
    source text,               -- community / data_insight / competitor / manual / ai_generated
    source_detail text,        -- which community post, which data insight

    -- Scoring
    priority_score integer DEFAULT 50,  -- 0-100, higher = do first
    estimated_hook_rate decimal,        -- predicted based on patterns

    -- When it goes live
    assigned_ad_id text,
    assigned_adset text,
    went_live_at timestamptz,

    -- Performance (filled after it runs)
    actual_hook_rate decimal,
    actual_ctr decimal,
    actual_cpa decimal,
    actual_roas decimal,
    actual_spend decimal,
    performance_verdict text,   -- winner / average / loser

    -- Copy
    primary_text text,         -- the ad copy
    headline text,
    description_text text,
    cta_type text,             -- LEARN_MORE / SIGN_UP / etc.

    -- Assets
    image_url text,
    video_url text,

    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- 6. ALERTS (things that need your attention)
CREATE TABLE IF NOT EXISTS ads_alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    type text NOT NULL,         -- kill / scale / fatigue / budget / error / winner / milestone
    severity text NOT NULL,     -- critical / warning / info / positive

    title text NOT NULL,        -- "Ad 'Hook #3' has spent €45 with 0 conversions"
    message text,               -- detailed explanation

    -- What it's about
    related_entity_id text,
    related_entity_type text,   -- ad / adset / campaign / account
    related_entity_name text,

    -- Action
    suggested_action text,      -- "Pause this ad" / "Increase budget 20%"
    action_taken text,          -- what was actually done

    status text DEFAULT 'new',  -- new / acknowledged / action_taken / dismissed

    created_at timestamptz DEFAULT now(),
    resolved_at timestamptz
);

-- 7. WEEKLY INSIGHTS (AI-generated weekly intelligence)
CREATE TABLE IF NOT EXISTS ads_weekly_insights (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    week_start date NOT NULL,
    week_end date NOT NULL,

    -- Summary
    summary text,               -- human-readable 3-5 sentence summary
    overall_grade text,         -- A / B / C / D / F

    -- Key numbers
    total_spend decimal,
    total_conversions integer,
    avg_cpa decimal,
    avg_roas decimal,

    -- What worked
    top_performers jsonb,       -- [{ad_id, name, roas, cpa, why_it_worked}]
    winning_patterns jsonb,     -- ["UGC outperforms polished by 2.3x", ...]

    -- What didn't work
    worst_performers jsonb,     -- [{ad_id, name, roas, cpa, what_went_wrong}]

    -- Recommendations
    recommendations jsonb,      -- [{action, reason, priority}]
    creative_suggestions jsonb, -- [{concept, hook, angle, reason}]

    -- Community intelligence
    community_angles jsonb,     -- [{angle, source, suggested_hook}]
    trending_topics jsonb,      -- what the community is talking about

    created_at timestamptz DEFAULT now()
);

-- 8. FUNNEL TRACKING (webinar-specific metrics)
CREATE TABLE IF NOT EXISTS ads_funnel_metrics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    date date NOT NULL UNIQUE,

    -- Top of funnel
    ad_impressions integer DEFAULT 0,
    ad_clicks integer DEFAULT 0,
    ad_spend decimal DEFAULT 0,

    -- Registration
    page_visitors integer DEFAULT 0,
    registrations integer DEFAULT 0,
    registration_rate decimal,     -- registrations / page_visitors
    cost_per_lead decimal,         -- ad_spend / registrations

    -- Webinar
    attendees integer DEFAULT 0,
    show_rate decimal,             -- attendees / registrations

    -- Conversion
    sales integer DEFAULT 0,
    revenue decimal DEFAULT 0,
    conversion_rate decimal,       -- sales / attendees
    cost_per_sale decimal,         -- ad_spend / sales
    roas decimal,                  -- revenue / ad_spend

    -- Downsells
    box_sales integer DEFAULT 0,
    box_revenue decimal DEFAULT 0,

    created_at timestamptz DEFAULT now()
);

-- ============================================================
-- INDEXES for fast queries
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_daily_perf_date ON ads_daily_performance(date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_perf_ad ON ads_daily_performance(ad_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_perf_campaign ON ads_daily_performance(campaign_type, date DESC);
CREATE INDEX IF NOT EXISTS idx_todos_status ON ads_todos(status, priority);
CREATE INDEX IF NOT EXISTS idx_todos_category ON ads_todos(category, status);
CREATE INDEX IF NOT EXISTS idx_creative_status ON ads_creative_pipeline(status);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON ads_alerts(status, severity);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON ads_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_funnel_date ON ads_funnel_metrics(date DESC);

-- ============================================================
-- ENABLE RLS (but allow service_role full access)
-- ============================================================
ALTER TABLE ads_dashboard ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_campaign_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_daily_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_todos ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_creative_pipeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_weekly_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_funnel_metrics ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read everything
CREATE POLICY "Allow authenticated read" ON ads_dashboard FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_campaign_status FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_daily_performance FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_todos FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_creative_pipeline FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_alerts FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_weekly_insights FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated read" ON ads_funnel_metrics FOR SELECT TO authenticated USING (true);

-- Allow authenticated users to update todos and alerts (mark as done, acknowledge)
CREATE POLICY "Allow authenticated update" ON ads_todos FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Allow authenticated update" ON ads_alerts FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Allow authenticated update" ON ads_creative_pipeline FOR UPDATE TO authenticated USING (true);

-- Service role has full access (for the automation system to write data)
CREATE POLICY "Service role full access" ON ads_dashboard FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_campaign_status FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_daily_performance FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_todos FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_creative_pipeline FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_alerts FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_weekly_insights FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access" ON ads_funnel_metrics FOR ALL TO service_role USING (true);
