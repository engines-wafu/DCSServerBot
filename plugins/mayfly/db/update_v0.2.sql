-- Mayfly v0.2: Add persistence storage columns and version history table
-- Stores F-4E .cache files (~2MB each) directly in PostgreSQL,
-- replacing the external S3 sync workflow.

-- Add persistence binary storage to aircraft table
ALTER TABLE mayfly_aircraft ADD COLUMN IF NOT EXISTS persistence_data BYTEA;
ALTER TABLE mayfly_aircraft ADD COLUMN IF NOT EXISTS persistence_updated_at TIMESTAMPTZ;

-- Persistence version history (equivalent to S3 bucket versioning for rollback)
CREATE TABLE IF NOT EXISTS mayfly_persistence_history (
    id SERIAL PRIMARY KEY,
    aircraft_id INTEGER NOT NULL REFERENCES mayfly_aircraft(id) ON DELETE CASCADE,
    persistence_data BYTEA NOT NULL,
    uploaded_by_ucid TEXT REFERENCES players (ucid) ON UPDATE CASCADE ON DELETE SET NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    source TEXT NOT NULL DEFAULT 'unknown',
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_mayfly_persistence_history_aircraft ON mayfly_persistence_history (aircraft_id);
CREATE INDEX IF NOT EXISTS idx_mayfly_persistence_history_uploaded ON mayfly_persistence_history (uploaded_at);
