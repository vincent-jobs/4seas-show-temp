CREATE TABLE IF NOT EXISTS eight_sleep_days (
    source_id text NOT NULL REFERENCES sources(id),
    user_id text NOT NULL,
    day date NOT NULL,
    data jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, user_id, day)
);

CREATE TABLE IF NOT EXISTS eight_sleep_sync (
    source_id text NOT NULL REFERENCES sources(id),
    user_id text NOT NULL,
    next_before date NOT NULL,
    complete boolean NOT NULL DEFAULT false,
    PRIMARY KEY (source_id, user_id)
);
