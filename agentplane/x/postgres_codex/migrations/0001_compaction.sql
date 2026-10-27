-- Additive upgrade for databases created by the original experiment.
-- Run once, offline, before starting a sampler using compaction.
-- NULL context_items means the entire original items history remains active.
ALTER TABLE spike_conversation ADD COLUMN context_items JSONB;
ALTER TABLE spike_conversation ADD COLUMN instructions TEXT;
ALTER TABLE spike_conversation ADD COLUMN context_tokens INTEGER;
