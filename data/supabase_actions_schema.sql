-- ============================================================
-- Ads Action Queue — Execute actions from the dashboard
-- Run this in your backoffice Supabase SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS ads_action_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What to do
    action_type text NOT NULL,  -- pause_ad / activate_ad / pause_adset / activate_adset / pause_campaign / activate_campaign / update_budget / refresh_sync / generate_creative

    -- What to do it to
    entity_id text,             -- Meta ad/adset/campaign ID
    entity_name text,           -- Human-readable name (for display)
    entity_type text,           -- ad / adset / campaign

    -- Parameters (for budget changes, creative generation, etc.)
    params jsonb DEFAULT '{}',  -- e.g. {"new_budget": 2000} or {"prompt": "..."}

    -- Status tracking
    status text DEFAULT 'pending',  -- pending / processing / completed / failed
    result text,                    -- Success message or error details

    -- Who/when
    requested_by text DEFAULT 'dashboard',
    requested_at timestamptz DEFAULT now(),
    processed_at timestamptz,

    -- For display in the dashboard
    display_message text           -- "Pausing ad '90% Never Make Money'..."
);

CREATE INDEX IF NOT EXISTS idx_action_queue_status ON ads_action_queue(status, requested_at DESC);

-- RLS
ALTER TABLE ads_action_queue ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow authenticated read" ON ads_action_queue FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated insert" ON ads_action_queue FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Service role full access" ON ads_action_queue FOR ALL TO service_role USING (true);
