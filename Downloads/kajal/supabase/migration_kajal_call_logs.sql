-- Kajal Voice Engine — Supabase Migration
-- Creates the call_logs table for tracking all AI voice calls

CREATE TABLE IF NOT EXISTS call_logs (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    call_sid        TEXT NOT NULL,
    phone           TEXT,
    event_type      TEXT NOT NULL,   -- started | ended | transferred | site_visit_booked
    transcript      TEXT,
    source          TEXT DEFAULT 'kajal_voice',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup by phone and call_sid
CREATE INDEX IF NOT EXISTS idx_call_logs_phone    ON call_logs(phone);
CREATE INDEX IF NOT EXISTS idx_call_logs_call_sid ON call_logs(call_sid);
CREATE INDEX IF NOT EXISTS idx_call_logs_created  ON call_logs(created_at DESC);

-- Add kajal-specific columns to leads table if not already present
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_called_by   TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS kajal_notes      TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS language_preference TEXT DEFAULT 'Hinglish';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS agent_name       TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS project_name     TEXT;
