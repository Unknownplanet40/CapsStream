-- ==============================================================================
-- CapsStream Media Requests Table Schema for Supabase
--
-- Instructions:
-- 1. Open your Supabase project dashboard (https://supabase.com/dashboard)
-- 2. Navigate to "SQL Editor" in the left sidebar
-- 3. Click "New Query", paste the entire contents of this file, and click "Run"
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.media_requests (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'Movie',
    year TEXT,
    season INTEGER,
    episode INTEGER,
    notes TEXT,
    tmdb_id BIGINT,
    poster_path TEXT,
    backdrop_path TEXT,
    overview TEXT,
    vote_average NUMERIC(3, 1),
    has_digital_release BOOLEAN,
    digital_release_date TEXT,
    digital_status_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending', 'in_progress', 'completed', 'rejected'
    admin_note TEXT,                         -- Notes from Desktop 1 (DEV server) back to requester
    requested_by TEXT,
    profile_avatar TEXT,
    custom_avatar_url TEXT,
    profile_color TEXT,
    detected_media_id INTEGER,
    detected_media_type TEXT,
    detected_tmdb_id BIGINT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indices for rapid querying by client and status
CREATE INDEX IF NOT EXISTS idx_media_requests_client_id ON public.media_requests (client_id);
CREATE INDEX IF NOT EXISTS idx_media_requests_status ON public.media_requests (status);
CREATE INDEX IF NOT EXISTS idx_media_requests_created_at ON public.media_requests (created_at DESC);

-- Enable Row Level Security (RLS) or public access policy
-- For standard anonymous public key access:
ALTER TABLE public.media_requests ENABLE ROW LEVEL SECURITY;

-- Allow anonymous clients to read, insert, update, and delete requests
-- (Client isolation is enforced by client_id parameter in CapsStream queries)
CREATE POLICY "Allow anon read" ON public.media_requests
    FOR SELECT USING (true);

CREATE POLICY "Allow anon insert" ON public.media_requests
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow anon update" ON public.media_requests
    FOR UPDATE USING (true);

CREATE POLICY "Allow anon delete" ON public.media_requests
    FOR DELETE USING (true);
