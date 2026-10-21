CREATE TABLE IF NOT EXISTS experiences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 60),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ended_at timestamptz CHECK (ended_at >= started_at)
);
-- This installation has one room and one active participant at a time.
CREATE UNIQUE INDEX IF NOT EXISTS experiences_one_active_idx
    ON experiences ((true)) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS experiences_started_idx ON experiences (started_at DESC);
ALTER TABLE samples ADD COLUMN IF NOT EXISTS experience_id uuid REFERENCES experiences(id);
CREATE INDEX IF NOT EXISTS samples_experience_id_idx ON samples (experience_id, id DESC);
