-- AI Analyst Briefings — Daily intelligence reports
-- Run this in your backoffice Supabase SQL Editor

CREATE TABLE IF NOT EXISTS ads_ai_briefings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- When
    created_at timestamptz DEFAULT now(),
    period text NOT NULL,          -- 'every_4h' / 'daily' / 'weekly'

    -- The briefing
    summary text NOT NULL,         -- 2-3 sentence executive summary

    -- Decisions made
    actions_taken jsonb DEFAULT '[]',    -- [{action, entity, reason}] — what the AI auto-did
    actions_suggested jsonb DEFAULT '[]', -- [{action, entity, reason}] — what needs human approval

    -- Analysis
    performance_grade text,        -- A/B/C/D/F
    top_performer jsonb,           -- {ad_name, metric, value, why}
    worst_performer jsonb,         -- {ad_name, metric, value, why}
    patterns_detected jsonb DEFAULT '[]',  -- ["UGC outperforms static by 2x", ...]

    -- Strategy
    strategic_recommendations jsonb DEFAULT '[]',  -- [{recommendation, reasoning, priority}]
    next_creative_briefs jsonb DEFAULT '[]',        -- [{concept, hook, angle, why}]
    budget_recommendations jsonb DEFAULT '[]',      -- [{from, to, amount, reasoning}]

    -- Raw AI response (for debugging)
    raw_response text
);

CREATE INDEX IF NOT EXISTS idx_briefings_created ON ads_ai_briefings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_briefings_period ON ads_ai_briefings(period, created_at DESC);

ALTER TABLE ads_ai_briefings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated read" ON ads_ai_briefings FOR SELECT TO authenticated USING (true);
CREATE POLICY "Service role full access" ON ads_ai_briefings FOR ALL TO service_role USING (true);
