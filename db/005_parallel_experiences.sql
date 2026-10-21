ALTER TABLE experiences ADD COLUMN IF NOT EXISTS heart_source_id text REFERENCES sources(id);
ALTER TABLE experiences ADD COLUMN IF NOT EXISTS client_id uuid;
DROP INDEX IF EXISTS experiences_one_active_idx;
CREATE UNIQUE INDEX IF NOT EXISTS experiences_active_band_idx
    ON experiences (heart_source_id) WHERE ended_at IS NULL AND heart_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS experiences_active_client_idx
    ON experiences (client_id) WHERE ended_at IS NULL AND client_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS experience_samples (
    experience_id uuid NOT NULL REFERENCES experiences(id),
    sample_id bigint NOT NULL REFERENCES samples(id),
    PRIMARY KEY (experience_id, sample_id)
);
CREATE INDEX IF NOT EXISTS experience_samples_sample_idx ON experience_samples (sample_id);
INSERT INTO experience_samples (experience_id, sample_id)
    SELECT experience_id, id FROM samples WHERE experience_id IS NOT NULL ON CONFLICT DO NOTHING;
