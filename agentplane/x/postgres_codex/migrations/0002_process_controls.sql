-- Additive upgrade for disposable experiment databases initialized before process controls.
-- Fresh databases are still initialized from SQLAlchemy metadata by `main_bin init`.
ALTER TABLE spike_conversation ADD COLUMN stopped boolean NOT NULL DEFAULT false;
ALTER TABLE spike_conversation ADD COLUMN executor_session varchar;

CREATE TABLE spike_process (
    id varchar PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES spike_conversation(id),
    generation integer NOT NULL,
    after_seq integer,
    status varchar NOT NULL,
    tty boolean NOT NULL,
    exit_code integer
);

CREATE TABLE spike_cell (
    id varchar NOT NULL,
    conversation_id uuid NOT NULL REFERENCES spike_conversation(id),
    generation integer NOT NULL,
    status varchar NOT NULL,
    PRIMARY KEY (id, conversation_id, generation)
);

CREATE TABLE spike_interrupt (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES spike_conversation(id),
    generation integer NOT NULL,
    result jsonb
);
