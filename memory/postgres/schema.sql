CREATE TABLE IF NOT EXISTS agents (
    agent_id UUID PRIMARY KEY,
    state TEXT,
    model_name TEXT,
    model_key TEXT,
    workflow_id UUID,
    task_type TEXT,
    gpu_slot TEXT,
    tokens_used INTEGER DEFAULT 0,
    token_budget INTEGER DEFAULT 4000,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3
);

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id UUID PRIMARY KEY,
    name TEXT,
    status TEXT,
    dag_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY,
    workflow_id UUID REFERENCES workflows(workflow_id),
    agent_id UUID,
    name TEXT,
    task_type TEXT,
    status TEXT,
    model_used TEXT,
    tokens_used INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result_json JSONB
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id UUID PRIMARY KEY,
    workflow_id UUID UNIQUE,
    step_name TEXT,
    progress FLOAT,
    model_name TEXT,
    state_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_metrics (
    metric_id UUID PRIMARY KEY,
    model_name TEXT,
    task_type TEXT,
    latency_ms FLOAT,
    tokens_used INTEGER,
    success BOOLEAN,
    hallucination_flag BOOLEAN,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE agents ADD COLUMN IF NOT EXISTS model_key TEXT;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS task_type TEXT;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS tokens_used INTEGER DEFAULT 0;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS token_budget INTEGER DEFAULT 4000;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 3;

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type TEXT;
