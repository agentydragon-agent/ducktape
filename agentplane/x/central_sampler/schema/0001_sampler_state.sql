-- +goose Up
CREATE TABLE sampler_conversation (
    id UUID PRIMARY KEY,
    generation INTEGER NOT NULL DEFAULT 0,
    owner UUID,
    lease_until TIMESTAMPTZ,
    pending JSONB,
    stopped BOOLEAN NOT NULL DEFAULT FALSE,
    executor_session VARCHAR,
    context_items JSONB,
    instructions TEXT,
    context_tokens INTEGER
);

CREATE TABLE sampler_conversation_item (
    conversation_id UUID NOT NULL REFERENCES sampler_conversation(id),
    ordinal BIGINT NOT NULL CHECK (ordinal > 0),
    item JSONB NOT NULL,
    PRIMARY KEY (conversation_id, ordinal)
);

CREATE TABLE sampler_intent (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES sampler_conversation(id),
    generation INTEGER NOT NULL,
    request JSONB NOT NULL,
    result JSONB
);

CREATE TABLE sampler_process (
    id VARCHAR PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES sampler_conversation(id),
    generation INTEGER NOT NULL,
    after_seq INTEGER,
    status VARCHAR NOT NULL,
    tty BOOLEAN NOT NULL,
    exit_code INTEGER,
    buffered_output BYTEA NOT NULL DEFAULT ''::bytea
);

CREATE TABLE sampler_cell (
    id VARCHAR NOT NULL,
    conversation_id UUID NOT NULL REFERENCES sampler_conversation(id),
    generation INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    PRIMARY KEY (id, conversation_id, generation)
);

CREATE TABLE sampler_interrupt (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES sampler_conversation(id),
    generation INTEGER NOT NULL,
    target_turn VARCHAR,
    result JSONB
);

CREATE TABLE sampler_session (
    id VARCHAR PRIMARY KEY,
    conversation_id UUID NOT NULL UNIQUE REFERENCES sampler_conversation(id),
    account_uid VARCHAR NOT NULL,
    configuration BYTEA NOT NULL,
    model VARCHAR NOT NULL,
    effort VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    cursor INTEGER NOT NULL DEFAULT 0,
    active_turn VARCHAR,
    active_command VARCHAR,
    workspace_prepared BOOLEAN NOT NULL DEFAULT FALSE,
    setup_state INTEGER NOT NULL DEFAULT 1,
    setup_started BOOLEAN NOT NULL DEFAULT FALSE,
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason VARCHAR
);

CREATE TABLE sampler_command (
    session_id VARCHAR NOT NULL REFERENCES sampler_session(id),
    id VARCHAR NOT NULL,
    payload BYTEA NOT NULL,
    admission INTEGER NOT NULL,
    outcome INTEGER NOT NULL,
    failure_reason VARCHAR,
    PRIMARY KEY (session_id, id)
);

CREATE TABLE sampler_event (
    session_id VARCHAR NOT NULL REFERENCES sampler_session(id),
    sequence INTEGER NOT NULL,
    entry BYTEA NOT NULL,
    PRIMARY KEY (session_id, sequence)
);

CREATE TABLE sampler_export_checkpoint (
    session_id VARCHAR NOT NULL REFERENCES sampler_session(id),
    destination VARCHAR NOT NULL,
    cursor INTEGER NOT NULL,
    PRIMARY KEY (session_id, destination)
);

CREATE INDEX sampler_intent_unresolved_idx ON sampler_intent(conversation_id) WHERE result IS NULL;
CREATE INDEX sampler_interrupt_pending_idx ON sampler_interrupt(conversation_id, generation) WHERE result IS NULL;
CREATE INDEX sampler_command_queue_idx ON sampler_command(session_id, admission) WHERE outcome = 1;
CREATE INDEX sampler_event_sequence_idx ON sampler_event(session_id, sequence);

-- +goose Down
-- Durable sampler state has no safe downgrade. Restore a database backup to revert a migration.
